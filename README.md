# Data analysis workspace

Upload CSV files, prepare related tables on a canvas, and ask questions about the data. The frontend uses Next.js. FastAPI handles validation, DuckDB queries and Gemini calls. Local Supabase services provide authentication, Postgres and private file storage.

## Architecture

```mermaid
flowchart LR
    Browser[Next.js frontend] <-->|Sign in| Auth[Supabase Auth]
    Browser -->|Signed CSV upload| Storage[(Private object storage)]
    Browser -->|Authenticated requests| API[FastAPI]
    API <--> DB[(Postgres metadata and results)]
    API <--> Storage
    API --> DuckDB[Local DuckDB calculations]
    API <--> Gemini[Gemini plans and explanations]
    API <--> Redis[(Redis dashboard cache)]
    DuckDB <--> Disk[Temporary CSV and Parquet cache]
```

CSV validation, joins, stacking, SQL execution and exports run in FastAPI. Postgres stores metadata and results; object storage holds source and prepared CSV files. Processing stays in one backend service, with no separate worker or task queue. Docker Compose runs the frontend, backend and local Supabase dependencies.

The code is split into `app/` and `components/` for the interface, `lib/` for frontend API access, `shared/` for types, `backend/app/` for Python services, and `infra/` for local infrastructure. Tests are in `tests/` and `backend/tests/`.

## Start locally

Install Docker with Compose and Python 3.12+. Start Docker, then run from the repository root:

```bash
python3 scripts/local_setup.py
```

This creates a private `.env` with local service credentials. Add your Gemini key to **the root `.env`**:

```dotenv
GEMINI_API_KEY=your-key
GEMINI_MODEL=gemini-2.5-flash
```

The project URL setting is `SUPABASE_PUBLIC_URL`. Locally it is `http://127.0.0.1:54321`. For a hosted backend, create an environment variable with that name in Render or Railway and use the HTTPS project URL from Supabase. It does not have to be present in a generated `.env` before you can add it. Keep cloud credentials separate from the local Docker credentials. [.env.example](.env.example) lists the hosted backend settings and current authentication compatibility limits.

For hosted requests, `ALLOWED_ORIGINS` is a comma-separated list of frontend origins, for example `https://your-frontend.vercel.app`. Use the address actually open in the browser; Vercel preview addresses differ from the production address. Spaces and trailing slashes are normalized, but paths and wildcard domains are rejected. `SUPABASE_PUBLIC_URL` must be the project base URL, without `/rest/v1`; only the storage settings use the `/storage/v1` suffix. Save and deploy backend environment changes in Render. A changed `NEXT_PUBLIC_API_BASE_URL` needs a new frontend build in Vercel.

Then start the services:

```bash
docker compose up --build -d --wait
```

Open [the application](http://127.0.0.1:3000). Create an account using an email and password, or continue as a guest. Email confirmation is disabled for local testing. New accounts and guests start with an empty workspace and can upload their own CSV files. Guest access is tied to the browser session; create an account for an account you can sign back into.

| Service | Local address |
| --- | --- |
| Frontend | http://127.0.0.1:3000 |
| Backend | http://127.0.0.1:4000 |
| API documentation | http://127.0.0.1:4000/docs |
| Auth and storage gateway | http://127.0.0.1:54321 |
| Postgres | 127.0.0.1:54322 |
| Redis | 127.0.0.1:6379 |

All infrastructure runs locally. Gemini is the only external service, and questions and dashboard generation need a valid key and internet access. Uploading, preparing, previewing and exporting data work without it. There are no simulated answers.

Docker checks service readiness every 30 seconds after startup. `/health` is a cheap liveness response; `/ready` checks the database. Neither endpoint calls Gemini or consumes question quota. Ordinary workspace reads and saves do not compete with the model-request concurrency limit.

### After changing the API key

Compose reads `.env` when it creates a container. A plain restart does not load changed values. Run:

```bash
docker compose up -d --force-recreate backend
```

Refresh the browser. [Backend health](http://127.0.0.1:4000/health) should report `"analysis": true`. This means a key is configured; it does not check the provider's quota or validate the key.

If you changed code, rebuild instead:

```bash
docker compose up --build -d --wait
```

Stop with `docker compose down`. Named volumes keep accounts, metadata and files across restarts. Do not remove those volumes unless you intend to erase the local data. Keep `.env` after setup because its credentials match the initialized database.

## Using the application

1. Create an analysis and upload CSV files.
2. Arrange tables on the canvas. Connect columns for an inner or left join, or drop matching tables onto each other to stack them. Original files remain available.
3. Open Data preview to inspect a selected table.
4. In Analysis, select a table or **All tables** from the dropdown, then type a question and send it. All tables uses the schemas and saved relationships to choose relevant data and give one combined answer.
5. In Dashboard, choose tables and generate a dashboard. Reopening a saved dashboard does not call Gemini again. You can also pin question results and export data or a report.

Changing data creates a new version. Earlier findings remain stored with their original versions and are not shown as current results. Moving a card does not regenerate data. Delete an analysis from its card to remove its records and files.

Use **+**, **−**, **100%** and **Fit tables** above the canvas to change zoom. Ctrl/Command + scroll also zooms. The pencil button on each table renames it without changing its data or connections. **Preview** shows the first eight rows below the canvas, including joined and stacked outputs. Zoom and preview selection survive a refresh in the current browser tab.

Each analysis has its own URL: `/analyses/{id}/setup`, `/data`, `/analysis` and `/dashboard`. The selected table is kept in the `table` query parameter. Refresh and browser Back/Forward restore that location. Saved data and findings load from the backend; unfinished questions, titles and canvas layouts are kept in session storage for the current browser tab. These editing drafts are not shared between devices.

All tables normally makes two Gemini calls for the whole question: one plan with up to three SQL calculations, then one combined explanation. SQL repairs share a maximum of two extra calls. Saved request retries make no model calls. Full CSV files stay in storage and are processed locally; model prompts contain compact metadata, short samples and bounded results.

## Development and checks

Install Node.js 22+ and [uv](https://docs.astral.sh/uv/getting-started/installation/) to run processes outside Docker:

```bash
npm ci
uv sync --directory backend --frozen
docker compose up -d --wait redis db auth rest storage gateway
npm run dev
```

If the app containers are already running, stop them first with `docker compose stop frontend backend` to free ports 3000 and 4000. `npm run dev` starts both the frontend and backend. Both read the same local configuration; provider credentials stay on the backend.

With the local infrastructure running:

```bash
npm run typecheck
npm run lint
npm test
npm run lint:backend
npm run test:backend
npm run evaluate
npm run build
```

Integration tests use real local Redis, Postgres, Auth, Storage and DuckDB with a deterministic test-only model. They do not make paid model calls. Optional live planning checks use the configured Gemini key:

```bash
npm run evaluate -- --live
```

## Redis configuration

Docker Compose starts Redis automatically and connects the backend to `redis://redis:6379/0`. When running the backend outside Docker, `REDIS_URL` defaults to `redis://127.0.0.1:6379/0`. Keep Redis running alongside the other local infrastructure.

For Railway, set the backend's `REDIS_URL` to the TLS connection string from Upstash, for example `rediss://default:YOUR_TOKEN@YOUR_ENDPOINT:6379`. Use the actual port supplied by Upstash. The same Python client handles both environments; an Upstash REST URL is not a Redis connection string. See [Upstash's connection instructions](https://upstash.com/docs/redis/howto/connect-client).

Set `REDIS_NAMESPACE` to a separate value for each environment, such as `data-analysis:production` or `data-analysis:staging`. Both settings belong on the backend. Redis credentials must never use a `NEXT_PUBLIC_` variable. Supabase Storage still receives signed uploads directly from the browser.

## Hosted authentication

In Supabase, open Authentication → URL Configuration. Set the Site URL to the deployed frontend, such as `https://your-frontend.vercel.app`. Add `https://your-frontend.vercel.app/` to Redirect URLs. Add `http://localhost:3000/` separately when using the cloud project for local development. Keep the default confirmation email template pointing at Supabase's confirmation link.

Signup explicitly requests a return to the current frontend origin. The frontend processes the returned verification session through the Supabase SDK. After changing these settings, use a new confirmation email; an old email can retain its earlier redirect. If the account is already confirmed, sign in on the deployed frontend.

For ES256 or RS256 projects, the backend verifies tokens against the public signing keys at the configured project's `/auth/v1/.well-known/jwks.json` endpoint. It checks the signature, issuer, audience, expiry and authenticated user role. Keys are cached for five minutes; unknown key IDs can trigger a refresh at most once per 30 seconds. `JWT_SECRET` is optional for those hosted projects, and still required for local or legacy HS256 tokens. `JWT_ISSUER` defaults to the project base URL followed by `/auth/v1`. Authentication changes need a backend deploy on Render and a frontend deploy on Vercel.

## Limits and assumptions

- Up to five source files, 15 MB combined and 20,000 source rows per analysis; 40 columns per table. Derived tables also have a 15 MB and 20,000-row limit.
- CSV files must be UTF-8 with unique, non-empty headers. Dates use `YYYY-MM-DD`. IDs with leading zeros stay text.
- Stacking requires matching column names and compatible types, and preserves duplicates. Joins use equality on one key pair. Empty keys do not match; repeated keys can multiply rows.
- Questions run read-only SQL against selected table versions. Results show at most 200 rows. SQL is validated before execution; generated Python is never executed.
- Anomaly queries use statistical thresholds. Their explanation describes the calculation, not an assumed business cause. Forecast requests can use SQL regression; there is no separate forecasting or semantic-search service.
- One backend process supports two concurrent analytical requests. Busy requests receive a retry message. Work runs inside FastAPI, without a separate worker or durable task queue. Interrupted requests do not automatically resume.
- Redis caches saved dashboards for five minutes, with separate keys per user, analysis and table selection. Data changes invalidate the analysis cache. Responses over 1 MB are served from Postgres without caching. The local Redis container uses up to 64 MB and evicts older keys under memory pressure; its contents are disposable.
- Redis failures fall back to Postgres without regenerating dashboards or calling Gemini. Connection attempts have short timeouts and a five-second retry cooldown. Backend startup and cache recovery invalidate the cache namespace so missed invalidations do not survive recovery. Concurrent fills are checked against invalidation tokens. Keep one backend process initially: miss coalescing and request concurrency limits are per process; a second replica could briefly serve an old cached response during another replica's cache outage, until invalidation or the five-minute expiry.
- The backend also keeps a bounded temporary CSV/Parquet disk cache for DuckDB. This is separate from Redis. Postgres and object storage remain the durable sources of truth.
- Old SQLite files, if present in `backend/.data`, are retained as a backup but are not imported into Postgres.
- Local email auto-confirmation and anonymous login are testing settings. A hosted Vercel frontend uses `NEXT_PUBLIC_API_BASE_URL` set before building; the backend needs a Python-capable host and matching allowed origins. Hosted Supabase email confirmation uses the URL settings described above.

To remove expired or abandoned objects, run this explicit maintenance command while the infrastructure is up:

```bash
uv run --directory backend python -m app.maintenance
```
