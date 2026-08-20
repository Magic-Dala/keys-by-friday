# Persistent ADK Sessions (Milestone 4)

This guide explains how Agent conversation memory works, what Milestone 4
changes, and how to test it on macOS without calling Gemini during automated
tests.

## The problem in easy terms

Firestore from Milestone 3 remembers product records such as:

- which Firebase user owns a conversation;
- the latest normalized rental listings;
- saved shortlist items and commute summaries.

That is not the same as the Google ADK session. The ADK session contains the
Agent's event history and working state, such as:

```text
city = Mountain View
max rent = 4000
parking required = false
```

Before Milestone 4, FastAPI used ADK's `InMemoryRunner`. Its session was similar
to writing those facts on a whiteboard inside one backend process:

```text
backend starts  → blank whiteboard
user searches   → requirements appear on whiteboard
backend restarts→ whiteboard is erased
```

Milestone 4 makes the whiteboard configurable:

```text
local/CI default → InMemorySessionService
production       → DatabaseSessionService → PostgreSQL / Cloud SQL
```

The HTTP API is unchanged. The browser continues sending the same
`conversationId` to FastAPI and never talks to the session database directly.

## What each database owns

```text
Firestore
├── conversation ownership and timestamps
├── latest normalized listing snapshots
└── user shortlist

ADK PostgreSQL session database
├── ADK user/model/tool events
├── Agent session state
└── multi-turn context used by follow-up requests
```

This is intentional. Firestore stores application data designed by this team.
The ADK database stores ADK's own internal session tables using Google's
official `DatabaseSessionService`.

Do not manually create or edit the ADK tables. The installed ADK version creates
and manages its schema.

## Configuration

Two backend variables select the session service:

```dotenv
ADK_SESSION_MODE=memory
ADK_SESSION_DATABASE_URL=
```

### Local default

```dotenv
ADK_SESSION_MODE=memory
ADK_SESSION_DATABASE_URL=
```

This is fast and does not create files. Restarting the backend intentionally
loses the ADK session.

### Local restart test with SQLite

```dotenv
ADK_SESSION_MODE=database
ADK_SESSION_DATABASE_URL=sqlite+aiosqlite:///./.local/adk-sessions.db
```

SQLite is one database file on the Mac. It is useful for proving restart
behavior locally, but it is not allowed by production readiness because Cloud
Run's local filesystem is not durable.

### Production with PostgreSQL

```dotenv
ADK_SESSION_MODE=database
ADK_SESSION_DATABASE_URL=postgresql+asyncpg://USER:PASSWORD@/DATABASE?host=/cloudsql/PROJECT:REGION:INSTANCE
```

The URL is a secret because it contains a database password. Store it in Secret
Manager; never commit it or include it in screenshots.

## What database readiness verifies

`/health` only proves that the FastAPI process is alive. When database session
mode is selected, `/ready` also asks ADK's official `DatabaseSessionService` to
perform a non-user session lookup. This forces the service to connect and
prepare its tables before Cloud Run sends normal Agent traffic.

The lookup uses reserved readiness IDs and does not create a user conversation.
It has a five-second timeout. Connection, socket, credential, schema, or timeout
failures produce HTTP 503 with `adk_session: unavailable`; sensitive database
details are not returned to the caller.

## Why PostgreSQL / Cloud SQL was selected

ADK officially supports `DatabaseSessionService` for relational databases. This
project already runs FastAPI on Cloud Run, so Cloud SQL for PostgreSQL gives the
current runtime a durable database without moving the Rental Agent into a
different hosting product.

`VertexAiSessionService` is also an official persistent option, but it requires
an Agent Runtime / Agent Engine resource. That would be a larger deployment
change than this project's current Cloud Run architecture.

## Simultaneous requests

Imagine these requests arrive at almost the same instant:

```text
request A: "I also need parking"
request B: "Actually lower the budget to $3,800"
```

If both read the old state before either finishes, one update can be based on
stale information. `ConversationTurnCoordinator` therefore permits only one
complete Agent turn at a time for the same `(Firebase uid, conversationId)`.

```text
request A acquires conversation lock
request B waits
request A reads → reasons → calls tools → saves state → releases lock
request B then reads the updated state and continues
```

Different conversations use different locks and can still run concurrently.
The lock records are removed when the last waiter finishes, so the dictionary
does not grow forever.

ADK's database service also supplies in-process event locking and PostgreSQL row
locking. The backend-level lock is still useful because it protects the whole
turn, not only the final database event append.

The current Cloud Run deployment remains capped at one instance. Before raising
`--max-instances` above `1`, add or verify distributed whole-turn coordination
under realistic load; an `asyncio.Lock` exists only inside one Python process.

## 1. Install on macOS

The repository now pins Python 3.12 in `.python-version`, matching the Docker
image. From the repository root:

```bash
uv sync --extra dev --extra backend
uv run python --version
```

Expected Python output begins with:

```text
Python 3.12
```

The backend extra installs:

- ADK's database extra and SQLAlchemy;
- `aiosqlite` for the local file test;
- `asyncpg` for production PostgreSQL;
- `greenlet`, explicitly included for SQLAlchemy on Apple Silicon.

## 2. Run the automated Milestone 4 tests

```bash
uv run --extra dev --extra backend pytest backend/tests/test_adk_sessions.py -q
```

Desired ending:

```text
5 passed
```

These tests make zero Gemini, RealtyAPI, Maps, Firestore, or Cloud SQL calls.

The restart test does the following:

```text
1. Create official DatabaseSessionService using a temporary SQLite file.
2. Send "Search Mountain View under $4,000."
3. Destroy the first runner/session-service connection.
4. Create a completely new runner using the same file.
5. Send "I also need parking" with the same conversationId.
6. Confirm city=Mountain View, max_rent=4000, and parking=true.
```

The concurrency test starts two turns for the same conversation and proves that
the maximum number executing inside the Agent boundary at once is `1`.

Run every project check afterward:

```bash
uv run --extra dev --extra backend pytest backend/tests tests -q
uv run python -m compileall backend rental_agent -q

cd frontend
npm run check
cd ..
```

## 3. Manually reproduce the accepted restart example

This test calls the real Agent, so it can use Gemini and provider quota. Keep
your existing Gemini/Vertex AI and RealtyAPI configuration.

Create the ignored local directory:

```bash
mkdir -p .local
```

Temporarily set these values in the ignored root `.env`:

```dotenv
ADK_SESSION_MODE=database
ADK_SESSION_DATABASE_URL=sqlite+aiosqlite:///./.local/adk-sessions.db
```

Start only the backend:

```bash
uv run --extra backend uvicorn backend.app.main:app --host 127.0.0.1 --port 8000
```

In a second Terminal, send the first request with an explicit conversation ID:

```bash
curl -s \
  -H 'Content-Type: application/json' \
  -d '{"message":"Search Mountain View under $4,000.","conversationId":"restart-demo-1"}' \
  http://localhost:8000/api/chat | python3 -m json.tool
```

If Firebase auth is enabled locally, use the normal browser test instead or add
a valid `Authorization: Bearer ...` Firebase ID token. Do not paste tokens into
source files or screenshots.

Now:

1. Press `Control+C` in the backend Terminal.
2. Start the same backend command again.
3. Send the follow-up using the exact same `conversationId`:

```bash
curl -s \
  -H 'Content-Type: application/json' \
  -d '{"message":"I also need parking.","conversationId":"restart-demo-1"}' \
  http://localhost:8000/api/chat | python3 -m json.tool
```

Desired behavior: the response and active filters still include Mountain View
and the $4,000 budget, with parking added.

To start a clean manual test, stop the backend and delete only this ignored test
file:

```bash
rm .local/adk-sessions.db
```

Then return `.env` to memory mode for ordinary local work if desired:

```dotenv
ADK_SESSION_MODE=memory
ADK_SESSION_DATABASE_URL=
```

## 4. Check readiness

```bash
curl -s http://localhost:8000/ready | python3 -m json.tool
```

Local memory mode reports:

```json
"adk_session": "memory"
```

Reachable database mode reports:

```json
"adk_session": "connected"
```

Configured but unreachable database mode reports `unavailable` with HTTP 503.

Production rejects these unsafe configurations:

```text
memory with APP_ENV=production → memory_not_allowed
SQLite with APP_ENV=production → sqlite_not_allowed
database mode without URL      → not_configured
```

Readiness verifies configuration, not a live database query. The restart test
or a real follow-up proves the connection and stored session actually work.

## 5. Prepare Cloud SQL when ready to deploy

Cloud SQL creates billable infrastructure. Create it only when the team is ready
for the hosted persistence test, and remove it afterward if it is no longer
needed.

In Google Cloud Console:

1. Open **SQL**.
2. Create a **PostgreSQL** instance in the same region as Cloud Run.
3. Choose the smallest development configuration that meets the demo needs.
4. Create a database named `kbf_adk_sessions`.
5. Create a non-admin built-in user named `kbf_adk` with a strong password.
6. Copy the instance connection name, formatted as
   `PROJECT_ID:REGION:INSTANCE_ID`.

Store the complete async database URL as a Secret Manager secret named
`kbf-adk-session-db-url`. The Cloud Run command in `docs/deployment.md` attaches
the Cloud SQL instance and exposes that secret only as
`ADK_SESSION_DATABASE_URL`.

The backend service account needs `roles/cloudsql.client`. It does not need the
Cloud SQL Admin role to serve requests.

## Common results

| Result | Meaning | Fix |
|---|---|---|
| `/ready` shows `memory` | Restart-safe sessions are not selected | set database mode and restart backend |
| `/ready` shows `not_configured` | Database mode has no URL | set `ADK_SESSION_DATABASE_URL` |
| `/ready` shows `sqlite_not_allowed` | A local file was configured in production | use Cloud SQL PostgreSQL |
| `/ready` shows `connected` | ADK completed a real database session lookup | the session database is ready |
| `/ready` shows `unavailable` | ADK could not complete its database lookup within five seconds | check the URL secret, Cloud SQL attachment, password, database, IAM, and instance availability |
| Chat returns `502` immediately | ADK session service could not initialize/connect | check driver, URL, secret, Cloud SQL attachment, and IAM |
| First turn works but restart loses context | requests used different session stores or IDs | check mode, URL, uid, and exact `conversationId` |
| Simultaneous follow-up waits | the same-conversation safety lock is working | allow the first turn to complete |
| Different conversations all wait | unexpected global serialization | inspect conversation IDs and coordinator usage |

## Gemini 3.7 note

The Rental Agent owns Gemini model selection and fallback policy. The backend
environment and Cloud Run configuration intentionally do not set model-routing
variables. Model selection is independent of session storage: changing an
Agent-owned model does not change where ADK history is saved.

Before deploying, run one live request in the intended Vertex AI project and
region to confirm that the exact model ID is available to that project. A model
availability error should be treated separately from a session database error.
