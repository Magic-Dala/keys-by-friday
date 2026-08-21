# Anonymous Search Rate Limits

This guide explains the backend cost guard for Firebase anonymous users.

## What problem this solves

Every Agent turn can spend Gemini tokens and may call RealtyAPI. Without a
limit, one anonymous browser could repeatedly send requests and consume the
team's hackathon quota.

The default policy is:

```text
10 Agent-backed requests
per Firebase anonymous uid
per 3,600 seconds (one hour)
```

`POST /api/chat` and `POST /api/compare` use the same allowance. A search,
follow-up refinement, or comparison can all call Gemini, so they all count.
`POST /api/route` is not part of this bucket because it has a different Maps
cost boundary.

Google or another non-anonymous sign-in provider bypasses this particular
anonymous-user limit. Project quotas and abuse controls should still apply to
all users.

## Easy example

Imagine an anonymous user has a limit of three:

```text
1. "Find Mountain View rentals"  → allowed, 2 remaining
2. "I also need parking"         → allowed, 1 remaining
3. Compare two homes             → allowed, 0 remaining
4. "Lower my budget"             → HTTP 429, Agent does not run
```

After the configured window resets, the user receives a new allowance.

## Why Firestore is used in production

Cloud Run may start several backend instances:

```text
Browser
  ├→ Cloud Run instance A
  └→ Cloud Run instance B
          ↓
      one Firestore counter
```

If each instance used its own Python dictionary, a user could receive ten calls
from instance A and another ten from instance B. A Firestore transaction makes
all instances update the same counter atomically.

Memory storage is still used locally and in automated tests. Production
readiness already requires Firestore, so production rate limits are distributed.

## Request behavior

An accepted anonymous request includes:

```text
X-RateLimit-Limit: 10
X-RateLimit-Remaining: 9
X-RateLimit-Reset: 1787245200
```

`X-RateLimit-Reset` is a Unix timestamp. When no allowance remains:

```http
HTTP/1.1 429 Too Many Requests
Retry-After: 1842
X-RateLimit-Limit: 10
X-RateLimit-Remaining: 0
```

The check runs after FastAPI validates the request body but before Agent
execution. A malformed request returning HTTP 422 does not consume allowance.
An accepted request does consume allowance even if Gemini or RealtyAPI later
fails, because external work may already have cost money.

If Firestore cannot check the counter, anonymous Agent requests fail closed with
HTTP 503. This avoids turning a storage outage into unlimited external spend.
Non-anonymous users do not depend on this anonymous counter.

## Configuration

Add these values to the backend environment:

```dotenv
ANONYMOUS_SEARCH_RATE_LIMIT=10
ANONYMOUS_SEARCH_RATE_WINDOW_SECONDS=3600
```

Both values must be positive whole numbers. Changing them does not require a
code change.

For a quick local test, temporarily use:

```dotenv
ANONYMOUS_SEARCH_RATE_LIMIT=2
ANONYMOUS_SEARCH_RATE_WINDOW_SECONDS=300
```

Restart the backend after changing `.env`, because settings are loaded at
process startup.

## Automated testing on macOS

From the repository root:

```bash
cd /Users/ayushiiamin/Documents/keys-by-friday
uv run pytest backend/tests/test_rate_limit.py backend/tests/test_firestore_adapter.py -q
```

These tests verify:

- the Agent is not called after the limit;
- chat and comparison share a bucket;
- invalid requests do not consume allowance;
- signed-in non-anonymous users bypass the anonymous limit;
- storage errors fail closed;
- simultaneous requests cannot exceed the allowance;
- separate Firestore repository objects share the same counter;
- windows reset at the expected time.

The tests use memory/fake Firestore and consume no Gemini, RealtyAPI, Maps, or
Firestore quota.

## Manual browser test on macOS

1. Set the temporary limit of two shown above.
2. Start the product with `./kbf start`.
3. Open `http://localhost:3000` in a browser using anonymous Firebase sign-in.
4. Send two valid Agent messages. Both should work.
5. Send a third message. It should show the stable HTTP 429 detail and should
   not reach the Agent.
6. In browser Developer Tools, open **Network**, select the request, and inspect
   the `X-RateLimit-*` response headers.
7. Restore the desired production values and restart the backend.

With Firestore enabled, the Firebase Console should show a `rateLimits`
collection. Document IDs and `subjectHash` are one-way hashes; plaintext
Firebase UIDs are not stored there.

## Important limitation

Firebase anonymous identity is stored in the browser. A determined user can
clear browser data and receive a new UID, creating a new per-uid allowance.
Therefore this limiter is one layer, not complete public-internet protection.

Before broad public access, also configure:

- Gemini/Vertex AI project quotas and budgets;
- RealtyAPI quotas or provider-side caps;
- an aggregate application cost/request ceiling;
- edge/IP/device abuse controls where appropriate;
- monitoring and alerts for unusual request volume.
