# Leopard Support

Conversational IT support for Wentworth Institute of Technology. Students and staff describe a tech problem in their own words and get step-by-step help grounded in TechSpot guides. When a detail is missing, the app asks one specific question. When a person is needed, it drafts a ticket (device, error, steps already tried) to hand to TechSpot.

The guide library is synthetic until TechSpot and the university security team approve access to the real knowledge base.

## Campus integration milestone

`AGENT_MODE=grounded` enables an opt-in campus integration path. The default remains
`guided` until the deployment has completed the release checks below. This code is
an integration candidate, not evidence of university approval or live-model quality.

The grounded turn is: interpret the current message → admit supported user facts →
retrieve permitted sources → choose a bounded action → read the retrieved evidence
with the model → validate citations → save and display the answer. In pilot mode,
both model calls run outside database transactions and are covered by the existing
durable request ID, concurrency limits and provider spend grants. There are at most
two provider calls per turn; no autonomous account changes or ticket submission.

The second call receives up to three source sections, including the current approved
procedure and relevant informational context. The backend checks exact quoted
passages and source membership, and displays the reviewed procedure steps separately.
Those checks **do not prove semantic entailment**: a paraphrase can cite real words
and still misinterpret them. Real-model and independent staff review remain release
requirements. The offline provider copies a source excerpt to exercise the plumbing;
it is explicitly labeled scripted and must never count as an LLM qualification.

User details need supporting words from the current message before becoming hard
retrieval filters. Unsupported interpretations are retained as `unverified` facts.
Known aliases support conservative normalization; this is not a general semantic
proof that a quoted fact describes the affected device. Corrections replace prior
facts, and up to three unresolved issues can be suspended and explicitly resumed.
Authored diagnostic graphs retain control of ordering, attempt counts and completion.

### Importing approved campus documentation

Use a private pilot database and `APP_MODE=pilot`, `DIALOGUE_MODE=conversational`,
`AGENT_MODE=grounded`. Set `APPROVED_CAMPUS_CORPUS_VERSION` to the exact import
version and `CAMPUS_SOURCE_HOSTS` to a JSON array of approved HTTPS hostnames.
These settings are operator attestations: obtain the campus approvals first.
There is no crawler or public upload endpoint.

The JSON envelope has `version`, `permission` and `guides`. For real content:

- `permission.audience` is `campus pilot`; `approved_by` and
  `security_approved_by` record the responsible reviewers.
- Every article has a unique URL-safe `id`, `title`, category, approved HTTPS
  `source_url`, explicit `is_synthetic: false`, `content_owner`, current
  `reviewed_at` and future `review_due` dates in `YYYY-MM-DD` format.
- `audiences` contains one or more of `campus`, `student`, `staff`. `campus`
  means every invited pilot user. Application administrator status does not grant
  staff-document access. Use `python -m app.pilot_admin invite EMAIL --audience
  student` or `--audience staff` under operator credentials to grant affiliation.
- `applicability` contains reviewed constraints using `Details` fields, such as
  `os` or `network`; use `{}` for generally applicable information. `request_types`
  identifies supported tasks (`troubleshoot`, `install`, `setup`, `access`, `how_to`).
- Sections have `heading`, `text`, and `content_kind`. An `information` section
  has `steps: []` and no workflow. A `procedure` needs 1–6 reviewed steps. Optional
  diagnostic workflows require a versioned, validated graph. JSON, CSV and HTML
  with review metadata are accepted; HTML informational imports do not need fake steps.

Run `PYTHONPATH=apps/api .venv/bin/python -m app.release --corpus PATH` with the
operator environment and a separate `RUNTIME_DB_PASSWORD`. The release command
applies migrations, validates every section, imports embeddings and grants the
restricted runtime role. Deploy the web and API together, and set `CORPUS_VERSION`
to the imported version. An existing version cannot be overwritten: publish changes
as a new version. Keep reviewed source files in approved protected storage, not Git.

Retrieval, source pages and pinned workflow loads share audience, review-expiry and
withdrawal checks. To withdraw an article, run `python -m app.knowledge VERSION
--source-id ID` as an operator; omit `--source-id` to withdraw the corpus. Old pinned
links then become unavailable. Republishing requires a new version. Sources are
revalidated after model inference so a withdrawal during a turn prevents its commit.

Real content is never exposed in demo mode. Permission to import content does not
authorize sending it to an AI provider: the exact `APPROVED_EXTERNAL_CORPUS_VERSION`,
provider configuration and existing database spend grant must separately permit that
processing. The campus path does not change any external-call or spend allowance.

### Opening the invited pilot

Before real students or staff enter the pilot, require:

1. Approved content for the selected 2–3 topics, a named campus sponsor/reviewer,
   approved tester scope, an agreed escalation destination and real campus identity
   configuration. The local test issuer must never be deployed as campus identity.
2. Actual-model evaluation on the approved corpus and a fresh holdout. Proposed
   acceptance thresholds are at least 90% correct eligible retrieval and 90%
   staff-accepted outcomes, with no unauthorized source exposure, unsupported
   consequential instructions or falsely claimed submissions in the release set.
   Staff must approve the rubric and thresholds before qualification.
3. Passing ownership, source visibility, history, deletion, retention and regression
   checks. Run `python -m app.cleanup --apply` on the approved retention schedule.
   Export recovery ledgers to separate protected storage and test backup restoration.
   Ledger version 3 preserves audience grants and source withdrawals as well as
   deletions, invitation revocations and spend counters; older ledgers are rejected.
4. Measured response time and cost within agreed budgets; verified alert delivery,
   provider failure behavior, inference kill switch and rollback to the prior
   reviewed release/corpus. `/api/ready` proves service configuration and accessible
   content, not model quality or permission to launch.

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
