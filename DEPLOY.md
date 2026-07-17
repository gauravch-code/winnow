# Deploying Winnow

The demo backend runs as a single container against a managed Postgres.
Two platforms are pre-configured; pick whichever free-tier situation is
least broken on the day you deploy.

**tl;dr as of July 2026:** Fly.io's free tier is gone (2024). Railway's
"free" plan gives $1/mo credit — unusable for a real workload. Realistic
options: Railway Hobby ($5/mo, includes $5 usage credit) or Fly
pay-as-you-go (~$3-8/mo for the tiny VM + tiny Postgres).

Both configs are in the repo — the same `apps/api/Dockerfile` builds
identically on either.

## Env vars the platform needs

Configure these as platform secrets (never commit them):

| Var                            | Required in    | Notes                                                          |
| ------------------------------ | -------------- | -------------------------------------------------------------- |
| `WINNOW_MODE`                  | always         | `demo` for public deploy, `real` only for your local self-host. |
| `WINNOW_DATABASE_URL`          | always         | e.g. `postgresql+psycopg://user:pass@host:5432/db`.            |
| `WINNOW_IP_HASH_SALT`          | demo mode      | Any random 32+ byte string. Rotating invalidates rate-limit IP hashes only. |
| `WINNOW_ENCRYPTION_KEY`        | real mode      | Fernet key: `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`. |
| `WINNOW_LLM_API_KEY`           | real mode      | Anthropic (or your chosen provider) key.                       |
| `NEXT_PUBLIC_API_ORIGIN`       | Vercel (site)  | Full URL of the deployed API, e.g. `https://winnow-api.up.railway.app`. Baked in at build time. |

## Railway (recommended)

```bash
# 1. One-time
railway login
railway init            # creates a project; pick "Empty Project"
railway link            # link this repo

# 2. Add Postgres
railway add --database postgresql

# 3. Set secrets (Railway auto-injects DATABASE_URL, rename to WINNOW_DATABASE_URL)
railway variables --set WINNOW_MODE=demo
railway variables --set "WINNOW_DATABASE_URL=\${{Postgres.DATABASE_URL}}"
railway variables --set "WINNOW_IP_HASH_SALT=$(openssl rand -hex 32)"

# 4. Deploy
railway up

# 5. Grab the URL
railway domain              # generates *.up.railway.app if none exists

# 6. Wire the site (see Vercel section)
```

Railway reads `railway.json` at the repo root and builds using
`apps/api/Dockerfile`. Migrations run automatically via the
`startCommand` (see `railway.json`).

## Fly.io (fallback)

```bash
# 1. One-time
fly auth login
fly apps create winnow-api          # matches app = "winnow-api" in fly.toml

# 2. Postgres
fly postgres create --name winnow-db --region iad --vm-size shared-cpu-1x --volume-size 1
fly postgres attach --app winnow-api winnow-db
#   this sets DATABASE_URL; convert it to WINNOW_DATABASE_URL:
fly secrets set --app winnow-api "WINNOW_DATABASE_URL=$(fly ssh console -a winnow-api -C 'printenv DATABASE_URL' | tr -d '\r')"
fly secrets set --app winnow-api "WINNOW_IP_HASH_SALT=$(openssl rand -hex 32)"

# 3. Deploy
fly deploy

# 4. Grab the URL
fly status                          # shows the hostname
```

Fly's `fly.toml` sets `min_machines_running = 0` so the VM sleeps when
idle. First request after a sleep pays a ~10s cold start, which is
survivable for a portfolio demo but not for production traffic.

## Site (Vercel)

```bash
cd apps/site
vercel                              # first run: pick a project name; use "winnow"
vercel env add NEXT_PUBLIC_API_ORIGIN production
#   paste the API URL from Railway/Fly, e.g. https://winnow-api.up.railway.app
vercel --prod                       # deploy
```

The site's `next.config.mjs` rewrites `/api/*` to whatever
`NEXT_PUBLIC_API_ORIGIN` is set to, so cookies stay SameSite=Lax on the
first-party origin.

## Post-deploy smoke test

```bash
API=https://winnow-api.up.railway.app     # or your Fly URL
SITE=https://winnow.vercel.app             # or your Vercel URL

curl -s "$API/health"
# expect: {"status":"ok","mode":"demo","fixtures_loaded":200}

# Open $SITE in a fresh incognito window, click "Try the demo",
# drag any card between lanes, click "ask LLM" — verify the tier-2
# panel shows a pre-recorded response with the "prerecorded" badge.
```

If `fixtures_loaded` reports 0, the Dockerfile didn't copy
`packages/seed-data/llm-responses/` correctly — rebuild.

## Updating fixtures on the deployed instance

Fixtures are baked into the image — regenerating them (`uv run python
packages/seed-data/generate.py`) and pushing a new image redeploys the
demo with the new responses. There is no runtime "reload fixtures"
endpoint by design.
