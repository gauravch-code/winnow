# Winnow architecture

## One codebase, two modes

The FastAPI backend serves both the real self-hosted app and the public
demo. `WINNOW_MODE` (`real` | `demo`) selects behavior at startup, and the
app **refuses to boot** if the mode contradicts the database:

- `demo` mode with any row in `users` → refuse (a demo must never run
  against a real-user database).
- `real` mode with an empty `users` table → refuse (real mode needs the
  owner row every user-scoped query anchors on).

This is enforced in `winnow_api/config.py::enforce_mode_invariant`, called
from the FastAPI lifespan hook before the app accepts traffic.

### Dual-scoped data

Rows in `emails`, `triage_decisions`, `actions`, and `training_examples`
carry **exactly one** of `user_id` (real) or `session_id` (demo), enforced by
a `CHECK ((user_id IS NULL) <> (session_id IS NULL))` on every table and
locked in by `tests/test_dual_scoping_invariant.py`. Demo sessions are
cookie-scoped and garbage-collected after 24h; real data belongs to the
single owner.

## Tiered triage

```
incoming email
   │
   ▼
tier 1 — classifier (winnow_api/classifier)
   │   engineered features + MiniLM embeddings → logistic regression
   │   returns lane, confidence, signed per-feature explanation
   │
   ├─ confidence ≥ threshold ─────────────► final lane
   │
   └─ confidence < threshold ──► tier 2 — agent (winnow_api/agents)
                                    PydanticAI, structured Tier2AgentOutput
                                    (lane, confidence, reasoning, signals, draft)
                                        │
                                        ▼
                                    final lane (+ optional draft)
```

The router is `winnow_api/triage/orchestrator.py::orchestrate_triage` — one
small function, no retries or fallback chains (that ceremony belongs at the
API layer where it can be observed). The confidence threshold at or above
which tier-1 is trusted is `users.confidence_threshold` (default from the
eval sweep — see [evals.md#threshold-selection](evals.md)).

Tier-2 output is shape-compatible between the live path
(`agents/live_provider.py`, real mode) and the pre-recorded path
(`agents/fixture_provider.py`, demo mode), so downstream code never knows
which produced a response.

## The $0 demo: pre-recorded fixtures

The demo never calls a paid LLM. The fixture workflow:

1. `packages/seed-data/generate.py` runs once locally with a real key,
   calls the tier-2 agent for every synthetic email, and writes
   `packages/seed-data/llm-responses/{seed_id}.json`.
   (`generate_stub_fixtures.py` produces deterministic offline placeholders
   marked `provider: "stub"` so the demo has content before a real run.)
2. Fixtures are committed to the repo — shipped content, not secrets.
3. The demo backend's `FixtureLoader` indexes them by `seed_email_id` at
   startup.
4. In demo mode the orchestrator's tier-2 provider is `FixtureProvider`: it
   looks up the fixture, awaits a simulated 1000–1500 ms latency, and returns
   it tagged `tier_2_source: "prerecorded"`.
5. Novel emails with no fixture return a graceful "run locally" response.

### Fixture freshness

Each fixture records a `prompt_hash` (of the tier-2 system prompt) and a
`seed_email_hash`. `packages/seed-data/check_fixtures_fresh.py` recomputes
both and fails CI (`.github/workflows/check-fixtures-fresh.yml`) if any real
fixture drifted from the current prompt or seed corpus — forcing a
regenerate before a prompt change can merge. Stub fixtures are exempt.

**Regeneration:** after changing the agent prompt or schema, re-run
`packages/seed-data/generate.py` and commit the updated fixtures.

## Learning loop

`winnow_api/learning/`:

- Every UI action maps to a training label (`action_labels.py`): `lane_moved`
  → the target lane, `archived` → hidden, `starred`/`snoozed`/`draft_edited`
  → needs_you. `marked_read` and `draft_discarded` are dropped as weak signal.
- `training_writer.py` caches the feature vector + MiniLM embedding on each
  example so the nightly job doesn't re-embed history.
- `retrainer.py` combines the seed corpus with the owner's labeled examples,
  does a stratified split, trains, and evaluates both the new and current
  model on the same holdout. Guardrails: skip under 20 examples or <2 classes;
  reject a model that regresses more than 5% vs the active one; write a
  `classifier_metrics_history` row every attempt (deployed or not).
- `artifacts.py` rotates `base.joblib` → `base.previous.joblib` before
  writing a new model, so `winnow rollback` is a single atomic swap.
- `scheduler.py` runs the nightly job via APScheduler (real mode only), cron
  from `WINNOW_RETRAIN_CRON`.

## Gmail integration (real mode only)

`winnow_api/gmail/` raises `ImportError` if imported under `WINNOW_MODE=demo`
— a machine-enforced guarantee the demo image never carries Gmail code.

- **OAuth:** installed-app (desktop) flow via loopback — single user, no
  hosted callback. Only the refresh token is persisted, Fernet-encrypted with
  `WINNOW_ENCRYPTION_KEY`.
- **Sync:** `sync_full(days)` backfills; `sync_incremental()` walks
  `historyId`. On a 404 (history expired past Gmail's ~7-day window) it falls
  back to a bounded full sync automatically.
- **Push:** `POST /gmail/webhook` verifies the Google-signed Pub/Sub JWT and
  triggers incremental sync. `winnow gmail listen` is a polling fallback when
  Pub/Sub isn't set up.

## Deployment

- **Demo API** → Railway (Docker). Binds `$PORT`; migrations run via
  `python -m alembic` on start (multi-stage venv makes console-script
  shebangs unreliable). See `railway.json`, `apps/api/Dockerfile`.
- **Site** → Vercel, root `apps/site`. `NEXT_PUBLIC_API_ORIGIN` points the
  `/api/*` rewrite proxy at the Railway API, keeping the session cookie
  first-party.
- Full runbook in `DEPLOY.md`.
