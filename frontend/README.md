# GitFox frontend

A React + TypeScript status page, served by Vite. It shows whether the FastAPI
backend and PostgreSQL database are reachable.

## Install and run

Use Node.js 22.12 or newer; this project was verified with Node.js 22.14.
Start PostgreSQL and FastAPI using the [backend instructions](../backend/README.md).
FastAPI should listen on port 8001.

In a separate PowerShell terminal:

```powershell
cd D:\GitFox\frontend
npm ci
npm run dev
```

Open <http://127.0.0.1:5173> (or <http://localhost:5173>).
The server uses a fixed port so the backend's local CORS settings match.

The backend address defaults to http://127.0.0.1:8001. To use a different address,
copy .env.example to .env and change VITE_API_BASE_URL, then restart Vite.
VITE_ values are public browser configuration: database credentials and API keys
belong only in backend/.env.

## What happens on this page

1. When opened, the page requests GET /health and GET /ready from FastAPI.
2. It validates each JSON response and displays the API and database status separately.
3. Check again repeats the requests and updates the last-checked time.

Each request has an eight-second timeout. An unavailable database does not mark a
healthy API as unavailable. Errors show useful messages without displaying raw
backend error bodies. There is no automatic polling.

The browser only calls FastAPI. FastAPI makes the PostgreSQL connection.

## Files to follow

| File | Purpose |
|---|---|
| src/main.tsx | Mounts React inside index.html. |
| src/App.tsx | Renders the page, starts the checks, and handles refresh. |
| src/api/status.ts | Makes requests, validates responses, and handles timeouts. |
| src/index.css | Styles the desktop and mobile layouts. |
| vite.config.ts | Enables React support in the Vite development/build tools. |
| tsconfig.json | Configures TypeScript checks. |

## Verify

```powershell
npm run typecheck
npm run build
```

The build includes TypeScript checking and writes the production files to dist/.
To serve that build locally, run npm run preview and open http://127.0.0.1:4173.
If checking the backend from that preview, explicitly include its origin in the
backend's CORS_ORIGINS and restart FastAPI.

## Browser tests

Install Playwright's Chromium browser once, then run the tests:

```powershell
npx playwright install chromium
npm run test:e2e
```

Alternatively, use an already installed Google Chrome browser:

```powershell
$env:PLAYWRIGHT_CHANNEL = "chrome"
npm run test:e2e
```

The ordinary tests mock API responses and cover success, database failure,
unreachable API, invalid responses, timeout, retry, mobile layout, and keyboard use.
The real backend check is skipped by default. With FastAPI and PostgreSQL running:

```powershell
$env:RUN_LIVE_STATUS_CHECKS = "1"
npm run test:e2e
```

Playwright starts Vite for the tests or reuses a running development server. Browser
reports and screenshots are ignored by Git.

See the official [Vite guide](https://vite.dev/guide/) and
[React effect documentation](https://react.dev/reference/react/useEffect) for the
tools used here.
