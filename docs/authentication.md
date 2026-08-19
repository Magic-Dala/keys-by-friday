# Firebase Authentication (Milestone 2)

This guide adds a private user identity to the existing browser → FastAPI → ADK
flow. It uses **anonymous Firebase sign-in** for the MVP, so a visitor is signed
in automatically and does not need to create a password.

## What this milestone does

```text
Browser asks Firebase for an anonymous ID token
→ Browser sends: Authorization: Bearer <ID token>
→ FastAPI asks Firebase Admin to verify the token
→ FastAPI reads the verified uid
→ AgentService uses that uid for the ADK session
```

Think of the ID token as a temporary, digitally signed ID card. The browser can
carry the card, but it cannot make a convincing fake because it cannot create
Firebase's signature. The backend never accepts a `userId` from the request
body.

The backend also records which verified `uid` first used each `conversationId`.
The same user can continue that conversation and request its selected commute
route. A different user receives HTTP `403 Forbidden` from either endpoint.

## Important MVP boundary

Milestone 3 now stores conversation ownership and metadata in Firestore when
`PERSISTENCE_MODE=firestore`. The full ADK conversation session is still held in
the backend process, so a Cloud Run restart can preserve ownership/shortlists
without preserving every earlier conversational refinement. See
`docs/firestore.md` for that boundary.

Anonymous identity is also tied to the browser's local Firebase data. Clearing
browser storage, using a different browser, or using another device creates a
new anonymous user. A later Google sign-in feature can give users a durable
cross-device identity without changing backend token verification.

## 1. Check the Mac prerequisites

From Terminal, at the repository root:

```bash
node --version
npm --version
uv --version
gcloud --version
```

Node must be at least `20.9.0`; Node 24 is recommended by this project. If your
Node version is older, install the current Node release from nodejs.org (or with
your preferred version manager), close Terminal, reopen it, and check again.

Install the project dependencies:

```bash
uv sync --extra dev --extra backend
cd frontend
npm install
cd ..
```

`firebase-admin` is the trusted server library. `firebase` is the browser
library. They have different responsibilities and must not be swapped.

## 2. Add Firebase to the existing Google Cloud project

Do **not** create a separate Google Cloud project for this milestone.

1. Open the Firebase Console at <https://console.firebase.google.com/>.
2. Choose **Add project**.
3. Select the Google Cloud project already used in Milestone 1.
4. Finish the Firebase setup. Google Analytics is optional for this MVP.

Firebase is being added as a service on the existing project; this does not
replace Cloud Run, Secret Manager, or the existing project configuration.

## 3. Register the frontend as a Firebase web app

1. In Firebase Console, open **Project settings → General**.
2. Under **Your apps**, choose the Web icon (`</>`).
3. Give it a name such as `keys-by-friday-web`.
4. Firebase Hosting is not required for this step.
5. Register the app and keep the displayed `firebaseConfig` values nearby.

The web values such as `apiKey`, `authDomain`, `projectId`, and `appId` identify
the Firebase project. They are designed to be included in browser code; they do
not replace backend authorization checks.

## 4. Enable anonymous sign-in

1. In Firebase Console, open **Build → Authentication**.
2. Choose **Get started** if Authentication has not been initialized.
3. Open **Sign-in method**.
4. Select **Anonymous**, enable it, and save.

If this provider is not enabled, the browser will show the safe message
"Couldn't sign you in" and no chat request will be sent.

## 5. Configure the backend

In the repository-root `.env` file, add or update:

```dotenv
AUTH_MODE=firebase
FIREBASE_PROJECT_ID=your-existing-google-cloud-project-id
```

Do not put the Firebase web API key in the root backend `.env`; it belongs in
the frontend file in the next step.

For local Firebase Admin credentials on macOS, run:

```bash
gcloud config set project 'your-existing-google-cloud-project-id'
gcloud auth application-default login
```

The second command opens a Google login page and creates local Application
Default Credentials. Do not download or commit a service-account JSON key.

## 6. Configure the frontend

Create or update `frontend/.env.local`:

```dotenv
NEXT_PUBLIC_BACKEND_URL=http://localhost:8000
NEXT_PUBLIC_AUTH_MODE=firebase
NEXT_PUBLIC_FIREBASE_API_KEY=copy-apiKey-from-firebaseConfig
NEXT_PUBLIC_FIREBASE_AUTH_DOMAIN=copy-authDomain-from-firebaseConfig
NEXT_PUBLIC_FIREBASE_PROJECT_ID=copy-projectId-from-firebaseConfig
NEXT_PUBLIC_FIREBASE_APP_ID=copy-appId-from-firebaseConfig
```

Next.js reads `NEXT_PUBLIC_*` settings when it starts/builds. Restart the
frontend after changing this file.

## 7. Start and test the full app

From the repository root:

```bash
./kbf start
```

Open <http://localhost:3000> and send:

```text
Find a 2-bedroom apartment in Mountain View under $4,000.
```

The desired result is:

- the UI sends the message normally;
- `POST /api/chat` returns HTTP `200`;
- the response contains a `conversationId`;
- a follow-up such as "I also need parking" keeps the same conversation;
- Firebase Console → Authentication → Users shows an anonymous user.

To inspect the request in Chrome:

1. Open **View → Developer → Developer Tools**.
2. Select **Network**.
3. Send another chat message.
4. Select the `/api/chat` request, then **Headers**.
5. Under Request Headers, confirm that `Authorization` starts with `Bearer`.

Treat the full token as temporary private data: do not paste it into chat,
screenshots, documentation, or Git.

## 8. Test backend rejection without a token

With the backend running in Firebase mode, open a second Terminal:

```bash
curl -i \
  -H 'Content-Type: application/json' \
  -d '{"message":"Find a rental"}' \
  http://localhost:8000/api/chat
```

Desired output:

```text
HTTP/1.1 401 Unauthorized
...
{"detail":"A valid sign-in token is required."}
```

This proves that FastAPI rejects a missing Firebase identity in local testing.
It does not by itself make an internet-facing paid API safe from repeated calls.

## 9. Run the automatic security tests

These tests use fake users named `user-a` and `user-b`; they do not call
Firebase or use cloud quota:

```bash
uv run --extra dev --extra backend pytest backend/tests/test_auth.py -q
```

Desired output ends with:

```text
9 passed
```

The most important test does this:

```text
user-a starts conversation C → 200
user-a continues conversation C → 200
user-b tries conversation C → 403
```

Run the complete project checks too:

```bash
uv run --extra dev --extra backend pytest backend/tests tests -q
uv run python -m compileall backend rental_agent -q

cd frontend
npm run check
cd ..
```

## 10. Cloud Run configuration

Cloud Run uses the attached service account through Application Default
Credentials. Add these variables to the Milestone 1 deployment command:

```text
AUTH_MODE=firebase
FIREBASE_PROJECT_ID=${KBF_PROJECT_ID}
```

Keep the Cloud Run service private with `--no-allow-unauthenticated` for this
milestone. Firebase authentication isolates users and conversations, but
anonymous Firebase identities do not rate-limit aggregate Gemini, RealtyAPI, or
Routes spending. The deployment guide grants selected developers the Cloud Run
Invoker role and shows how to test both the Cloud Run IAM and Firebase layers.

As a deployment guardrail, `APP_ENV=production` with `AUTH_MODE=disabled` makes
`/ready` fail and makes `/api/chat` return HTTP `503`. This prevents a missing
environment variable from silently exposing a shared production identity.

The current browser frontend calls FastAPI directly, so it cannot use a private
Cloud Run URL as `NEXT_PUBLIC_BACKEND_URL`. Continue browser end-to-end testing
against the local backend. Before hosting the browser flow, add an approved
server-side edge and distributed per-user plus aggregate abuse controls; do not
make Cloud Run public based on Firebase authentication alone.

## Common problems

| Symptom | Meaning | What to check |
|---|---|---|
| UI says it could not sign in | Browser could not get a Firebase token | Anonymous provider and `frontend/.env.local` values |
| `/api/chat` returns 401 | Token missing, expired, forged, or for another Firebase project | Frontend/backend project IDs and Authorization header |
| `/api/chat` returns 503 | Backend Firebase configuration is unavailable | `AUTH_MODE`, `FIREBASE_PROJECT_ID`, and local ADC |
| `/api/chat` returns 403 | Conversation belongs to another verified uid | Start a new conversation for the current user |
| Direct Cloud Run URL returns 401/403 | Cloud Run IAM rejected a caller without Invoker credentials | Private deployment is working; use the deployment guide's identity-token test |
| Browser reports a CORS error | Origin or allowed headers do not match | `FRONTEND_ORIGIN` and restart backend |
| `npm run check` rejects Node | Installed Node is too old | Install Node 20.9+; Node 24 recommended |

## Adding Google sign-in later

Firebase tokens have the same backend verification path regardless of whether
the provider is anonymous or Google. To add Google sign-in later, enable the
Google provider and change the frontend sign-in experience. The backend should
continue verifying the token and using only its verified `uid`.
