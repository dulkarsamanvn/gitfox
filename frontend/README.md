# GitFox frontend

A React + TypeScript PR preview page, served by Vite. Paste a public GitHub pull
request URL to inspect its metadata, selected patches, and skipped-file reasons.
Service-status cards below the preview show FastAPI and PostgreSQL availability.

## Install and run

Use Node.js 22.12 or newer; this project was verified with Node.js 22.14.
Start FastAPI using the [backend instructions](../backend/README.md), on port 8001.
PostgreSQL is optional for PR previews; start it to make the database status healthy.

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

## Preview a pull request

1. Paste an HTTPS public GitHub PR URL into **GitHub pull request URL**.
2. Click **Preview PR**, or press Enter in the field.
3. Inspect the PR title, author, state, commit details, and selection totals.
4. Expand selected files to read their patches. Skipped files include a reason.

The form calls `POST /api/v1/pull-requests/preview` with `{ "pr_url": "..." }`.
Axios sends the request; a TanStack Query mutation manages loading, errors, and
results. Previews run only on explicit submission, with automatic retries disabled.
They use a 70-second timeout to allow the backend's bounded GitHub retrieval to
finish. **Cancel preview** aborts the browser request and clears its state.

The form normalizes supported PR URLs and catches obvious invalid input before
requesting the API. The backend remains authoritative. During loading, the field
and submit button are disabled, preventing duplicate submissions. Editing the URL
clears previous results, so an old PR's data is not shown for a new input. Each
submission fetches fresh data; there is no persisted browser preview cache.

The API helper validates incoming data at runtime, including PR identity, safe
GitHub links, filenames, skip reasons, and coverage/patch-size totals. Unicode
patch sizes use code-point counts to match Python. Errors use fixed messages based
on known backend codes; raw backend messages are not displayed. Repository titles,
paths, and patches render as text, without HTML or Markdown execution.

Empty PRs and previews with no selected patches have explicit empty states. A
failed database readiness check does not disable previews. This UI previews code
changes; AI findings and saved-review history come later.

## LLM configuration

Open **LLM configuration** below the PR preview. Choose OpenAI, Anthropic Claude,
or Google Gemini, then enter a model ID available to your account. **Find model
IDs** opens the provider's official documentation; model availability is account
specific, so no model is hardcoded as a default.

Enter an API key in the masked field, or leave it blank to keep a key already
configured for that provider on the backend. The API reports only whether a key
exists, never the saved key itself.

- **Test connection** checks the current draft's credentials and model visibility.
  It does not save settings, generate text, test generation quota/billing, or prove
  that a model can produce the review schema.
- **Save configuration** saves the provider, model, and optional replacement key
  to the local backend. It does not automatically run a connection test. The key
  field is cleared after saving, including when replacing an existing key.

Changes clear previous success/error messages. Fields are disabled while saving
or testing to avoid stale results. Settings load only when the panel is opened;
closing it unmounts the form and cancels browser requests. A test has a 20-second
browser timeout around the backend's 15-second provider deadline.

Draft keys are held only in form/request memory: they are not put into localStorage,
sessionStorage, query results, or mutation variables. Axios errors are replaced
with safe errors so request configurations containing keys are not retained as
mutation errors. Raw backend/provider messages are not displayed.

Saved credentials live in the Git-ignored `backend/.llm-settings.json` file, as
local plaintext, with backend environment keys as a fallback. This is a local
configuration interface; it requires a loopback backend connection and an allowed
local browser origin. Backend authentication and public remote administration
are outside this local setup. See the [backend configuration API](../backend/README.md#llm-provider-configuration).

This prepares provider settings for the future AI review client. PR previews still
fetch GitHub data and select patches without generating an AI review.

## Service-status checks

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
| src/App.tsx | Places the PR preview above service status and handles Check again. |
| src/components/PrPreview.tsx | PR input, loading/errors, metadata, selected patches, and skipped-file results. |
| src/hooks/usePrPreview.ts | TanStack mutation lifecycle, duplicate-submit guard, and browser cancellation. |
| src/api/pullRequests.ts | PR types, URL normalization, Axios POST, runtime response checks, and safe errors. |
| src/components/LlmSettings.tsx | Provider/model/key form, save result, and model-access test result. |
| src/hooks/useLlmConfiguration.ts | Lazy configuration query and secret-free mutation variables. |
| src/api/llm.ts | LLM API types, safe errors, and public response validation. |
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

The preview flow is PrPreview -> usePrPreview -> fetchPrPreview -> Axios -> FastAPI.
The service-status flow is App.tsx -> useServiceStatus -> Axios -> FastAPI.

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

The ordinary tests mock API responses and cover PR submission, metadata/patches,
renames, skipped reasons, empty states, cancellation, invalid input/responses,
safe error messages, stale-result clearing, Unicode, text rendering, mobile layout,
keyboard use, and the existing service-status states. The browser clock tests the
70-second preview timeout without a real 70-second wait. Desktop and mobile preview
screenshots are written to the ignored `test-results/` directory.
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
