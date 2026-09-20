# Winnow

**Local-first AI inbox triage.** A small classifier on your own machine
handles 80%+ of email routing in milliseconds for free. An LLM sees only
the cases the classifier isn't sure about — and only if you opt in with
your own key. Your inbox never leaves your machine unless you say so.

**[Try the hosted interactive demo](https://gauravch-code.github.io/winnow/)** — synthetic email, deterministic decisions, prerecorded Tier 2, no signup or API key.

**Run the real classifier locally in 5 minutes** — see the Quickstart below. Synthetic data, real inference, no signup needed.

[![status](https://img.shields.io/badge/status-v1.1-brightgreen)](https://github.com/gauravch-code/winnow)
[![license](https://img.shields.io/badge/license-MIT-blue)](LICENSE)
[![python](https://img.shields.io/badge/python-3.12%2B-blue)](apps/api/pyproject.toml)
[![tests](https://img.shields.io/badge/tests-166%20passing-brightgreen)](apps/api/tests)

<!-- Maintainer: drop a 30s screen capture at docs/img/demo.gif and this renders. -->
<!-- ![Winnow demo](docs/img/demo.gif) -->

---

## Why this exists

Existing AI inbox tools are one of two things:

1. **Hosted SaaS** that ingests all your email onto someone else's servers, or
2. **Thin LLM wrappers** that fire a paid API call at every single message.

Winnow is neither. It's a **tiered** system: a cheap, private, local model
does the bulk of the work, and the expensive model is a scalpel, not a
firehose. That means your mail stays local, the running cost is ~$0, and the
system gets *better at handling things locally* the more you use it.

## How it works

```text
Incoming email
      |
      v
Tier 1: local classifier (~5 ms, CPU, $0)
      |
      +-- high confidence --> Needs You / Informational / Hidden
      |
      +-- low confidence ---> Tier 2: optional LLM
                                  |
                                  v
                         Structured triage + draft
                                  |
                                  v
User action (move / archive / star / edit)
      |
      v
Training example --> nightly retrain --> Tier 1
```

- **Tier 1 (local, free, private).** A scikit-learn logistic-regression
  classifier over engineered features (sender domain, thread depth, urgency
  words, time of day, …) plus `all-MiniLM-L6-v2` sentence embeddings. Runs on
  CPU in milliseconds. Handles the large majority of triage decisions and
  returns a signed per-feature explanation for every one.
- **Tier 2 (LLM, opt-in).** A PydanticAI agent with a structured output
  schema, invoked only when tier-1 confidence is below threshold, or when you
  explicitly ask for a drafted reply. Bring your own key (Anthropic default;
  OpenAI and Ollama behind a provider abstraction).
- **Learning loop.** Every action you take — moving an email between lanes,
  archiving, starring, editing a draft — becomes a labeled training example.
  A nightly job retrains tier-1 on your own history, gated by guardrails
  (won't retrain on too little data, won't deploy a model that regresses,
  keeps the previous model for one-command rollback).
- **Drafts only, never sends.** Tier-2 can draft a reply and surface the
  assumptions it made, but Winnow never sends mail on your behalf. Deliberate
  product call — you stay in the loop for anything irreversible.

## Evals

Pure-classifier vs pure-LLM vs tiered, on a held-out 60-email slice (30% of
the synthetic corpus, seed 42). Full breakdown + threshold sweep in
[`docs/evals.md`](docs/evals.md) and on the
[`/evals` page](https://winnow-eight.vercel.app/evals). Reproduce with `winnow eval`.

| Strategy | Accuracy | Mean latency | Cost / 1000 | Escalated |
|---|---|---|---|---|
| Pure classifier (tier-1) | 86.7% | 3.7 ms | $0.00 | 0% |
| Pure LLM (tier-2) | 100%\* | 1.20 s | $5.30 | 100% |
| **Tiered (Winnow)** | **88.3%** | **104 ms** | **$0.41** | **8.3%** |

The result: tiered beats the standalone classifier (88.3% vs 86.7%) by
escalating only the ~8% of emails tier-1 is unsure about, which buys most of
the accuracy gap to the LLM at a fraction of its cost and latency. Raise the
confidence threshold and accuracy climbs toward the LLM ceiling (~98%) as cost
rises with it; that dial is the whole point of a tiered system.

\* _Pure LLM shows 100% because the demo's tier-2 fixtures are rule-based
stubs whose labels mirror ground truth, so treat it as a ceiling rather than a
measured LLM score. The classifier accuracy, escalation rate, latency, and
cost are all real, measured on held-out data. Run
`packages/seed-data/generate.py` with a real key to publish genuine LLM
accuracy._

## How the demo stays at $0

The public demo **never calls a paid LLM API**. Not once.

- **Tier 1 runs for real** — it's CPU-only and free, so every visitor gets
  genuine live classifier decisions with real feature-importance
  explanations, retraining on their own drag-and-drop edits within their
  session.
- **Tier 2 is pre-recorded.** Every synthetic email's tier-2 response is
  generated once offline (`packages/seed-data/generate.py`), committed as a
  JSON fixture, and served with a realistic simulated latency. The API badges
  each response `tier_2_source: "prerecorded"` so the UI is honest about it.
- **Novel emails** with no fixture get a graceful "run Winnow locally with
  your own key to see the LLM handle this" placeholder.

Session state is isolated per visitor by cookie and garbage-collected after
24h. This is a strength, not a limitation — it's why anyone can try it
without costing the maintainer money or risking abuse.

## Quickstart (local demo)

Prereqs: [uv](https://docs.astral.sh/uv/), Node 18+, Docker.

```bash
# 1. Postgres
docker compose up -d postgres

# 2. Python workspace (installs the API, the winnow CLI, uvicorn, alembic, ML deps)
uv sync --all-packages

# 3. Dashboard deps
(cd apps/web && npm install)

# 4. Point at the DB in demo mode (bash; PowerShell: $env:NAME='value')
export WINNOW_MODE=demo
export WINNOW_DATABASE_URL=postgresql+psycopg://winnow:winnow@localhost:5432/winnow
export WINNOW_IP_HASH_SALT=local-dev-not-a-secret

# 5. Migrate + generate the 200 synthetic emails + train the tier-1 model
(cd apps/api && uv run python -m alembic upgrade head)
uv run python packages/seed-data/generate_emails.py
uv run python -m winnow_api.classifier.train

# 6. Boot API + dashboard (two shells)
uv run python -m uvicorn winnow_api.main:app --app-dir apps/api --port 8000
(cd apps/web && npm run dev)

# 7. open http://localhost:3000
```

Config is entirely environment variables — see [`.env.example`](.env.example).
The API **refuses to boot** if `WINNOW_MODE` contradicts the database:
`demo` mode with real users, or `real` mode with no owner row. Fail loud,
fail early.

## Running it on your own Gmail

Real mode is single-user (you), self-hosted on your machine, and gated behind
`WINNOW_MODE=real` — the demo backend can't even import the Gmail modules.
Three parts: connect Google, configure secrets, run.

### 1. One-time Google Cloud setup (the only manual part)

Winnow talks to Gmail through your own OAuth client, so nothing is shared:

1. [console.cloud.google.com](https://console.cloud.google.com) → create a project.
2. **APIs & Services → Library** → enable **Gmail API**.
3. **OAuth consent screen** → External → add your own address as a **Test user**.
4. **Credentials → Create Credentials → OAuth client ID → Desktop app** →
   download the JSON. Save it as `./credentials.json` (gitignored).

### 2. Secrets — put them in `.env` (gitignored), never `.env.example`

```bash
cp .env.example .env
```
Then edit `.env`:
```
WINNOW_MODE=real
WINNOW_ENCRYPTION_KEY=        # generate: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
WINNOW_LLM_API_KEY=sk-...     # optional — enables the tier-2 "ask LLM" button
WINNOW_LLM_PROVIDER=openai    # or anthropic
WINNOW_LLM_MODEL=gpt-4o-mini
```

### 3. Run

Connect Gmail once on the host (the OAuth loopback needs your browser; the
encrypted refresh token lands in Postgres), then start the stack:

```bash
docker compose -f docker-compose.full.yml up -d postgres     # DB first, for bootstrap
uv sync --all-packages                                        # host tools for the one-time connect
set -a && source .env && set +a                               # load .env into the shell

winnow bootstrap --email you@gmail.com                        # create the owner row
winnow gmail authorize --credentials-file ./credentials.json  # opens your browser
winnow gmail sync --full                                      # backfill + classify last 30 days

docker compose -f docker-compose.full.yml up --build          # Postgres + API + dashboard
# open http://localhost:3000 — your inbox, triaged
```

In the dashboard: drag to correct a lane (every move trains tier-1), click
**archive**/**star** (also training signal), or **ask LLM** to escalate an
email to the tier-2 agent with your key. `winnow retrain` (or the nightly job)
folds your corrections into a new model, with a regression guardrail and
one-command `winnow rollback`.

**Cost:** tier-1 runs locally for free; the paid LLM fires **only** when you
click "ask LLM" (never per-sync), so a normal day costs cents or nothing.

The refresh token is encrypted at rest with `cryptography.fernet`. Sync is
incremental via `historyId` with a polling fallback and optional Pub/Sub push.
Details in [`docs/architecture.md`](docs/architecture.md).

## Repository layout

```
apps/
  api/        FastAPI backend — real app + demo share one codebase, split by WINNOW_MODE
    winnow_api/
      classifier/   tier-1: features, MiniLM embeddings, train, inference + explainability
      agents/       tier-2: PydanticAI schema, prompt, provider factory, live + fixture providers
      triage/       confidence-threshold orchestrator (tier-1 → maybe tier-2)
      learning/     action→label mapping, nightly retrainer, guardrails, artifact rotation
      gmail/        real-mode only: OAuth, API client, historyId sync, Pub/Sub webhook
      realapp/      real-mode only: owner-scoped dashboard API (list, lane, archive, star, escalate)
      eval/         pure-classifier vs pure-LLM vs tiered harness
      demo/         session middleware, seeder, fixture loader, demo routes
      db/           SQLAlchemy models + Alembic migrations
  web/          Next.js 15 dashboard (App Router, Tailwind, dnd-kit)
  site/         Marketing landing + embedded /demo + /evals
packages/
  seed-data/    200 synthetic emails, tier-2 fixtures, generators, freshness check
docs/           architecture.md, evals.md
```

## Tech stack

**Backend** Python 3.12 · FastAPI · Pydantic v2 · PydanticAI · SQLAlchemy 2 +
Alembic · Postgres 16 · scikit-learn · sentence-transformers · APScheduler ·
structlog
**Frontend** Next.js 15 · TypeScript (strict) · Tailwind · shadcn/ui · dnd-kit
**Infra** Docker Compose · Railway (demo API) · Vercel (site) · GitHub Actions
**Tooling** uv · ruff · mypy · pytest (153 tests) · Vitest

## Explicitly out of scope

Deliberate non-goals, so the project stays focused:

- Multi-account support, non-Gmail providers, team/shared inboxes, mobile app
- **Auto-sending replies** — drafts only; you send
- Calendar integration
- Live LLM calls in the public demo — pre-recorded fixtures instead
- Hosting Winnow-as-a-service for other people's real inboxes

## License

MIT — see [LICENSE](LICENSE).
