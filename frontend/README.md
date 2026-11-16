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

Axios makes the HTTP requests. TanStack Query manages their loading, error, cached
data, and refresh state. Each endpoint has its own query, so they can resolve
independently. Automatic retries, focus refresh, and reconnect refresh are disabled
for this status page; Check again explicitly refetches both endpoints. A page mount
also checks again. Offline checks are attempted rather than paused indefinitely.

Each request has an eight-second timeout. An unavailable database does not mark a
healthy API as unavailable. Errors show useful messages without displaying raw
backend error bodies. There is no automatic polling.

The browser only calls FastAPI. FastAPI makes the PostgreSQL connection.

## Files to follow

| File | Purpose |
|---|---|
| src/main.tsx | Mounts React and provides the TanStack Query client. |
| src/App.tsx | Renders the page using the status hook and handles Check again. |
| src/hooks/useServiceStatus.ts | Uses TanStack Query to manage each endpoint's state. |
| src/api/client.ts | Creates the shared Axios client, backend address, and timeout. |
| src/api/status.ts | Calls Axios, validates responses, and translates errors into safe messages. |
| src/index.css | Styles the desktop and mobile layouts. |
| vite.config.ts | Enables React support in the Vite development/build tools. |
| tsconfig.json | Configures TypeScript checks. |

## TypeScript for a React developer

React still uses components, props, hooks, and JSX. TypeScript adds checks for the
types of values you pass around. A .tsx file is TypeScript containing JSX; a .ts
file is ordinary TypeScript without JSX.

For example:

```tsx
type TitleProps = { title: string };

function Title({ title }: TitleProps) {
  return <h2>{title}</h2>;
}

// Valid: <Title title="GitFox" />
// Type error: <Title title={123} />
```

The type annotation helps catch the second usage while developing. The browser
runs JavaScript after Vite removes the TypeScript annotations. npm run build also
runs the TypeScript checker before bundling. TypeScript does not validate network
responses at runtime, so the API helper still checks the JSON received from FastAPI.

The request flow is App.tsx -> useServiceStatus -> Axios -> FastAPI. The hook gives
App.tsx a status object to display; App.tsx no longer manages requests with useEffect.

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

See the official [Vite guide](https://vite.dev/guide/),
[TypeScript React guide](https://www.typescriptlang.org/docs/handbook/react.html),
[Axios documentation](https://axios-http.com/docs/intro), and
[TanStack Query overview](https://tanstack.com/query/latest/docs/framework/react/overview).
