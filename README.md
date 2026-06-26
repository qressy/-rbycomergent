# /r by Comergent — Reddit monitoring for go-to-market teams

**/r by Comergent** is a self-hostable Reddit monitoring app: define keyword and semantic monitors across subreddits, get matching posts and comments back as a triageable lead inbox, and reach out before someone else does. Django + HTMX, server-rendered, Celery for background fetching.

## Features

- **Keyword monitors** — exact phrases, word-boundary matches, or hybrid keyword + semantic descriptions, per subreddit.
- **Lead inbox** — every match lands in a list/detail Leads view; mark contacted, drill in from any monitor chip.
- **Run log** — every fetch (manual, scheduled, or auto) recorded with status, match count, and duration in UTC.
- **Multi-subreddit** — one configuration covers as many communities as you track.
- **Email alerts** — Postmark / SES / Mailgun via Anymail; per-subreddit notification cadence.
- **Background processing** — Celery workers with retries; periodic fetches via Celery beat.
- **Open source** — MIT-licensed. Read it, fork it, run it on your own infrastructure.

## Self-Hosted Deployment

The app is designed to run on a single VPS with Docker Compose. Caddy terminates HTTPS, Postgres and Redis run as internal services on named volumes, and migrations run automatically before Django and Celery start.

### Infrastructure requirements

You only need a Linux host with Docker — every runtime (Python, Node, Postgres, Redis) runs in containers.

**Compute sizing**

| Tier | Use case | vCPU | RAM | Disk |
|---|---|---|---|---|
| Tiny (dev / staging) | Single user, 1–2 subreddits | 1 | 2 GB | 20 GB SSD |
| **Small (recommended start)** | Up to ~20 monitors, low traffic | **2** | **4 GB** | **40 GB SSD** |
| Medium | Dozens of monitors, multi-user | 4 | 8 GB | 80 GB SSD |

Approximate RAM allocation on the small tier: Postgres ~500 MB · Redis ~200 MB · Django/gunicorn ~600 MB · Celery worker ~400 MB · Celery beat ~150 MB · OS + Docker ~500 MB · headroom for fetch bursts.

Disk grows with matched posts (`Match`) and fetch history (`FetchRun`). Expect a few GB per year of Postgres data + WAL at moderate volume.

**Software on the host**

- **Docker Engine** with Compose v2 (`docker compose`, not legacy `docker-compose`)
- **GNU Make**
- **git**
- **Python 3** (stdlib only — used by `scripts/bootstrap-deploy-env`)

**Networking**

- Public IPv4 + DNS A record on a domain you control
- Inbound `80` and `443` open (Caddy obtains TLS via Let's Encrypt)
- Outbound to `reddit.com` / `oauth.reddit.com` and your SMTP provider

**External services**

- **Reddit API credentials** — client ID, secret, and a descriptive user-agent string
- **Transactional email provider** — Postmark / Mailgun / SendGrid / SES (Anymail-supported)
- **LLM credentials (optional)** — only required for semantic monitors and the "Generate DM" assist
- **Domain** — required for HTTPS

**Recommended providers (small tier, monthly ballpark)**

- Hetzner CX22 — 2 vCPU / 4 GB / 40 GB · ~€4
- DigitalOcean / Linode 4 GB droplet — ~$24
- AWS Lightsail 4 GB — ~$24

### First deploy

```bash
make deploy-init      # generates .env.production with internal secrets
```

Edit `.env.production` and set at minimum:

- `CHATTERSIFT_SITE_DOMAIN`
- `CADDY_SITE_ADDRESS`
- `CADDY_ACME_EMAIL`
- `DJANGO_ALLOWED_HOSTS`
- `DJANGO_CSRF_TRUSTED_ORIGINS`
- `DJANGO_DEFAULT_FROM_EMAIL` / `DJANGO_SERVER_EMAIL`
- `CHATTERSIFT_EMAIL_PROVIDER` plus the matching provider credentials
- Reddit API credentials (`REDDIT_CLIENT_ID`, `REDDIT_CLIENT_SECRET`, `REDDIT_USER_AGENT`)

Then bring up the production stack:

```bash
make deploy           # alias for `make up production` — build + start
make deploy-logs      # follow production logs
```

The production stack includes Postgres, Redis, Django (Gunicorn + Uvicorn workers), Celery worker, Celery beat, and Caddy. Health check: `/healthz/`.

### Upgrades

```bash
git pull
make deploy
```

The `migrate` service runs `migrate --noinput` and syncs `django_site` from `CHATTERSIFT_SITE_DOMAIN` before Django and Celery start.

### Production management

```bash
make deploy-manage shell                 # Django shell in production container
make deploy-manage createsuperuser
make ps production                       # list running containers
make logs production [service]           # follow logs for a single service
make down production                     # stop the stack
```

### Backups

```bash
make backup                              # snapshot the production database
make backups                             # list snapshots
make restore <backup-file>               # restore from a snapshot
```

Production-grade backups should be shipped off-box. The compose file ships an `awscli` helper container for S3 sync — wire `make backup` into cron and follow it with `aws s3 cp`.

See [docs/deployment.md](docs/deployment.md) for the full reference, including email provider configuration, LLM credentials, and backup retention.

## Local Development

Install Python dependencies and run the local stack:

```bash
uv sync
make shell            # serve Django on http://127.0.0.1:8000 (runs migrations + collectstatic)
```

Or run everything in Docker:

```bash
make up               # start the local Docker stack
make manage migrate   # run management commands in the Docker django service
```

`make help` lists every target. All Make targets accept an optional `local` / `production` mode argument (default: `local`).

### Tailwind CSS

```bash
npm install
npm run build:css     # one-off build
npm run watch:css     # rebuild on template / style changes
```

Source: `chattersift/static/src/project.css`. Compiled output: `chattersift/static/css/project.css` (already linked from the base template).

### Tests, lint, types

```bash
make test             # uv run pytest
make lint             # uv run ruff check .
make type             # uv run ty check
make template-lint    # djlint
make migration-check  # detect missing migrations
```

Tests use `pytest` + `pytest-django` and read `DATABASE_URL`; use Postgres locally.

### Users

- Create a normal account through the Sign Up form; email verification shows up in the console (or Mailpit at `http://127.0.0.1:8025` when running Docker).
- Create a superuser with `uv run python manage.py createsuperuser` (or `make manage createsuperuser` in Docker).

### Celery

```bash
cd chattersift
uv run celery -A config.celery_app worker -l info
uv run celery -A config.celery_app beat        # periodic tasks
```

Run `celery` from the directory containing `manage.py` so Celery's import magic resolves correctly. The Docker stacks run a worker and beat container automatically.
