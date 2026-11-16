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
Application tables and Alembic migrations are the next implementation step.

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

Unit tests do not require a running database or API keys. The integration test is
skipped unless `TEST_DATABASE_URL` is set. To run it using the current local settings:

```powershell
.\env\Scripts\python.exe -c "import os, pytest; from app.core.config import get_settings; os.environ['TEST_DATABASE_URL'] = str(get_settings().database_url); raise SystemExit(pytest.main(['-m', 'integration', '-q']))"
```

This checks the real PostgreSQL connection without printing the database URL.

Settings and CORS follow the official
[FastAPI settings](https://fastapi.tiangolo.com/advanced/settings/) and
[CORS](https://fastapi.tiangolo.com/tutorial/cors/) documentation.
Database lifecycle follows [FastAPI lifespan](https://fastapi.tiangolo.com/advanced/events/)
and [SQLAlchemy engines](https://docs.sqlalchemy.org/en/21/core/engines.html).
