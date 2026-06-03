# chattersift

Keywords monitoring for Reddit. Hosted SaaS at **[chattersift.com](https://chattersift.com)**.

[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)

License: MIT

Chattersift is a Django 5.2 app that watches Reddit for keywords across user-defined monitors and delivers matches as alerts. It is HTMX/server-rendered first. The fastest way to use it is the hosted SaaS at [chattersift.com](https://chattersift.com); to self-host, follow the deployment instructions below. See [AGENTS.md](AGENTS.md) for repository conventions and [docs/deployment.md](docs/deployment.md) for the full deployment reference.

## Self-Hosted Deployment

Chattersift is designed to run on a single VPS with Docker Compose. Caddy terminates HTTPS, Postgres and Redis run as internal services on named volumes, and migrations run automatically before Django and Celery start.

### First deploy

```bash
uv sync
make deploy-init      # generates .env.production with internal secrets
```

Edit `.env.production` and set at minimum:

- `CHATTERSIFT_SITE_DOMAIN`
- `CADDY_SITE_ADDRESS`
- `CADDY_ACME_EMAIL`
- `DJANGO_ALLOWED_HOSTS`
- `DJANGO_CSRF_TRUSTED_ORIGINS`
- `DJANGO_DEFAULT_FROM_EMAIL` / `DJANGO_SERVER_EMAIL`
- `CHATTERSIFT_EMAIL_PROVIDER` and the matching provider credentials

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
