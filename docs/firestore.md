# Firestore Persistence (Milestone 3)

This guide explains the backend repository layer, how to configure Firestore on
macOS, and how to verify conversation metadata, shortlist persistence, Firebase
identity isolation, and Maps data.

## What changed

Before this milestone:

```text
conversation owner → Python process memory
shortlist          → browser localStorage
Cloud Run restart  → conversation owner metadata disappears
different browser  → shortlist is not available
```

After this milestone:

```text
Next.js browser
→ authenticated FastAPI route
→ backend service
→ repository interface
→ Firestore in production (or memory repository in local tests)
```

The frontend does not import the Firestore SDK and does not receive Firestore
credentials. Firebase Authentication answers "who is this user?" Firestore
answers "what durable data belongs to this verified user?"

## Easy analogy: service versus repository

Imagine a library:

- The **route** is the front desk receiving a request.
- The **service** is the librarian checking the rules.
- The **repository** is the shelf system used to store or retrieve a book.
- Firestore is one real shelf system; the memory repository is a lightweight
  cardboard shelf used for fast local tests.

The librarian should not care whether the shelf is Firestore or memory. That is
why the code depends on repository interfaces instead of importing Firestore in
every route.

## Request flows

### Conversation metadata

```text
POST /api/chat with verified Firebase uid
→ repository atomically claims conversationId for that uid
→ Agent runs and returns normalized listings
→ repository records turn count and latest listing snapshots
```

The metadata stores the latest normalized listing results, including available
coordinates and commute summaries. It does not store the full prompt, Agent
answer, ADK event trace, provider response, API key, or Maps route polyline.

### Save a listing

```text
POST /api/shortlist with listingId + conversationId
→ backend loads that verified user's conversation metadata
→ backend finds listingId in the latest server-stored results
→ backend saves that snapshot under the verified user's shortlist
```

The browser intentionally does not submit a full listing object. For example, a
user cannot change `$3,800` to `$800` in browser developer tools and make the
backend treat that edited object as the saved verified snapshot.

## Firestore data layout

```text
conversations/{hashed-conversation-id}
  schemaVersion
  conversationId
  ownerHash
  createdAt
  updatedAt
  turnCount
  lastListings[]
  lastCommuteStatus
  lastRouteListingId

users/{hashed-firebase-uid}/shortlist/{hashed-listing-id}
  schemaVersion
  listingId
  sourceConversationId
  listingSnapshot
  savedAt
  updatedAt
```

External IDs are SHA-256 hashed before being used as Firestore document names.
The original listing/conversation ID remains inside the document. This matters
because provider IDs can contain characters such as `/` that are unsafe in a
Firestore document path.

The Firebase UID is not stored in plaintext in these document paths. A one-way
hash separates each user's shortlist.

## Maps behavior

A saved listing snapshot can contain:

```json
{
  "latitude": 37.401,
  "longitude": -122.101,
  "commute": {
    "destination": "Google Mountain View",
    "mode": "DRIVE",
    "durationMinutes": 18,
    "distanceMeters": 12400,
    "status": "available",
    "routingPreference": "TRAFFIC_AWARE"
  }
}
```

Firestore only stores this already-normalized snapshot. The repository does not
call Google Maps, recompute commute time, rank homes, or decide whether a route
passes a hard limit. Those responsibilities remain in the existing Agent/Maps
pipeline.

## What is and is not durable

Durable now:

- conversation ownership;
- conversation timestamps and successful turn count;
- latest normalized listing snapshots;
- shortlist items, including available commute summaries.

Still held by the current ADK process:

- the full multi-turn ADK session;
- raw Agent session state;
- selected-route state/polyline used by `/api/route`.

Therefore, after a Cloud Run restart, the backend still knows that conversation
`C` belongs to user `A`, but the Agent may not remember all earlier natural-
language refinements. Persisting/restoring the full ADK session is a separate
milestone.

## 1. Check Mac prerequisites

From the repository root:

```bash
node --version
uv --version
gcloud --version
```

Node must be at least `20.9.0`; Node 24 is recommended. Milestone 2 Firebase
Authentication and Application Default Credentials should already work.

Install/refresh dependencies:

```bash
uv sync --extra dev --extra backend
cd frontend
npm install
cd ..
```

`firebase-admin` already brings the Python Firestore server client used here.
The frontend does not add a Firestore import.

## 2. Create the Firestore database

Use the same Firebase/Google Cloud project as Milestones 1 and 2:

1. Open Firebase Console.
2. Choose **Build → Firestore Database**.
3. Choose **Create database**.
4. Choose **Firestore in Native mode / Standard edition**.
5. Choose **Production mode** for Security Rules.
6. Choose a location close to the Cloud Run service and confirm it carefully;
   changing database location later is not a normal setting change.

Production mode denies browser/mobile access while the privileged Python server
client can use IAM. That matches this project's FastAPI-only architecture.

The repository also contains `firestore.rules`, which explicitly denies every
direct client read/write. The backend server SDK is controlled by Google Cloud
IAM rather than these client rules.

## 3. Configure local environment variables

In the ignored root `.env` file, keep the existing Gemini, RealtyAPI, Firebase,
and `GOOGLE_MAPS_API_KEY` values. Add:

```dotenv
PERSISTENCE_MODE=firestore
FIRESTORE_PROJECT_ID=your-existing-google-cloud-project-id
FIRESTORE_DATABASE_ID=(default)
```

`GOOGLE_MAPS_API_KEY` remains a separate secret. It is not used to authenticate
to Firestore.

Authenticate the local Python server:

```bash
gcloud config set project 'your-existing-google-cloud-project-id'
gcloud auth application-default login
```

Restart the backend after changing `.env` because settings and repository
factories are cached for the life of the process.

## 4. Run fake-repository tests first

These tests are fast, do not call Google Cloud, do not write real rental data,
and do not consume Firestore or Maps quota:

```bash
uv run --extra dev --extra backend pytest backend/tests/test_persistence.py -q
```

Desired output ends with:

```text
9 passed
```

The test scenarios prove:

- metadata records successful turns;
- commute and coordinates survive a save/list round trip;
- one user cannot claim another user's conversation;
- one user cannot list another user's shortlist;
- save/list/delete work through FastAPI;
- IDs containing `/` are converted to safe Firestore document IDs.

Run the complete suite:

```bash
uv run --extra dev --extra backend pytest backend/tests tests -q
uv run python -m compileall backend rental_agent -q

cd frontend
npm run check
cd ..
```

## 5. Check readiness

Start the application:

```bash
./kbf start
```

Then in a second Terminal:

```bash
curl -s http://localhost:8000/ready | python3 -m json.tool
```

With Firestore configured, look for:

```json
"persistence": "configured"
```

Readiness checks configuration only. The real save/load test below proves that
credentials, IAM, database location, and network access actually work.

## 6. Test real Firestore through the UI

Open <http://localhost:3000> and search for rentals. For Maps coverage, use a
complete commute request such as:

```text
Find a 2-bedroom rental under $4,000 within 25 minutes of Google Mountain View by car.
```

Then:

1. Click **Save** on one result.
2. Confirm the shortlist count increases.
3. Refresh the browser.
4. Confirm the saved home returns.
5. Click **Saved** to remove it.
6. Refresh again and confirm it remains removed.

Desired backend HTTP results in Chrome Developer Tools → Network:

```text
GET    /api/shortlist                 → 200
POST   /api/shortlist                 → 201
DELETE /api/shortlist/<listing-id>    → 204
```

Every request should include `Authorization: Bearer ...`.

## 7. Inspect the stored data

In Firebase Console → Firestore Database → Data, expect:

```text
conversations
users
```

After a successful Maps-aware search, the conversation document's
`lastListings` should include `latitude`, `longitude`, and a `commute` object
when that evidence was available.

After saving, the same normalized information should appear in the shortlist
document's `listingSnapshot`.

Do not expect raw prompts, API keys, complete provider payloads, or an encoded
route polyline.

## 8. Optional local Firestore emulator

The automated test suite uses fake repositories, so installing the emulator is
optional. If you want to inspect Firestore locally without writing cloud data:

```bash
npm install --global firebase-tools
firebase emulators:start --only firestore --project demo-keys-by-friday
```

In another Terminal, start the backend with:

```bash
FIRESTORE_EMULATOR_HOST=127.0.0.1:8081 \
PERSISTENCE_MODE=firestore \
FIRESTORE_PROJECT_ID=demo-keys-by-friday \
AUTH_MODE=disabled \
AGENT_MODE=stub \
LISTING_PROVIDER=mock \
uv run --extra backend uvicorn backend.app.main:app --host 127.0.0.1 --port 8000
```

The emulator UI address is printed by Firebase CLI. The Python Firestore client
automatically honors `FIRESTORE_EMULATOR_HOST`.

The emulator usually requires a supported Java runtime. Skip this optional step
if the fake tests and real Firebase smoke test are sufficient.

## 9. Cloud Run permissions and deployment

The Cloud Run service account needs Firestore application read/write access:

```bash
gcloud projects add-iam-policy-binding "$KBF_PROJECT_ID" \
  --member="serviceAccount:${KBF_SERVICE_ACCOUNT}" \
  --role='roles/datastore.user'
```

Deploy with:

```text
PERSISTENCE_MODE=firestore
FIRESTORE_PROJECT_ID=${KBF_PROJECT_ID}
FIRESTORE_DATABASE_ID=(default)
```

The full deployment command is in `docs/deployment.md`. Do not create or upload
a service-account JSON key. Cloud Run supplies credentials for its attached
service account.

## Index decision

No custom `firestore.indexes.json` file is included.

Current access patterns are:

- exact conversation document read/write by hashed ID;
- exact shortlist item read/write/delete by hashed ID;
- one user's shortlist ordered by the single `savedAt` field.

Firestore supplies automatic single-field indexes, so these operations do not
need a custom composite index. Add a custom index only when a future query
combines fields in a way Firestore reports as requiring one—for example, a
cross-user administrative query filtering by status and ordering by time.

## Common results

| Result | Meaning | Check |
|---|---|---|
| `/ready` says `memory` | Local non-durable repository is selected | `PERSISTENCE_MODE` and backend restart |
| `/ready` says `not_configured` | Firestore project ID is missing | `FIRESTORE_PROJECT_ID` |
| Shortlist request returns `401` | Firebase ID token is missing/invalid | Milestone 2 frontend configuration |
| Save returns `404` | Listing is not in that conversation's latest stored results | current `conversationId` and listing result |
| Save returns `403` | Conversation belongs to another Firebase user | current signed-in identity |
| Request returns `503` | Firestore client, credentials, IAM, or database is unavailable | ADC, database creation, `roles/datastore.user`, logs |
| Save works but commute is absent | Search did not have available Maps evidence | Maps request completeness, key, Routes result |
| Full follow-up context is lost after restart | Metadata survived but ADK session did not | expected current boundary; session persistence is later |
