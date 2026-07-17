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

# Copy workspace layout — uv reads pyproject.toml and uv.lock from the
# root plus the two workspace members.
COPY pyproject.toml uv.lock ./
COPY apps/api/pyproject.toml apps/api/
COPY packages/seed-data/pyproject.toml packages/seed-data/

# Resolve + install into a venv. --frozen fails if uv.lock is stale,
# which is the behavior we want for reproducible container builds.
#
# No BuildKit cache mount: Railway's BuildKit rejects the syntax in
# multiple forms ("missing an id argument" for anonymous mounts,
# "missing the cacheKey prefix" once id= is added). Railway's platform
# already does layer-level caching, so the mount was optional. Local
# ``docker build`` behaves identically without it — just a tiny bit
# slower on repeat rebuilds, which is worth trading for a portable
# Dockerfile.
RUN uv venv /build/.venv && \
    VIRTUAL_ENV=/build/.venv uv sync --frozen --no-install-workspace

# Now install the workspace packages themselves. Copy source last so
# code changes don't invalidate the dep-install layer.
COPY apps/api/ apps/api/
COPY packages/seed-data/ packages/seed-data/
RUN VIRTUAL_ENV=/build/.venv uv pip install \
    --no-deps \
    -e apps/api \
    -e packages/seed-data

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

# Healthcheck hits /health, which returns 200 iff the mode invariant
# passed at boot. A failing container gets replaced by the platform.
HEALTHCHECK --interval=15s --timeout=5s --start-period=30s --retries=3 \
    CMD python -c "import urllib.request,sys; urllib.request.urlopen('http://localhost:8000/health',timeout=3); sys.exit(0)" || exit 1

# Run migrations then start uvicorn. Both platforms let us set the
# start command explicitly (Railway: startCommand in railway.json;
# Fly: [processes.app] cmd in fly.toml), so this ENTRYPOINT is only
# the default.
CMD ["sh", "-c", "cd apps/api && alembic upgrade head && cd ../.. && uvicorn winnow_api.main:app --app-dir apps/api --host 0.0.0.0 --port 8000"]
