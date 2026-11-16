# GitFox backend

FastAPI foundation, tested with Python 3.13. Runtime dependency versions are
pinned in `requirements.txt`; development tools are in `requirements-dev.txt`.

## Local setup (PowerShell)

From `D:\GitFox\backend`:

```powershell
python -m venv env
.\env\Scripts\python.exe -m pip install -r requirements-dev.txt
```

If `env` already exists, use it and skip the first command. For runtime-only
installation, use `requirements.txt` instead.

For a fresh setup, create the local environment file once:

```powershell
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
```

Edit `.env` with your local values. It is ignored by Git. Environment variables
override values in `.env`, which is always loaded from the backend directory.
Restart the server after changing settings.

Replace `replace_me` in both `POSTGRES_PASSWORD` and `DATABASE_URL` with the same
local password. Use a URL-safe password (letters, numbers, `-`, and `_`) or URL-encode
special characters in the URL. Keep existing credentials when restarting the database.
`OPENAI_API_KEY`, `OPENAI_MODEL`, and `GITHUB_TOKEN` may remain blank.

The API can start without `DATABASE_URL`; in that case `/ready` returns `503`.
PostgreSQL URLs use `postgresql+psycopg://` (plain `postgresql://` and `postgres://`
also select psycopg). Other drivers and multiple database hosts are rejected.

`CORS_ORIGINS` is a comma-separated list of HTTP(S) origins, such as
`http://localhost:5173,http://127.0.0.1:5173`. Wildcards, credentials, paths,
queries, and fragments are rejected.

## Where the database settings come from

In Django, DATABASES in settings.py describes how the application connects. Here,
app/core/config.py loads DATABASE_URL from backend/.env, and app/db/database.py
uses it to establish SQLAlchemy connections.

- POSTGRES_USER and POSTGRES_DB are set to gitfox in compose.yaml.
- POSTGRES_PASSWORD comes from backend/.env. During the initial local setup,
  a random password was generated and saved there.
- Docker Compose uses that password to initialize the database account when
  creating a new data volume.
- DATABASE_URL gives FastAPI the matching connection details:

```text
postgresql+psycopg://gitfox:<password>@127.0.0.1:5433/gitfox
```

The parts are driver, username, password, host, port, and database name. Real
credentials stay in the ignored backend/.env; .env.example has placeholders.
Editing POSTGRES_PASSWORD after the database has been initialized does not change
the existing PostgreSQL account's password.

## Start PostgreSQL

Start Docker Desktop, then run from the repository root:

```powershell
cd D:\GitFox
docker compose --env-file backend/.env up -d --wait db
docker compose --env-file backend/.env ps
```

`compose.yaml` starts PostgreSQL 17 with database/user `gitfox` and exposes it at
`127.0.0.1:5433`. The existing local PostgreSQL service on `5432` is separate.
Compose reads only the database password into the container, not the API keys.
Database data is stored in the persistent `gitfox_postgres_data` Docker volume.

To stop the project database while keeping its data:

```powershell
docker compose --env-file backend/.env stop db
```

The application uses `app/db/database.py` to manage a shared SQLAlchemy connection
pool through psycopg. Connections are opened when needed and closed on application
shutdown. Connection, pool, and SQL statement timeouts bound readiness checks.

## Create or update the tables

With PostgreSQL running and DATABASE_URL configured:

```powershell
cd D:\GitFox\backend
.\env\Scripts\python.exe -m alembic upgrade head
.\env\Scripts\python.exe -m alembic current
.\env\Scripts\python.exe -m alembic check
```

The initial migration creates:

| Table | Purpose |
|---|---|
| reviews | PR identity, base/head SHA, status, coverage counts, summary, and timestamps |
| findings | Evidence, severity, category, confidence, suggestion, and optional line location |
| review_files | Reviewed/skipped file metadata and skip reasons |

PostgreSQL generates UUID IDs and creation timestamps. Check constraints enforce
allowed status/finding values, positive PR/line numbers, and valid coverage counts.
Foreign keys link findings and files to their review, with cascade deletion.
File paths are unique within each review. No raw repository files are retained.

The files involved are:

- app/db/base.py: shared SQLAlchemy model metadata.
- app/models/: Python table definitions, similar to Django's models.py.
- alembic/env.py: migration configuration using the existing DATABASE_URL.
- alembic/versions/: versioned schema changes.
- alembic.ini: migration paths and logging, with no database credentials.

Alembic records the applied revision in its own alembic_version table. Run upgrade
head after pulling new migrations; application startup does not create tables.

When changing models later, generate and review a migration before applying it:

```powershell
.\env\Scripts\python.exe -m alembic revision --autogenerate -m "describe the schema change"
.\env\Scripts\python.exe -m ruff check --fix alembic/versions
.\env\Scripts\python.exe -m ruff format alembic/versions
.\env\Scripts\python.exe -m alembic upgrade head
```

This corresponds to Django's makemigrations followed by migrate. Migration rollback
tests run in disposable schemas so they do not drop application tables.

## Run

```powershell
cd D:\GitFox\backend
.\env\Scripts\python.exe -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8001
```

Use port `8001` because the local Laravel server uses `8000`.

- Home: <http://127.0.0.1:8001/>
- Liveness: <http://127.0.0.1:8001/health> returns `{"status":"ok"}`.
- Database readiness: <http://127.0.0.1:8001/ready> returns
  `{"status":"ok","database":"ok"}` with HTTP `200` after an authenticated `SELECT 1`.
- API documentation: <http://127.0.0.1:8001/docs>

If the database is unavailable or not configured, `/ready` returns HTTP `503` with
`{"status":"not_ready","database":"unavailable"}`. Driver errors and credentials
are not included in that response. `/health` still reports application liveness.

## Verify

```powershell
.\env\Scripts\python.exe -m pip check
.\env\Scripts\python.exe -m pytest
.\env\Scripts\python.exe -m ruff check .
.\env\Scripts\python.exe -m ruff format --check .
```

Unit tests do not require a running database or API keys. Integration tests are
skipped unless `TEST_DATABASE_URL` is set. To run them using the current local settings:

```powershell
.\env\Scripts\python.exe -c "import os, pytest; from app.core.config import get_settings; os.environ['TEST_DATABASE_URL'] = str(get_settings().database_url); raise SystemExit(pytest.main(['-m', 'integration', '-q']))"
```

This checks the real PostgreSQL connection without printing the database URL.

Settings and CORS follow the official
[FastAPI settings](https://fastapi.tiangolo.com/advanced/settings/) and
[CORS](https://fastapi.tiangolo.com/tutorial/cors/) documentation.
Database lifecycle follows [FastAPI lifespan](https://fastapi.tiangolo.com/advanced/events/)
and [SQLAlchemy engines](https://docs.sqlalchemy.org/en/21/core/engines.html).
