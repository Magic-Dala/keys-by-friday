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

To test the real Agent, configure the root `.env` file and use:

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
  secretmanager.googleapis.com
```

Create a dedicated identity for the backend:

```bash
gcloud iam service-accounts create kbf-backend \
  --display-name='Keys by Friday backend'
```

## Store API keys in Secret Manager

Read each key without showing it in the Terminal, create the secret, and clear
the temporary shell variable:

```bash
read -s -p 'Google API key: ' KBF_SECRET_VALUE; echo
printf '%s' "$KBF_SECRET_VALUE" | \
  gcloud secrets create kbf-google-api-key --data-file=-
unset KBF_SECRET_VALUE

read -s -p 'RealtyAPI key: ' KBF_SECRET_VALUE; echo
printf '%s' "$KBF_SECRET_VALUE" | \
  gcloud secrets create kbf-realtyapi-key --data-file=-
unset KBF_SECRET_VALUE
```

Allow only the backend service account to read those secrets:

```bash
gcloud secrets add-iam-policy-binding kbf-google-api-key \
  --member="serviceAccount:${KBF_SERVICE_ACCOUNT}" \
  --role='roles/secretmanager.secretAccessor'

gcloud secrets add-iam-policy-binding kbf-realtyapi-key \
  --member="serviceAccount:${KBF_SERVICE_ACCOUNT}" \
  --role='roles/secretmanager.secretAccessor'
```

## Deploy to Cloud Run

From the repository root:

```bash
gcloud run deploy "$KBF_SERVICE" \
  --source . \
  --project "$KBF_PROJECT_ID" \
  --region "$KBF_REGION" \
  --service-account "$KBF_SERVICE_ACCOUNT" \
  --allow-unauthenticated \
  --port 8080 \
  --cpu 1 \
  --memory 1Gi \
  --concurrency 8 \
  --min-instances 0 \
  --max-instances 1 \
  --timeout 180 \
  --set-env-vars "APP_ENV=production,AGENT_MODE=adk,LISTING_PROVIDER=realtyapi,GOOGLE_GENAI_USE_VERTEXAI=FALSE,GEMINI_MODELS=gemini-3.5-flash-lite,AGENT_TIMEOUT_SECONDS=120,LOG_LEVEL=INFO,GOOGLE_CLOUD_PROJECT=${KBF_PROJECT_ID},FRONTEND_ORIGIN=${KBF_FRONTEND_ORIGIN}" \
  --set-secrets 'GOOGLE_API_KEY=kbf-google-api-key:1,REALTYAPI_API_KEY=kbf-realtyapi-key:1'
```

`max-instances=1` reduces the chance that an in-memory conversation is split
across instances. It does not make sessions durable: a restart or scale-to-zero
event still removes current ADK session state. Persistent sessions are a later
milestone.

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

Test health and readiness:

```bash
curl -i "$KBF_BACKEND_URL/health"
curl -i "$KBF_BACKEND_URL/ready"
```

Test a real rental search:

```bash
curl -i \
  -H 'Content-Type: application/json' \
  -H 'X-Request-ID: cloud-smoke-test' \
  -d '{"message":"2B2B under $4,000 in Mountain View"}' \
  "$KBF_BACKEND_URL/api/chat"
```

Copy the returned `conversationId` into a follow-up request:

```bash
curl -i \
  -H 'Content-Type: application/json' \
  -d '{"message":"I also need parking","conversationId":"PASTE_ID_HERE"}' \
  "$KBF_BACKEND_URL/api/chat"
```

View recent application and platform logs:

```bash
gcloud run services logs read "$KBF_SERVICE" \
  --project "$KBF_PROJECT_ID" \
  --region "$KBF_REGION" \
  --limit 50
```

Do not commit `.env`, API keys, downloaded service-account files, or values copied
from Secret Manager.
