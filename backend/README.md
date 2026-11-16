# GitFox backend

FastAPI foundation, tested with Python 3.13. Runtime dependency versions are
pinned in requirements.txt; development tools are in requirements-dev.txt.

## Local setup (PowerShell)

From D:\GitFox\backend:

    python -m venv env
    .\env\Scripts\python.exe -m pip install -r requirements-dev.txt

If env already exists, skip creating it. Runtime-only installations can use
requirements.txt instead.

Configuration overrides are optional. Copy .env.example to .env once on a fresh
setup and edit local values. The local .env is ignored by Git. Environment
variables override the backend .env file; restart the server after changing them.
Database and API credentials are optional during this foundation step.

CORS_ORIGINS accepts comma-separated HTTP(S) browser origins. Wildcards,
credentials, paths, queries, and fragments are rejected.

## Run

    .\env\Scripts\python.exe -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8001

- Home: <http://127.0.0.1:8001/>
- Liveness: <http://127.0.0.1:8001/health>
- API documentation: <http://127.0.0.1:8001/docs>

## Verify

    .\env\Scripts\python.exe -m pytest
    .\env\Scripts\python.exe -m ruff check .
    .\env\Scripts\python.exe -m ruff format --check .
    .\env\Scripts\python.exe -m pip check

Tests cover configuration, CORS, credential redaction, and application liveness.
