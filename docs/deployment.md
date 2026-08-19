# Backend Deployment

This guide deploys the existing FastAPI → AgentService → Google ADK path to
Cloud Run. It does not create a second Agent API or change the frontend contract.

## What the container runs

```text
Cloud Run HTTPS request
→ Uvicorn on 0.0.0.0:$PORT
→ FastAPI
→ AgentService
→ Google ADK Rental Agent
```

Cloud Run supplies `PORT`. The container defaults to port `8080` when run
locally.

## Local test on macOS

From the repository root, test without external API keys:

```bash
APP_ENV=local \
AGENT_MODE=stub \
AUTH_MODE=disabled \
PERSISTENCE_MODE=memory \
ADK_SESSION_MODE=memory \
LISTING_PROVIDER=mock \
uv run --extra backend uvicorn backend.app.main:app --host 127.0.0.1 --port 8000
```

Open another Terminal window and run:

```bash
curl -i http://localhost:8000/health
curl -i http://localhost:8000/ready
curl -i \
  -H 'Content-Type: application/json' \
  -H 'X-Request-ID: mac-smoke-test' \
  -d '{"message":"2B2B under $4,000 in Mountain View"}' \
  http://localhost:8000/api/chat
```

Expected results:

- `/health` returns HTTP 200 and `{"status":"ok"}`.
- `/ready` returns HTTP 200 and reports `agent: stub`.
- `/api/chat` returns HTTP 200, a `conversationId`, `mode: stub`, and an empty
  listing array.
- Responses include an `X-Request-ID` header.
- The backend Terminal prints one-line JSON request logs.

To test the real Agent through Vertex AI, authenticate your Mac once:

```bash
gcloud auth application-default login
```

Then configure the ignored root `.env` file:

```dotenv
GOOGLE_GENAI_USE_VERTEXAI=TRUE
GOOGLE_CLOUD_PROJECT=your-google-cloud-project-id
GOOGLE_CLOUD_LOCATION=global
GOOGLE_API_KEY=
GEMINI_API_KEY=
```

Vertex AI uses your Google Cloud login locally, so it does not need a Gemini API
key. Keep the existing RealtyAPI and Firebase settings in `.env`, then run:

```bash
uv run --extra backend uvicorn backend.app.main:app --host 127.0.0.1 --port 8000
```

Then repeat the `/ready` and `/api/chat` requests. The real response should have
`mode: adk`, readable Agent text, and source-backed entries in `listings` when
matches are available.

## Local Docker test

Start Docker Desktop, then run:

```bash
docker build -t keys-by-friday-backend:local .
docker run --rm \
  --name keys-by-friday-backend \
  -p 8080:8080 \
  -e APP_ENV=local \
  -e AGENT_MODE=stub \
  -e AUTH_MODE=disabled \
  -e PERSISTENCE_MODE=memory \
  -e ADK_SESSION_MODE=memory \
  -e LISTING_PROVIDER=mock \
  keys-by-friday-backend:local
```

In a second Terminal window:

```bash
curl -i http://localhost:8080/health
curl -i http://localhost:8080/ready
curl -i \
  -H 'Content-Type: application/json' \
  -d '{"message":"2B2B under $4,000 in Mountain View"}' \
  http://localhost:8080/api/chat
```

Press `Control+C` in the Docker Terminal to stop the container.

To run the real Agent in Docker, keep secrets outside the image and pass the
ignored local environment file at runtime:

```bash
docker run --rm \
  --name keys-by-friday-backend \
  -p 8080:8080 \
  --env-file .env \
  keys-by-friday-backend:local
```

## Install and initialize Google Cloud CLI on macOS

Install the Google Cloud CLI using Google's macOS instructions, then run:

```bash
gcloud init
gcloud auth application-default login
```

Set shell variables for this Terminal session. Replace the example values:

```bash
export KBF_PROJECT_ID='your-google-cloud-project-id'
export KBF_REGION='us-west1'
export KBF_SERVICE='keys-by-friday-backend-1'
export KBF_FRONTEND_ORIGIN='http://localhost:3000'
export KBF_SERVICE_ACCOUNT="kbf-backend@${KBF_PROJECT_ID}.iam.gserviceaccount.com"
export KBF_INVOKER_EMAIL="$(gcloud config get-value account)"
export KBF_CLOUD_SQL_INSTANCE='kbf-adk-sessions'
export KBF_CLOUD_SQL_CONNECTION_NAME="${KBF_PROJECT_ID}:${KBF_REGION}:${KBF_CLOUD_SQL_INSTANCE}"
```

These values are configuration, not secrets.

## Prepare the Google Cloud project

Select the project and enable the required services:

```bash
gcloud config set project "$KBF_PROJECT_ID"
gcloud services enable \
  run.googleapis.com \
  cloudbuild.googleapis.com \
  artifactregistry.googleapis.com \
  secretmanager.googleapis.com \
  sqladmin.googleapis.com \
  firestore.googleapis.com \
  aiplatform.googleapis.com \
  routes.googleapis.com
```

Create a dedicated identity for the backend:

```bash
gcloud iam service-accounts create kbf-backend \
  --display-name='Keys by Friday backend'

gcloud projects add-iam-policy-binding "$KBF_PROJECT_ID" \
  --member="serviceAccount:${KBF_SERVICE_ACCOUNT}" \
  --role='roles/aiplatform.user'

gcloud projects add-iam-policy-binding "$KBF_PROJECT_ID" \
  --member="serviceAccount:${KBF_SERVICE_ACCOUNT}" \
  --role='roles/datastore.user'

gcloud projects add-iam-policy-binding "$KBF_PROJECT_ID" \
  --member="serviceAccount:${KBF_SERVICE_ACCOUNT}" \
  --role='roles/cloudsql.client'
```

The `Vertex AI User` role lets this backend identity call Gemini through Vertex
AI. Cloud Run automatically supplies credentials for its attached service
account, so do not create a Gemini API key and do not set
`GOOGLE_APPLICATION_CREDENTIALS` in Cloud Run.

The `Cloud Datastore User` role is Firestore's application read/write role. It
allows the backend service account to store conversation metadata and each
verified user's shortlist without granting index-administration access.

The `Cloud SQL Client` role lets the same backend identity open the encrypted
Cloud SQL connection used by ADK session storage. It does not grant Cloud SQL
administration permission.

## Prepare persistent ADK session storage

Create a small PostgreSQL Cloud SQL instance only when the team is ready for a
billable hosted test. Use the same region as Cloud Run, create database
`kbf_adk_sessions`, create non-admin user `kbf_adk`, and copy the instance
connection name.

Store this async SQLAlchemy URL in Secret Manager as
`kbf-adk-session-db-url`:

```text
postgresql+asyncpg://kbf_adk:URL_SAFE_PASSWORD@/kbf_adk_sessions?host=/cloudsql/PROJECT_ID:REGION:INSTANCE_ID
```

The password must be URL encoded if it contains URL punctuation. Do not put the
URL in `--set-env-vars`, source control, screenshots, or chat. Detailed macOS,
local SQLite, Cloud SQL, and restart instructions are in
`docs/adk-sessions.md`.

## Deploy and verify Firestore client rules

The committed `firestore.rules` file denies every direct browser/mobile read and
write. Deploy it explicitly before the Cloud Run revision so the Firebase
project enforces the same boundary as the repository:

```bash
npm install --global firebase-tools
firebase login
firebase deploy --only firestore:rules --project "$KBF_PROJECT_ID"
```

The deploy must finish with a successful Firestore Rules release. Then open
**Firebase Console → Firestore Database → Rules** for `KBF_PROJECT_ID` and
confirm the published rule contains:

```text
match /{document=**} {
  allow read, write: if false;
}
```

Use the Rules Playground on that page with an unauthenticated `get` request to
`/users/rules-verification`; the expected result is **Denied**. This verifies
the deployed client boundary, not merely the checked-in file. The Python Admin
SDK still reaches Firestore through the Cloud Run service account and IAM, so
this deny-all client rule does not block FastAPI.

## Store external API keys in Secret Manager

Read each key without showing it in the Terminal, create the secret, and clear
the temporary shell variable:

```bash
read -s -p 'RealtyAPI key: ' KBF_SECRET_VALUE; echo
printf '%s' "$KBF_SECRET_VALUE" | \
  gcloud secrets create kbf-realtyapi-key --data-file=-
unset KBF_SECRET_VALUE

read -s -p 'Google Maps Routes API key: ' KBF_SECRET_VALUE; echo
printf '%s' "$KBF_SECRET_VALUE" | \
  gcloud secrets create kbf-google-maps-api-key --data-file=-
unset KBF_SECRET_VALUE
```

Allow only the backend service account to read those secrets:

```bash
gcloud secrets add-iam-policy-binding kbf-realtyapi-key \
  --member="serviceAccount:${KBF_SERVICE_ACCOUNT}" \
  --role='roles/secretmanager.secretAccessor'

gcloud secrets add-iam-policy-binding kbf-google-maps-api-key \
  --member="serviceAccount:${KBF_SERVICE_ACCOUNT}" \
  --role='roles/secretmanager.secretAccessor'

gcloud secrets add-iam-policy-binding kbf-adk-session-db-url \
  --member="serviceAccount:${KBF_SERVICE_ACCOUNT}" \
  --role='roles/secretmanager.secretAccessor'
```

## Deploy to Cloud Run

Keep the Cloud Run service private for this milestone. Firebase verifies who owns
a conversation, but anonymous Firebase users are inexpensive to create and do
not prevent an attacker from repeatedly consuming Gemini, RealtyAPI, or Routes
quota. Cloud Run IAM therefore remains the outer deployment boundary until the
public path has distributed rate limiting, aggregate cost caps, and abuse
monitoring.

This gives the backend two different identity checks during private testing:

```text
Cloud Run IAM token  → may this developer/service invoke the private service?
Firebase ID token    → which product user owns this conversation/shortlist?
```

From the repository root:

```bash
gcloud run deploy "$KBF_SERVICE" \
  --source . \
  --project "$KBF_PROJECT_ID" \
  --region "$KBF_REGION" \
  --service-account "$KBF_SERVICE_ACCOUNT" \
  --no-allow-unauthenticated \
  --port 8080 \
  --cpu 1 \
  --memory 1Gi \
  --concurrency 8 \
  --min-instances 0 \
  --max-instances 1 \
  --timeout 180 \
  --add-cloudsql-instances "$KBF_CLOUD_SQL_CONNECTION_NAME" \
  --set-env-vars "APP_ENV=production,AGENT_MODE=adk,AUTH_MODE=firebase,FIREBASE_PROJECT_ID=${KBF_PROJECT_ID},PERSISTENCE_MODE=firestore,FIRESTORE_PROJECT_ID=${KBF_PROJECT_ID},FIRESTORE_DATABASE_ID=(default),ADK_SESSION_MODE=database,LISTING_PROVIDER=realtyapi,GOOGLE_GENAI_USE_VERTEXAI=TRUE,GOOGLE_CLOUD_LOCATION=global,GEMINI_SEARCH_MODEL=gemini-3.7-flash,GEMINI_MODELS=gemini-3.7-flash,AGENT_TIMEOUT_SECONDS=120,LOG_LEVEL=INFO,GOOGLE_CLOUD_PROJECT=${KBF_PROJECT_ID},FRONTEND_ORIGIN=${KBF_FRONTEND_ORIGIN}" \
  --set-secrets 'REALTYAPI_API_KEY=kbf-realtyapi-key:1,GOOGLE_MAPS_API_KEY=kbf-google-maps-api-key:1,ADK_SESSION_DATABASE_URL=kbf-adk-session-db-url:1'
```

Grant only your current Google account permission to invoke the private demo
service:

```bash
gcloud run services add-iam-policy-binding "$KBF_SERVICE" \
  --project "$KBF_PROJECT_ID" \
  --region "$KBF_REGION" \
  --member="user:${KBF_INVOKER_EMAIL}" \
  --role='roles/run.invoker'
```

If an earlier revision was public, remove any legacy `allUsers` Invoker binding:

```bash
gcloud run services remove-iam-policy-binding "$KBF_SERVICE" \
  --project "$KBF_PROJECT_ID" \
  --region "$KBF_REGION" \
  --member='allUsers' \
  --role='roles/run.invoker' \
  --all
```

This command bills Gemini usage to Vertex AI in `KBF_PROJECT_ID`. It does not
use Google AI Studio or a Gemini API key. Routes usage is billed to the same
project through the separate server-side Maps key.

The deployment intentionally does not set `GEMINI_SEARCH_MODEL` or
`GEMINI_MODELS`. The Rental Agent owns model selection and fallback policy.
When coordinating with the Agent-owned routing work, preserve the Firestore
variables in this command: `PERSISTENCE_MODE`, `FIRESTORE_PROJECT_ID`, and
`FIRESTORE_DATABASE_ID`.

`GOOGLE_MAPS_API_KEY` is optional to the ordinary rental-search flow, but it is
required for live commute summaries and selected-route geometry. Restrict this
key to the Google Routes API in Google Cloud Console. See `docs/maps.md` for the
local and deployed Maps checks.

Before making a later service public, confirm that Firebase is enabled and that
the frontend sends Firebase ID tokens, then add server-side distributed limits
for each uid plus an aggregate project-level cap. Provider quotas and billing
alerts are additional safeguards; a billing alert alone does not stop requests.

Firestore keeps conversation ownership/metadata and shortlists. ADK's official
database session service keeps Agent events and state in Cloud SQL, so a restart
or scale-to-zero event does not erase follow-up context. `max-instances=1`
remains intentional because the backend's whole-turn same-conversation lock is
process-local; review distributed turn coordination before scaling above one
instance.

After deployment, configure an HTTP startup/readiness probe for `/ready` and an
HTTP liveness probe for `/health` in the Cloud Run console under **Containers,
Networking, Security → Health checks**.

## Test the deployed service

Get the deployed URL:

```bash
export KBF_BACKEND_URL="$(gcloud run services describe "$KBF_SERVICE" \
  --project "$KBF_PROJECT_ID" \
  --region "$KBF_REGION" \
  --format='value(status.url)')"
echo "$KBF_BACKEND_URL"
```

First confirm that an unauthenticated request is rejected by Cloud Run:

```bash
curl -i "$KBF_BACKEND_URL/health"
```

The desired result is an HTTP `401` or `403` generated by Cloud Run because the
request has no Cloud Run identity token. It should not reach FastAPI.

Create a short-lived Cloud Run identity token for the developer account that has
the Invoker role:

```bash
export KBF_CLOUD_RUN_TOKEN="$(gcloud auth print-identity-token)"
```

This developer token is only for a short manual smoke test. Production
service-to-service callers should use a service-account ID token whose audience
is the Cloud Run service URL.

Now the platform should allow health and readiness requests through to FastAPI:

```bash
curl -i \
  -H "Authorization: Bearer ${KBF_CLOUD_RUN_TOKEN}" \
  "$KBF_BACKEND_URL/health"

curl -i \
  -H "Authorization: Bearer ${KBF_CLOUD_RUN_TOKEN}" \
  "$KBF_BACKEND_URL/ready"
```

Confirm that FastAPI still rejects a chat request without a Firebase token. Use
`X-Serverless-Authorization` for the Cloud Run token so the normal
`Authorization` header remains available to Firebase authentication:

```bash
curl -i \
  -H "X-Serverless-Authorization: Bearer ${KBF_CLOUD_RUN_TOKEN}" \
  -H 'Content-Type: application/json' \
  -d '{"message":"2B2B under $4,000 in Mountain View"}' \
  "$KBF_BACKEND_URL/api/chat"
```

The desired response is FastAPI HTTP `401` with `A valid sign-in token is
required.` A fully authenticated command-line request needs both headers:

```text
X-Serverless-Authorization: Bearer <Cloud Run identity token>
Authorization: Bearer <Firebase ID token>
```

Do not paste either token into source files, documentation, screenshots, or chat.
Clear the short-lived shell value when testing is complete:

```bash
unset KBF_CLOUD_RUN_TOKEN
```

The current Next.js browser calls FastAPI directly and cannot mint a Cloud Run
IAM token. Therefore, keep browser end-to-end testing local for now. A hosted
browser flow needs an approved public edge such as a server-side frontend proxy
or load balancer/gateway with abuse controls; Firebase authentication alone is
not that edge.

View recent application and platform logs:

```bash
gcloud run services logs read "$KBF_SERVICE" \
  --project "$KBF_PROJECT_ID" \
  --region "$KBF_REGION" \
  --limit 50
```

For a real search, look for an `agent dependency telemetry` JSON entry. It
contains sanitized `models`, `provider`, `sources`, `source_statuses`,
`provider_latency_ms`, `provider_status`, `data_source`, and `cache_status`
fields. It intentionally excludes prompts, API keys, and raw listing data.

Do not commit `.env`, API keys, downloaded service-account files, or values copied
from Secret Manager.
