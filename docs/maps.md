# Google Routes and Commute Intelligence

This guide explains the Maps/commute boundary merged in PR #7 and how it works
together with the Milestone 1 Cloud Run backend and Milestone 2 Firebase
identity.

## What is implemented

```text
User: "2B2B under $4,000 within 25 minutes of Google Mountain View by car"
  ↓
Gemini identifies the rental and commute requirements
  ↓
Rental provider returns listings with latitude/longitude
  ↓
Google Compute Route Matrix returns one commute result per listing
  ↓
Python removes listings that fail the hard 25-minute limit
  ↓
FastAPI returns structured listing + commute data
```

The broad search uses **Compute Route Matrix** because it can evaluate many
listing origins against one destination efficiently. A selected listing uses
**Compute Routes** through `POST /api/route` because that response can include
the encoded route polyline needed by a map UI.

This responsibility split is deliberate:

- Gemini understands phrases such as "within 25 minutes of work".
- Google Routes supplies measured duration and distance evidence.
- Python applies the hard maximum. Gemini does not invent or override it.

## Vertex AI, Maps, and Google Cloud credits

Vertex AI and Google Maps Platform can use the same Google Cloud project and
billing account, but they use different credentials:

```text
Gemini through Vertex AI → local Google login or Cloud Run service account
Google Routes API       → GOOGLE_MAPS_API_KEY
Billing                 → the Google Cloud project connected to both
```

Think of billing credits as the money in the project's wallet and credentials
as the keys that open individual services. Having Vertex AI credentials does
not automatically create a Maps key.

For local Vertex AI development, the root `.env` should contain:

```dotenv
GOOGLE_GENAI_USE_VERTEXAI=TRUE
GOOGLE_CLOUD_PROJECT=your-google-cloud-project-id
GOOGLE_CLOUD_LOCATION=global
GOOGLE_API_KEY=
GEMINI_API_KEY=
```

Run `gcloud auth application-default login` once on the Mac so the local Python
process can use your developer identity. Cloud Run uses its attached
`kbf-backend` service account instead and needs the `Vertex AI User` role.

An eligible Google Cloud Free Trial credit can pay for Google Maps Platform
usage when Maps uses the same billing account. Promotional or hackathon credits
can have different restrictions, so confirm the credit's applicable products
under **Google Cloud Console → Billing → Credits**.

## Important behavior

### A normal rental search does not require Maps

If the user does not request a commute constraint, the Agent does not call the
commute service. Missing `GOOGLE_MAPS_API_KEY` therefore does not break ordinary
searches.

### A hard commute request must be complete

The Agent needs all three values:

```text
destination: Google Mountain View
maximum:     25 minutes
mode:        DRIVE
```

For example, "within 25 minutes of work" is incomplete if the destination and
travel mode are unknown. The Agent should ask a follow-up before calling the
rental provider.

### Unknown is not a passing result

If coordinates are missing or Google Routes is unavailable, the commute status
is `unknown` or `unavailable`. A listing with unknown commute evidence cannot
pass a hard 25-minute constraint.

This is similar to checking a rental's pet policy: "not provided" must not be
treated as "pets allowed."

## How Maps and Firebase work together

Both map-related HTTP flows use the same verified Firebase user:

```text
POST /api/chat  → creates/continues user-a's ADK conversation
POST /api/route → reads route state only from user-a's conversation
```

If `user-b` sends `user-a`'s `conversationId` to either endpoint, FastAPI
returns HTTP `403`. The frontend sends a Firebase bearer token to both calls.

## 1. Enable the Routes API on Google Cloud

From the repository root on macOS:

```bash
export KBF_PROJECT_ID='your-existing-google-cloud-project-id'
gcloud config set project "$KBF_PROJECT_ID"
gcloud services enable routes.googleapis.com
```

Use the same Google Cloud project as Cloud Run and Firebase.
The Routes API requires billing on the project. In Google Cloud Console, set a
small quota that fits the hackathon budget before running public demos.

Maps is pay-as-you-go. Compute Route Matrix usage is measured per matrix element:
`origins × destinations`. For example, checking 25 rental listings against one
workplace consumes 25 elements, not one. The current code requests
`TRAFFIC_AWARE` driving data, so watch the applicable Routes Pro SKU in Billing
reports. A budget alert warns you but does not stop requests; a quota is the
control that limits API consumption.

## 2. Create a server-side API key

In Google Cloud Console:

1. Open **APIs & Services → Credentials**.
2. Choose **Create credentials → API key**.
3. Edit the key.
4. Under **API restrictions**, select **Restrict key**.
5. Allow only **Routes API**.
6. Save.

The current backend calls Google Routes from Cloud Run, so this key belongs in
the backend environment. Do not add it to a `NEXT_PUBLIC_*` frontend variable.
Do not commit it to Git.

Google recommends both API and application restrictions. API restriction to
Routes is always appropriate here. A default Cloud Run service does not have a
stable outbound IP, so add an IP application restriction only after configuring
static egress; do not guess an IP that would break production requests.

## 3. Configure local development

Add the key to the ignored repository-root `.env`:

```dotenv
GOOGLE_MAPS_API_KEY=your-restricted-routes-api-key
```

Restart the backend after changing `.env`. `get_commute_service()` is cached, so
a running process will not notice a newly added key until it restarts.

## 4. Run the fake integration tests

These tests use fake HTTP responses and do not spend Maps quota:

```bash
uv run --extra dev --extra backend pytest tests/test_commute.py backend/tests/test_api.py backend/tests/test_auth.py -q
```

They verify, among other things:

- route-matrix duration and distance normalization;
- `DRIVE` uses `TRAFFIC_AWARE`;
- invalid coordinates never reach Google;
- requests are chunked at 100 origins;
- unknown commute evidence does not pass a hard limit;
- map data reaches the shared frontend contract;
- another Firebase user cannot request a selected route.

Run the full suite before opening or updating a PR:

```bash
uv run --extra dev --extra backend pytest backend/tests tests -q
uv run python -m compileall backend rental_agent -q

cd frontend
npm run check
cd ..
```

## 5. Run a live local smoke test

Start the full app:

```bash
./kbf start
```

Open <http://localhost:3000> and try this exact prompt:

```text
Find a 2-bedroom apartment under $4,000 in Mountain View within 25 minutes of
Google Mountain View by car.
```

Desired behavior:

- the request succeeds and preserves the Firebase-authenticated conversation;
- the structured response contains listing `latitude` and `longitude` when the
  provider supplied valid coordinates;
- matching listings contain `commute.status: "available"`;
- available commutes contain `durationMinutes` and `distanceMeters`;
- the aggregate `commuteEvaluation` reports evaluated/available/within-limit
  counts;
- a listing over 25 minutes does not survive the hard filter;
- the Agent does not guess a commute when Google cannot provide one.

In Chrome, inspect **Developer Tools → Network → `/api/chat` → Response**. A
successful listing may resemble:

```json
{
  "id": "listing-123",
  "latitude": 37.4,
  "longitude": -122.1,
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

The exact time, distance, listings, and counts will change with real data. Test
the presence and meaning of the fields rather than expecting the example
numbers.

For an Agent-driven geometry check before a map UI is connected, follow up in
the same conversation with:

```text
Show me the route details for the first listing.
```

If the Agent calls its selected-route tool, the `/api/chat` response's top-level
`route` field should contain `status: "available"` and an `encodedPolyline`.

## 6. Test selected-route geometry

After a successful commute search, a frontend map component can call:

```http
POST /api/route
Authorization: Bearer <Firebase-ID-token>
Content-Type: application/json
```

```json
{
  "listingId": "listing-123",
  "conversationId": "the-current-conversation-id"
}
```

A successful live response has:

```json
{
  "listingId": "listing-123",
  "destination": "Google Mountain View",
  "mode": "DRIVE",
  "durationMinutes": 18,
  "distanceMeters": 12400,
  "status": "available",
  "routingPreference": "TRAFFIC_AWARE",
  "encodedPolyline": "..."
}
```

`encodedPolyline` is compact route geometry. It is not a map image; a frontend
map component decodes it and draws the path.

## 7. Configure Cloud Run securely

Store the key in Secret Manager instead of putting it directly in a deployment
command:

```bash
read -s -p 'Google Maps Routes API key: ' KBF_SECRET_VALUE; echo
printf '%s' "$KBF_SECRET_VALUE" | \
  gcloud secrets create kbf-google-maps-api-key --data-file=-
unset KBF_SECRET_VALUE

gcloud secrets add-iam-policy-binding kbf-google-maps-api-key \
  --member="serviceAccount:${KBF_SERVICE_ACCOUNT}" \
  --role='roles/secretmanager.secretAccessor'
```

Attach it during deployment:

```text
GOOGLE_MAPS_API_KEY=kbf-google-maps-api-key:1
```

The full command is in `docs/deployment.md`.

## Common results and what they mean

| Result | Meaning | Next check |
|---|---|---|
| Normal search works, commute is `unavailable` | Maps key missing, rejected, or Routes call failed | `.env`, key restriction, API enabled, billing/quota |
| Commute is `unknown` | Required input or valid coordinates/evidence are missing | destination, mode, listing coordinates |
| No listings after commute filter | Known results exceeded the hard limit, or none had passing evidence | relax the limit and inspect `commuteEvaluation` |
| `/api/route` returns 401 | Firebase token is missing/invalid | frontend auth configuration and request header |
| `/api/route` returns 403 | Conversation belongs to another Firebase user | use the current user's conversation ID |
| Route is available but no polyline | Google returned summary evidence without usable geometry | inspect live Routes response/logs |

## Current boundaries

- PR #7 added the backend/Agent contract, not a frontend map component.
- Places API is not enabled by this integration.
- Natural-language destination resolution needs a live smoke test.
- Commute state is held in the current in-memory ADK session.
- Routes calls use billable Google Cloud quota; use fake tests for routine CI.
- Route Matrix billing is per origin/destination element. This project uses one
  destination, so 25 listing origins produce 25 billed matrix elements.
- `DRIVE` uses `TRAFFIC_AWARE`, which Google bills as an advanced Routes feature;
  configure quotas and monitor usage before a public demo.
