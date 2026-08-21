# Web API Contract

> **Stable Reference — change only through a coordinated Frontend + Backend contract change.**

The frontend depends only on this HTTP contract.

## Health

```http
GET /health
```

```json
{"status":"ok"}
```

## Chat

```http
POST /api/chat
Content-Type: application/json
Authorization: Bearer <Firebase-ID-token>
```

Request:

```json
{
  "message": "2B2B under $4,000 in Mountain View",
  "conversationId": "optional-existing-id"
}
```

Response:

```json
{
  "conversationId": "server-created-or-existing-id",
  "message": "Agent response text",
  "listings": [],
  "comparison": null,
  "searchPerformed": true,
  "mode": "adk"
}
```

Each listing may add a `canonicalListing` object using
`kbf.canonical-listing.v1`. Explicit JSON `null` values represent unknown facts
and must not be converted to `false` or guessed values.

## Comparison

```http
POST /api/compare
Authorization: Bearer <Firebase-ID-token>
Content-Type: application/json

{
  "listingIds": ["listing-1", "listing-2"],
  "conversationId": "existing-conversation-id"
}
```

Two to four unique listing IDs are allowed. The backend reuses the verified
user's ADK conversation and returns `kbf.canonical-comparison.v1` in the
`comparison` field of the normal response shape. `message` is Gemini's readable
explanation; the structured comparison tool response is the fact source.

The response's `listings` array contains the selected listings as refreshed by
the Agent's comparison-time detail verification. For example, a policy that was
unknown in the original search snapshot may now be `petsAllowed: true`. The
frontend should merge these selected snapshots into its existing result cards by
listing ID. It should not replace the whole result list, because unselected
search results are intentionally absent from this comparison response.

The backend performs the same merge in conversation persistence: selected
snapshots are refreshed, unselected snapshots remain available, and existing
card-only presentation fields are retained when detail verification does not
return them. This is additive and does not change
`kbf.canonical-comparison.v1`.

`message` is trimmed by the backend, must not be blank, and is limited to 4,000 characters. `conversationId` is optional, limited to 128 characters, and should be returned to the backend on follow-up turns.

Validation failures return HTTP `422`. If the Agent execution path is temporarily unavailable, the backend returns HTTP `502` without exposing provider or runtime internals.

When `AUTH_MODE=firebase`, a missing or invalid Firebase ID token returns HTTP
`401`. A verified user attempting to reuse another user's `conversationId`
returns HTTP `403`. The request body never accepts a user ID; identity comes only
from the verified token.

## Recent Searches

```http
GET /api/conversations?limit=20
Authorization: Bearer <Firebase-ID-token>
```

Returns up to 20 of the verified user's successful conversation metadata records,
newest first by `updatedAt`. The optional `limit` query parameter must be between
1 and 50. The endpoint does not accept a UID or user ID; any user identity comes
exclusively from the verified Firebase bearer token.

```json
{
  "items": [
    {
      "conversationId": "abc123",
      "createdAt": "2026-08-20T18:00:00Z",
      "updatedAt": "2026-08-20T18:15:00Z",
      "turnCount": 4,
      "listings": [],
      "lastCommuteStatus": "available"
    }
  ]
}
```

Each item contains only timestamps, successful turn count, the latest normalized
listing snapshots, and the latest commute status. Full chat transcripts and ADK
event history remain in the separately owned ADK session database and are not
returned by this endpoint.

## Selected Route

```http
POST /api/route
Content-Type: application/json
Authorization: Bearer <Firebase-ID-token>
```

The selected-route request uses an existing `conversationId`. It is protected by
the same verified Firebase identity and cross-user conversation check as chat.

## Shortlist

All shortlist routes require the Firebase ID token when Firebase authentication
is enabled.

```http
GET /api/shortlist
Authorization: Bearer <Firebase-ID-token>
```

Returns the verified user's saved listing snapshots.

```http
POST /api/shortlist
Authorization: Bearer <Firebase-ID-token>
Content-Type: application/json

{
  "listingId": "listing-from-the-latest-response",
  "conversationId": "source-conversation-id"
}
```

The backend loads the listing snapshot from that user's persisted conversation
metadata. It does not trust a listing object supplied by the browser. Success
returns HTTP `201` and the saved item.

```http
DELETE /api/shortlist/{url-encoded-listing-id}
Authorization: Bearer <Firebase-ID-token>
```

Removal is idempotent and returns HTTP `204`.

```http
PATCH /api/shortlist/{url-encoded-listing-id}
Authorization: Bearer <Firebase-ID-token>
Content-Type: application/json

{"note":"Tour on Saturday"}
```

The note is optional, trimmed, and limited to 1,000 characters. Send `null` or
an empty string to clear it.

## Listing

```ts
interface Listing {
  id: string;
  title?: string;
  address?: string;
  price?: number;
  bedrooms?: number;
  bathrooms?: number;
  url?: string;
  score?: number;
  reason?: string;
}
```

The backend may normalize internal Agent fields into this web shape.

## Rules

- `/api/chat` is the primary user interaction endpoint.
- `/api/conversations` may list only lightweight metadata for the verified user.
- `/api/route` may read only the verified user's conversation state.
- `/api/compare` may compare only candidates in the verified user's conversation.
- `/api/shortlist` may read or change only the verified user's shortlist.
- The frontend never reads or writes Firestore directly.
- Frontend does not depend on ADK internals.
- `adk` is the normal real-Agent mode.
- `stub` is explicit development/testing mode only.
- Do not add another endpoint for the same flow without a concrete product need.

## Change Rule

Do not edit this file for UI changes or Agent implementation details. Update it only when the HTTP request/response contract intentionally changes.
