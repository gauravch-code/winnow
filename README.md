# Winnow

Local-first AI inbox triage. Runs a small classifier on your machine for
80%+ of email routing decisions, escalates only uncertain cases to an
LLM, and never sends your inbox anywhere you didn't opt in to.

**▶ [Try the live demo](https://winnow-eight.vercel.app/demo)** — synthetic
data, real tier-1 classifier running live in your session, pre-recorded
tier-2 LLM responses (keeps it free and abuse-proof). No signup, nothing
touches a real inbox.

**Status:** `v0.7-learning` — tiered classifier + LLM triage, explainability
panel, nightly learning loop, and Gmail integration all shipped. Public demo
deployed (Vercel + Railway). Eval harness (Step 10) and README polish
(Step 11) are next.

- **Demo site:** https://winnow-eight.vercel.app
- **Demo API:** https://winnow-api-production-6039.up.railway.app (demo mode)

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
