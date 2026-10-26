# Leopard Support

Conversational IT support for Wentworth Institute of Technology. Students and staff describe a tech problem in their own words and get step-by-step help grounded in TechSpot guides. When a detail is missing, the app asks one specific question. When a person is needed, it drafts a ticket (device, error, steps already tried) to hand to TechSpot.

The guide library is synthetic until TechSpot and the university security team approve access to the real knowledge base.

| Part | Stack | Path |
|---|---|---|
| Web | Next.js 16, React 19, plain CSS | `apps/web` |
| API | FastAPI, PostgreSQL + pgvector, FastEmbed (bge-small) | `apps/api` |
| Database migrations | SQL, applied by ingest | `infra/migrations` |
| Synthetic guides | JSON | `fixtures/synthetic_guides` |

## Run locally

Requirements: Python 3.11 with [uv](https://docs.astral.sh/uv/), Node 22+, and PostgreSQL 16+ with pgvector. You can use Docker (`make db`) or a local install listening on `127.0.0.1:55432` with the credentials from `.env.example`.

```sh
cp .env.example .env
make setup      # Python + npm dependencies
make db         # Postgres with pgvector (Docker)
make ingest     # run migrations and load the synthetic guides
make dev        # API on :8000, web on :3000
```

Tests:

```sh
.venv/bin/pytest -q                                   # backend
cd apps/web && npm run lint && npm run typecheck      # web
cd apps/web && npx playwright test                    # browser tests (app must be running)
```

The default browser suite (`chat`, `audit`) expects the classic dialogue: `DIALOGUE_MODE=classic CORPUS_VERSION=synthetic-2026-10-v1`. The `DIAGNOSTIC_E2E=1` and `FOLLOWUP_E2E=1` suites run against the default conversational mode.

## Web app layout

- `app/`: routes (chat, `sources/[id]` guide viewer, `team` results, error and 404 pages)
- `features/shell/`:
  - `AppShell`: sign-in state, history rail, switching conversations
  - `TopBar`, `HistoryRail`, `SignInDialog`
- `features/chat/`:
  - `AccessGate`: waits for the API to wake, then handles pilot sign-in
  - `ChatWorkspace`: conversation state, sending, retries, feedback, ticket
  - `MessageCard`, `FeedbackRow`, `TicketDraft`, `Composer`
- `lib/api.ts`: API client and shared types
- `lib/account.ts`: Firebase sign-in (Google, email link, optional phone)
- `components/`: icons, the Leopard mark and the small reply formatter

## Deploy (free)

| Piece | Host |
|---|---|
| Web | Vercel (Hobby) |
| API | Render free web service, Docker, from `render.yaml` |
| Database | Neon free Postgres |
| Answers | Gemini API free tier (`gemini-3.5-flash-lite`) |
| Sign-in (optional) | Firebase Authentication |

1. **Neon:** create a project and copy its connection string (keep `?sslmode=require`). Load the guides from your machine, and raise the external-call allowance (it defaults to 15). In demo mode the API also applies new migrations itself at startup:

   ```sh
   DATABASE_URL='postgresql://…neon.tech/neondb?sslmode=require' PYTHONPATH=apps/api .venv/bin/python -m app.ingest
   psql "$DATABASE_URL" -c "UPDATE provider_usage SET authorized_limit=2000 WHERE id=1;"
   ```

2. **Gemini:** create an API key at [Google AI Studio](https://aistudio.google.com/apikey).

3. **Render:** New → Blueprint, then pick this repo. Fill in the three secrets:
   - `DATABASE_URL`: from Neon
   - `GEMINI_API_KEY`: from step 2
   - `WEB_ORIGIN`: the Vercel URL, e.g. `https://leopard-support.vercel.app`

   Check `https://<service>.onrender.com/api/health`; it should report `"status": "ready"`.

4. **Vercel:** import the repo and set **Root Directory** to `apps/web`. Add the environment variables below for Production and Preview, then deploy. The rewrite from `/api/*` to the API is fixed at build time, so redeploy whenever `API_BASE_URL` changes.
   - `API_BASE_URL=https://<service>.onrender.com`
   - `NEXT_PUBLIC_SUPPORT_EMAIL`: optional; fills in the "Email to TechSpot" address

5. **Sign-in (optional).** Without these settings the app runs guest-only.
   1. Create a project at [console.firebase.google.com](https://console.firebase.google.com) and add a **Web app**. Copy its config values.
   2. Under **Authentication → Sign-in method**, enable **Google** and **Email/Password** with **Email link (passwordless sign-in)** turned on.
   3. Under **Authentication → Settings → Authorized domains**, add your Vercel domain.
   4. In Vercel, add these and redeploy:
      - `NEXT_PUBLIC_FIREBASE_API_KEY`
      - `NEXT_PUBLIC_FIREBASE_AUTH_DOMAIN`
      - `NEXT_PUBLIC_FIREBASE_PROJECT_ID`
      - `NEXT_PUBLIC_FIREBASE_APP_ID`
   5. In Render, set `FIREBASE_PROJECT_ID` to the same project ID.
   6. **Phone sign-in** costs about $0.01 per text and needs Firebase's pay-as-you-go plan. To turn it on, enable **Phone** in Firebase, then set `NEXT_PUBLIC_ENABLE_PHONE_SIGN_IN=1` in Vercel.

   The API stores only the Firebase user ID, not email addresses or phone numbers. Guests can still chat; when they sign in, their open conversation moves into their history.

Free-tier notes:

- **Render cold starts:** the free API sleeps after about 15 minutes idle and takes up to a minute to wake. The web app shows a "waking up" screen meanwhile. Before demos, open the site a few minutes early, or point a free uptime monitor at `/api/live`.
- **Neon:** scales to zero when idle and wakes in about a second. It doesn't pause the project.
- **Allowance:** `EXTERNAL_CALL_LIMIT` and `provider_usage.authorized_limit` cap total Gemini calls (about 2 per chat turn). Raise both if the allowance notice appears.
