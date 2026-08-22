# Agent Request Rate Limits

This guide explains the backend cost guard for Firebase users.

## What problem this solves

Every Agent turn can spend Gemini tokens and may call RealtyAPI. Without a
limit, one browser or signed-in account could repeatedly send requests and
consume the team's hackathon quota.

The default policy is:

```text
Firebase anonymous uid  → 10 Agent-backed requests per 3,600 seconds (one hour)
Signed-in Firebase uid  → 30 Agent-backed requests per 86,400 seconds (one day)
```

`POST /api/chat` and `POST /api/compare` use the same allowance for a given
user and identity class. A search, follow-up refinement, or comparison can all
call Gemini, so they all count. `POST /api/route` is not part of this bucket
because it has a different Maps cost boundary.

`AUTH_MODE=disabled` is a local-development mode and bypasses this external cost
guard. Production authentication already rejects that mode.

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

If each instance used its own Python dictionary, the same user could receive a
fresh allowance from each instance. A Firestore transaction makes all instances
update the same counter atomically.

Memory storage is still used locally and in automated tests. In production, both
readiness and the request path require distributed Firestore-backed rate-limit
storage; a misconfigured memory store fails closed before Agent execution.

## Request behavior

An accepted limited request includes:

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

If Firestore cannot create or update the counter, Firebase Agent requests fail
closed with HTTP 503. This avoids turning a storage outage or production
misconfiguration into unlimited external spend.

## Configuration

Add these values to the backend environment:

```dotenv
ANONYMOUS_SEARCH_RATE_LIMIT=10
ANONYMOUS_SEARCH_RATE_WINDOW_SECONDS=3600
AUTHENTICATED_SEARCH_RATE_LIMIT=30
AUTHENTICATED_SEARCH_RATE_WINDOW_SECONDS=86400
```

All values must be positive whole numbers. Changing them does not require a code
change.

For a quick local Firebase test, temporarily use small values for the relevant
identity class. Restart the backend after changing `.env`, because settings are
loaded at process startup.

## Automated testing

From the repository root:

```bash
uv run pytest backend/tests/test_rate_limit.py backend/tests/test_firestore_adapter.py -q
```

These tests verify:

- the Agent is not called after the limit;
- chat and comparison share a bucket;
- invalid requests do not consume allowance;
- anonymous and signed-in users each have bounded policies;
- local disabled-auth development remains unblocked;
- storage errors and production memory-store misconfiguration fail closed;
- simultaneous requests cannot exceed the allowance;
- separate Firestore repository objects share the same counter;
- windows reset at the expected time.

The tests use memory/fake Firestore and consume no Gemini, RealtyAPI, Maps, or
Firestore quota.

## Manual browser test

1. Temporarily lower the anonymous limit in `.env`.
2. Start the product with `./kbf start`.
3. Open the frontend in a browser using anonymous Firebase sign-in.
4. Send valid Agent messages until the configured allowance is exhausted.
5. The next request should return stable HTTP 429 detail and must not reach the
   Agent.
6. In browser Developer Tools, inspect the `X-RateLimit-*` and `Retry-After`
   response headers.
7. Restore the desired production values and restart the backend.

With Firestore enabled, the Firebase Console should show a `rateLimits`
collection. Document IDs and `subjectHash` are one-way hashes; plaintext
Firebase UIDs are not stored there.

## Agent-side search cost guardrails

The Agent also bounds each search workflow to at most 20 retained source
postings. Session caches are capped to the same size, and normal single-property
detail questions instruct the Agent to issue at most one detail lookup. Selected
multi-property comparisons use the existing bounded comparison tool instead of
unbounded repeated detail calls.

These guards reduce provider and model-context amplification, but they do not
count individual Gemini invocations or tokens.

## Important limitation

Firebase anonymous identity is stored in the browser. A determined user can
clear browser data and receive a new UID, creating a new per-uid allowance.
Therefore this limiter is one layer, not complete public-internet protection.

Before broad public access, also configure:

- Gemini/Vertex AI project quotas and budgets;
- RealtyAPI quotas or provider-side caps;
- an aggregate application cost/request ceiling;
- a separate request/cost boundary for Google Routes;
- edge/IP/device abuse controls where appropriate;
- monitoring and alerts for unusual request volume.
