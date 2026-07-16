# Winnow

Local-first AI inbox triage. Runs a small classifier on your machine for
80%+ of email routing decisions, escalates only uncertain cases to an
LLM, and never sends your inbox anywhere you didn't opt in to.

**Status:** `v0.1-demo` — synthetic-data dashboard with drag-and-drop
triage. Classifier tier, LLM tier, and Gmail integration land in later
steps.

## Getting started (local dev)

```
# 1. Start Postgres
docker compose up -d postgres

# 2. Install deps
uv sync --all-packages
uv pip install "uvicorn[standard]"
(cd apps/web && npm install)

# 3. Migrate + generate seed emails
cd apps/api && WINNOW_DATABASE_URL=postgresql+psycopg://winnow:winnow@localhost:5432/winnow \
  ../../.venv/Scripts/alembic upgrade head && cd ../..
.venv/Scripts/python packages/seed-data/generate_emails.py

# 4. Boot the demo (two shells)
.venv/Scripts/uvicorn winnow_api.main:app --port 8000 --app-dir apps/api
cd apps/web && npm run dev

# 5. Open http://localhost:3000
```

Configuration comes from environment variables — see [`.env.example`](.env.example).
`WINNOW_MODE=demo` requires an empty `users` table; `WINNOW_MODE=real`
requires exactly one owner row. The API refuses to boot if either
invariant is violated.

## Repository layout

```
apps/
  api/    FastAPI backend (real app + demo mode share this)
  web/    Next.js 15 demo dashboard (App Router + Tailwind + dnd-kit)
packages/
  seed-data/  Synthetic emails + Pydantic schemas for LLM fixtures
```

## Explicitly out of scope

- Multi-account support, non-Gmail providers, team inboxes, mobile app
- Auto-sending replies (drafts only)
- Live LLM calls in the public demo (pre-recorded fixtures instead)
- Hosting Winnow-as-a-service for other people's real inboxes

## Notes

- **pnpm vs npm**: the plan specifies pnpm, but this repo uses npm for
  the initial bootstrap so it works without corepack/global installs.
  Swap in pnpm freely — `package.json` is unchanged.
