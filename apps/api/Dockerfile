# Portable Dockerfile for the Winnow API. Runs identically on Railway,
# Fly.io, Render, or plain `docker run`.
#
# Two-stage build so the final image doesn't carry uv, build toolchains,
# or the ~500MB torch wheel cache. Final image is ~1.2GB — dominated by
# torch + MiniLM — which is fine for a $5/mo Railway hobby VM.
#
# Ships the pre-trained tier-1 classifier artifact and the 200 fixture
# JSON files. Demo mode boots without needing to download models or
# call an LLM.

# ---------- builder ----------
FROM python:3.12-slim AS builder

# uv is much faster than pip and gives us reproducible installs.
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /build

# Copy the workspace root + both members' source. Two-phase install
# (deps first, then source) would give slightly better local rebuild
# caching, but ``uv sync --no-install-workspace`` at the workspace root
# only installs the *root* project's deps — not workspace members'
# deps — which is how the previous version silently shipped an image
# without sentence-transformers, torch, etc. Combining into one COPY +
# one sync is correct; Railway rebuilds from scratch every push so we
# aren't losing meaningful caching.
COPY pyproject.toml uv.lock ./
COPY apps/api/ apps/api/
COPY packages/seed-data/ packages/seed-data/

# Resolve + install everything into a venv. ``--frozen`` enforces an
# up-to-date uv.lock (fail-fast if a dep drifted). ``--all-packages``
# installs the root project AND every workspace member editable, with
# their transitive deps — the flag combination that actually gets
# sentence-transformers, torch, apscheduler, typer, google-api into
# the runtime image.
RUN uv venv /build/.venv && \
    VIRTUAL_ENV=/build/.venv uv sync --frozen --all-packages

# Pre-download the MiniLM weights so first request doesn't pay the
# ~90MB download at startup on a fresh container. Model lives in
# ~/.cache/huggingface which we bake into the image.
ENV HF_HOME=/build/.hf_cache
RUN /build/.venv/bin/python -c "\
from sentence_transformers import SentenceTransformer; \
SentenceTransformer('sentence-transformers/all-MiniLM-L6-v2')"

# ---------- runtime ----------
FROM python:3.12-slim AS runtime

# Non-root user. Prevents accidental writes outside /app and satisfies
# platforms that enforce non-root (Fly.io deploys are fine either way,
# Railway rootless is easier).
RUN groupadd --system winnow && useradd --system --gid winnow --home /app winnow

WORKDIR /app

# Pull in the venv, workspace, artifact + fixtures, and the cached
# MiniLM weights from the builder.
COPY --from=builder --chown=winnow:winnow /build/.venv /app/.venv
COPY --from=builder --chown=winnow:winnow /build/apps/api /app/apps/api
COPY --from=builder --chown=winnow:winnow /build/packages/seed-data /app/packages/seed-data
COPY --from=builder --chown=winnow:winnow /build/.hf_cache /app/.hf_cache

ENV PATH=/app/.venv/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    HF_HOME=/app/.hf_cache \
    WINNOW_FIXTURE_DIR=/app/packages/seed-data/llm-responses \
    WINNOW_SEED_EMAIL_DIR=/app/packages/seed-data/emails

USER winnow

EXPOSE 8000

# Healthcheck hits /health on whatever port uvicorn actually bound to.
# Uses $PORT so it stays consistent with the CMD below.
HEALTHCHECK --interval=15s --timeout=5s --start-period=30s --retries=3 \
    CMD python -c "import os,urllib.request,sys; urllib.request.urlopen(f'http://localhost:{os.environ.get(\"PORT\",\"8000\")}/health',timeout=3); sys.exit(0)" || exit 1

# Run migrations then start uvicorn. Bind to $PORT when a platform
# injects one (Railway, Render, Fly's default), fall back to 8000 for
# plain `docker run` locally. Railway routes traffic to $PORT, so a
# hardcoded 8000 here would silently blackhole every request.
CMD ["sh", "-c", "cd apps/api && alembic upgrade head && cd ../.. && uvicorn winnow_api.main:app --app-dir apps/api --host 0.0.0.0 --port ${PORT:-8000}"]
