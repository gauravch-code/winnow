# Winnow

Local-first AI inbox triage. Runs a small classifier on your machine for
80%+ of email routing decisions, escalates only uncertain cases to an
LLM, and never sends your inbox anywhere you didn't opt in to.

**▶ [Try the live demo](https://winnow-eight.vercel.app/demo)** — synthetic
data, real tier-1 classifier running live in your session, pre-recorded
tier-2 LLM responses (keeps it free and abuse-proof). No signup, nothing
touches a real inbox.

**Status:** `v0.8-evals` — tiered classifier + LLM triage, explainability
panel, nightly learning loop, Gmail integration, and the eval harness all
shipped. Public demo deployed (Vercel + Railway). README polish (Step 11) is
next.

- **Demo site:** https://winnow-eight.vercel.app
- **Demo API:** https://winnow-api-production-6039.up.railway.app (demo mode)

## Evals

Pure-classifier vs pure-LLM vs tiered, on a held-out 30% of the synthetic
corpus. Full breakdown + threshold sweep: [`docs/evals.md`](docs/evals.md)
and the [`/evals` page](https://winnow-eight.vercel.app/evals). Reproduce
with `winnow eval`.

| Strategy | Accuracy | Mean latency | Cost / 1000 | Escalated |
|---|---|---|---|---|
| Pure classifier (tier-1) | 100.0%\* | 4.6 ms | $0.0000 | 0% |
| Pure LLM (tier-2) | 100.0%\* | 1.20 s | $5.3012 | 100% |
| **Tiered (Winnow)** | **100.0%\*** | **5.1 ms** | **$0.0000** | **0%** |

The point isn't the accuracy column — the synthetic corpus is near-separable
so everything scores ~100%. The point is the **latency and cost**: tiered
gets the same routing as the LLM at classifier speed and $0, because tier-1
is confident on clean data and escalates ~0% at the default threshold.

\* _Tier-2 fixtures in the public demo are stubs whose lanes mirror ground
truth, so the LLM/tiered **accuracy** figures are illustrative, not
meaningful. Latency and cost are modeled from real token counts at Opus
pricing; classifier accuracy and escalation rate are measured. Run
`packages/seed-data/generate.py` with a real key for genuine LLM accuracy._

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
