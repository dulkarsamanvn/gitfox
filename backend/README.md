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

## GitHub PR URL parser

`app/integrations/github_url.py` validates a pasted PR URL and extracts the owner,
repository, and positive PR number. It returns an immutable `PullRequestRef` with
a normalized `pr_url`. This step validates syntax; the GitHub client below checks
repository visibility when fetching metadata.

```python
from app.integrations.github_url import parse_pull_request_url

reference = parse_pull_request_url("https://github.com/octocat/Hello-World/pull/123")
# reference.owner == "octocat"
# reference.repository == "Hello-World"
# reference.pr_number == 123
```

Only HTTPS links on github.com with the path /OWNER/REPO/pull/NUMBER are accepted.
One trailing slash is removed; scheme/hostname casing is normalized and identifier
spelling is preserved. PR numbers use canonical decimal notation and fit the
database's positive INTEGER range. Credentials, ports, query/fragment delimiters,
encoded path segments, whitespace/control characters, and other paths are rejected.
Invalid input raises `InvalidPullRequestURL` with the stable code `invalid_pr_url`;
its message does not repeat the submitted URL.

Run the focused tests from the backend directory:

```powershell
.\env\Scripts\python.exe -m pytest tests/test_github_url.py -q
```

## GitHub PR metadata client

`app/integrations/github.py` uses the parser to build requests to the fixed
`https://api.github.com` host. It returns a validated `PullRequestMetadata` with
the PR title, author (or `None` for a deleted user), open/closed state, merged
flag, base/head commit SHAs, and changed-file count. It rejects private repositories
and checks that the returned PR matches the requested repository and number.

Use it from async Python code:

```python
from app.integrations.github import GitHubClient


async def read_pr(pr_url: str):
    async with GitHubClient() as github:
        return await github.get_pull_request(pr_url)
```

`GITHUB_TOKEN` in the backend environment is optional for public repositories.
If provided, it is sent only to GitHub; redirects are rejected. No token is
accepted from the frontend. The client pins GitHub API version `2026-03-10`.

Each attempt has a 15-second deadline, 5-second connection timeout, 10-second
read/write/pool timeouts, and a 1 MiB response limit. Network failures, timeouts,
and server errors are retried once after 0.5 seconds. Rate limits, access errors,
and missing PRs are returned immediately without retrying. `GitHubClientError`
has a stable `code` and safe message; raw response bodies and credentials are
not included. URL validation still raises `InvalidPullRequestURL`.

These are backend integration helpers. Connecting them to an HTTP endpoint and
the frontend comes in a later part.

```powershell
.\env\Scripts\python.exe -m pytest tests/test_github.py -q
```

## GitHub changed files and patches

`GitHubClient.get_pull_request_files(pr_url)` returns a `PullRequestFiles` with
`metadata` and an immutable `files` tuple. Each `PullRequestFile` (defined in
`app/integrations/github_files.py`) includes:

- `filename`, `status`, and `previous_filename` for renames.
- `additions`, `deletions`, and total `changes`.
- `patch`: the untrusted diff text, or `None` when GitHub omits it. Empty patches
  are preserved too. A missing patch does not prove a file is binary or unchanged.

```python
from app.integrations.github import GitHubClient


async def read_changed_files(pr_url: str):
    async with GitHubClient() as github:
        result = await github.get_pull_request_files(pr_url)
    return result.metadata, result.files
```

The reader checks public visibility first, then requests numbered pages of up to
100 files. Page requests are built locally using the metadata's changed-file count;
URLs in `Link`, `raw_url`, and `contents_url` are never fetched. Duplicate paths,
unsafe relative paths, and invalid response fields are rejected. Normal relative
paths with spaces and Unicode are preserved; absolute paths, Windows drive paths,
backslashes, traversal segments, and control characters are unsupported.

Fetching is limited to 300 files, 1 MiB per response, and a 60-second deadline for
the whole operation, including metadata checks and retries. Larger PRs raise
`github_too_many_files` before any file page is fetched. A count mismatch raises
`github_incomplete_files`; no partial list is returned after any page fails.

After fetching files, the reader checks the base SHA, head SHA, and changed-file
count again. Updates raise `github_pr_changed`, allowing a later caller to start
over. This detects updates during retrieval; GitHub's paginated files endpoint
does not provide an atomic commit snapshot.

Patches stay in memory and are excluded from model `repr` output. This helper
does not save source code or mark any file as reviewed. Pass its file list to
the selector below to prepare bounded input for a later AI review.

```powershell
.\env\Scripts\python.exe -m pytest tests/test_github.py tests/test_github_files.py -q
```

All client tests use HTTPX MockTransport; no real token or network is needed.
The client follows GitHub's [PR endpoint](https://docs.github.com/en/rest/pulls/pulls#get-a-pull-request)
and [files endpoint](https://docs.github.com/en/rest/pulls/pulls#list-pull-requests-files),
with [rate-limit handling](https://docs.github.com/en/rest/using-the-rest-api/rate-limits-for-the-rest-api).

## Select patches for review

`app/services/diff_selection.py` contains `select_diffs(files)`. This is application
logic: it processes the validated file objects returned by the GitHub client
without making network requests or calling an AI model.

```python
from app.integrations.github import GitHubClient
from app.services.diff_selection import select_diffs


async def prepare_review(pr_url: str):
    async with GitHubClient() as github:
        fetched = await github.get_pull_request_files(pr_url)
    return select_diffs(fetched.files)
```

The `DiffSelection` result contains:

- `selected`: immutable `SelectedDiff` objects with their original whole patches.
- `skipped`: immutable file metadata and a stable `reason`, without skipped patches.
- `files_seen`, `files_selected`, `files_skipped`, and `patch_chars`: computed totals
  included when serializing the result. Every input file is counted once.

Selection does not mark a file as reviewed. AI analysis and persistence come later.
For example, one Python patch plus a PNG without a text patch produces one selected
file and one skipped file, with `binary_file` as the PNG's reason.

Limits come from `app/core/config.py` and can be overridden in the backend environment:

| Setting | Default | Allowed range |
|---|---:|---:|
| MAX_REVIEW_FILES | 10 | 1–300 |
| MAX_PATCH_CHARS | 20000 | 1–200000 |
| MAX_FILE_PATCH_CHARS | 10000 | 1–100000 |

Sizes count Python characters in the diff text, including headers and line endings;
they are not model token limits or full-file sizes. The per-file and total limits
apply independently. Keep whole patches: an oversized patch is skipped, and later
smaller patches can still fill the remaining budget. Eligible files retain input
order, and skipped files do not consume the file or character budgets.

The filename policy supports common source, configuration, markup, and documentation
extensions, plus filenames such as Dockerfile and Makefile. Its explicit allowlist
is `_TEXT_EXTENSIONS` / `_TEXT_FILENAMES` in the selector module. Generated-file
detection uses known directory names and filename patterns, such as `dist/`,
`node_modules/`, `*.min.js`, and `*.generated.ts`; it does not inspect full file contents.

| Skip reason | Meaning |
|---|---|
| generated_file | Known generated/dependency directory or filename pattern |
| lock_file | Dependency lockfile name or `.lock` suffix |
| binary_file | Known binary file extension |
| unsupported_file_type | Filename/extension is outside the text allowlist |
| missing_patch | Patch is absent, empty, or whitespace only |
| patch_too_large | Whole patch exceeds MAX_FILE_PATCH_CHARS |
| invalid_patch | Patch has malformed unified-diff structure |
| incomplete_patch | Hunk lengths or added/deleted totals do not match; patch may be truncated |
| no_text_changes | Valid hunks contain only context lines |
| file_limit_exceeded | Enough eligible files have already been selected |
| patch_budget_exceeded | Whole patch does not fit the remaining total character budget |

Path rules run first, then patch availability, per-file size, and integrity checks,
followed by the file-count and total-character budgets. One primary reason is recorded
per skipped file. Hunk checks support additions, deletions, multiple hunks, CRLF, and
Git's no-final-newline marker, while preserving the original patch string. They detect
omitted lines/hunks through counts; finding-to-line mapping is a separate next step.

```powershell
.\env\Scripts\python.exe -m pytest tests/test_diff_selection.py tests/test_config.py -q
```

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
