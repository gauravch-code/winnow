# Changelog

Tags map to the 11-step build plan. Each was cut when its step's tests
passed, so `git log --oneline --decorate` is a durable checkpoint history.

## v1.1 — The real app
Closes the gap between the demo and a tool you run daily. Owner-scoped
dashboard API (`winnow_api/realapp/`: list, lane move, archive, star,
escalate), the tier-1 classifier now loads in real mode (fixing a latent
"everything is informational" bug), and live tier-2 wired in with the
WINNOW_LLM_API_KEY → provider-env bridge. Mode-aware dashboard (`apps/web`)
with "ask LLM" + draft display. One-command self-hosted stack
(`docker-compose.full.yml` + `apps/web/Dockerfile`). Google-Cloud-OAuth
run-on-your-Gmail guide. 166 tests.

## v1.0 — Polish
Full README (why-this-exists, architecture diagram, verified quickstart,
out-of-scope), `docs/architecture.md`, MIT `LICENSE`. All 11 steps complete;
public demo live.

## v0.8-evals — Eval harness
`winnow_api/eval/`: pure-classifier vs pure-LLM vs tiered on a held-out
split. `winnow eval` writes `docs/evals.md` + the `/evals` page data.
Threshold sweep. Provenance honestly labeled (stub vs live).

## v0.7-learning — Learning loop
Action→training-example writes, nightly APScheduler retrainer with
guardrails (min examples, regression gate, artifact rollback),
`classifier_metrics_history`, `winnow retrain` / `winnow rollback`.
Simulated-week test shows 0.58 → 1.00 lift.

## v0.6-gmail — Gmail integration (real mode)
Fernet-encrypted refresh token, `winnow bootstrap`, installed-app OAuth,
Gmail API client, `historyId` incremental sync + backfill + poll fallback,
Pub/Sub webhook. Hard import-gate keeps Gmail code out of the demo image.

## v0.5-public-demo — Marketing site + deploy
`apps/site` landing + embedded `/demo` with persistent banner and per-card
"ask LLM". Portable Dockerfile, `railway.json`, `fly.toml`, `DEPLOY.md`.
Later deployed to Railway (API) + Vercel (site).

## v0.4-fixtures — Pre-recorded tier-2
`generate.py` (real LLM) + `generate_stub_fixtures.py` (offline), 200
committed fixtures, canonical hashes, `check-fixtures-fresh` CI gate.

## v0.3-tier2 — LLM tier
PydanticAI structured output, provider factory (Anthropic/OpenAI/Ollama),
confidence-threshold orchestrator, live + fixture providers, escalate route.

## v0.2-classifier — Tier-1
MiniLM + logistic-regression classifier, signed per-feature explainability,
wired into the demo seeder, API, and UI panel.

## v0.1-demo — Foundation
Postgres schema with the dual-scope invariant, session-cookie demo backend,
Next.js three-lane drag-and-drop dashboard, 200 synthetic emails.
