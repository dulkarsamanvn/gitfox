# GitFox

[![CI](https://github.com/dulkarsamanvn/gitfox/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/dulkarsamanvn/gitfox/actions/workflows/ci.yml)

GitFox is being built to review public GitHub pull requests and present structured
findings. The current foundation includes FastAPI, PostgreSQL, SQLAlchemy models,
Alembic migrations, and a React + TypeScript page for PR previews and service status.

The page uses these backend endpoints:

| Endpoint | Meaning |
|---|---|
| GET /health | FastAPI is running. |
| GET /ready | FastAPI can connect to PostgreSQL. |
| POST /api/v1/pull-requests/preview | Fetch PR details and select patches, with skipped-file reasons. |

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

In second terminal, start the frontend:

```powershell
cd D:\GitFox\frontend
npm run dev
```

Open <http://127.0.0.1:5173>, paste a public GitHub PR URL, and click **Preview PR**.
Inspect PR metadata, expandable patches, and skipped-file reasons. Service-status
checks and **Check again** remain available below. API documentation is at
<http://127.0.0.1:8001/docs>.

The browser calls FastAPI; database credentials stay on the backend. Backend
helpers now validate public GitHub PR links, fetch metadata and changed-file patches,
and select bounded text patches with skipped-file reasons. The React form now
connects this flow. AI analysis and saved-review history come in subsequent steps.

To inspect a public PR now, use **POST /api/v1/pull-requests/preview** in
<http://127.0.0.1:8001/docs>. It returns PR metadata, selected patches, skipped-file
reasons, and totals. This preview works without PostgreSQL or an OpenAI key and
does not create a review record. See the [backend API guide](backend/README.md#preview-a-pull-request-through-the-api)
for request examples and error responses.

Open **LLM configuration** below the preview to choose OpenAI, Anthropic Claude,
or Google Gemini, enter a model ID and API key, test access, and save the selection.
Keys stay on the local backend and are never returned by the settings API. The
connection test checks model metadata without generating text.

PR previews now run through a two-node LangGraph workflow: fetch PR files, then
select diffs. The API and frontend still return the same preview. See the
[workflow walkthrough](backend/README.md#first-langgraph-workflow) for nodes,
edges, state updates, and execution examples.

The backend also defines validated AI review-result schemas for summaries and
findings. AI review generation and saved-review reuse are planned next; see the
[result contract](backend/README.md#ai-review-result-schemas) and
[reuse policy](backend/README.md#planned-review-reuse).

## Checks

Backend checks and database integration tests are documented in
[backend/README.md](backend/README.md). Frontend type checking, production build,
and browser tests are documented in [frontend/README.md](frontend/README.md).

## Automatic checks on GitHub

[CI](https://github.com/dulkarsamanvn/gitfox/actions/workflows/ci.yml) runs on pushes,
pull requests, and manual requests from the Actions tab. The workflow is defined in
[.github/workflows/ci.yml](.github/workflows/ci.yml) and has two independent jobs:

- Backend: Python 3.13, dependency compatibility, Ruff lint/format checks, migrations
  from an empty PostgreSQL 17 database, schema consistency, and all backend tests.
- Frontend: Node.js 22, a clean dependency install, TypeScript and production build,
  and Playwright browser tests using Chromium and mocked API responses.

GitHub creates a temporary test database for each backend job using the test-only
credentials in the workflow. It does not need your local .env files or API keys.
The separate live-browser test is opt-in locally; PostgreSQL integration tests run
in the backend CI job. Open a job in the Actions tab to see which step passed or
failed. Green checks mean both jobs completed successfully.
