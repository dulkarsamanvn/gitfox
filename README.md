# GitFox

GitFox is being built to review public GitHub pull requests and present structured
findings. The current foundation includes FastAPI, PostgreSQL, SQLAlchemy models,
Alembic migrations, and a React + TypeScript status page.

The status page checks the existing backend endpoints:

| Endpoint | Meaning |
|---|---|
| GET /health | FastAPI is running. |
| GET /ready | FastAPI can connect to PostgreSQL. |

## One-time setup

- Follow the [backend setup guide](backend/README.md) to create the Python
  environment, install dependencies, prepare backend/.env, and apply migrations.
- Follow the [frontend setup guide](frontend/README.md) to install Node dependencies.
- Keep real credentials in the ignored backend/.env. Committed environment examples
  contain placeholders only.

## Start locally

Start Docker Desktop. In a PowerShell terminal, start the database and API:

```powershell
cd D:\GitFox
docker compose --env-file backend/.env up -d --wait db
cd backend
.\env\Scripts\python.exe -m alembic upgrade head
.\env\Scripts\python.exe -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8001
```

In a second terminal, start the frontend:

```powershell
cd D:\GitFox\frontend
npm run dev
```

Open <http://127.0.0.1:5173>. The page displays real service status and provides a
Check again button. API documentation is at <http://127.0.0.1:8001/docs>.

The browser calls FastAPI; database credentials stay on the backend.
GitHub retrieval and AI review features are planned for subsequent steps.

## Checks

Backend checks and database integration tests are documented in
[backend/README.md](backend/README.md). Frontend type checking, production build,
and browser tests are documented in [frontend/README.md](frontend/README.md).
