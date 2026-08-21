# Comparison and Shortlist (Milestone 5)

This guide explains the structured comparison and complete shortlist CRUD flow,
including macOS setup and testing.

## What changed

Before Milestone 5, the browser's comparison panel placed a few card fields next
to each other. It did not ask the Agent's deterministic comparison tool for hard
constraint status, evidence, or unknowns. The backend also converted the Agent's
rich canonical listing into a smaller card shape and discarded the canonical
object.

After Milestone 5:

```text
User selects 2–3 current listings
→ POST /api/compare with listing IDs + conversation ID
→ FastAPI verifies the Firebase user owns the conversation
→ the existing ADK Agent calls compare_candidates()
→ deterministic code produces kbf.canonical-comparison.v1 facts
→ Gemini explains those facts without becoming their source
→ FastAPI returns refreshed selected listings and the structured comparison
→ FastAPI merges those selected snapshots into the stored full result list
→ Next.js displays facts, evidence, trade-offs, unknowns, and the explanation
```

`rental_agent/**` was not changed. The backend adapts the existing structured
Agent tool output to the agreed web contract.

## Easy mental model

Think of a home inspector and a tour guide:

- Deterministic Python is the **inspector**. It records facts such as rent,
  bedrooms, whether a hard requirement passes, and what is still unknown.
- Gemini is the **tour guide**. It explains the inspector's report in natural
  language.
- Gemini is not allowed to write new facts into the inspector's report.

For example, if parking is absent from provider evidence, the structured result
contains `policies.parkingAvailable` under `comparisonUnknowns`. Gemini may say
"parking still needs verification," but it may not turn that unknown into "yes."

## Additive canonical listing contract

Every normalized web listing can now include:

```json
{
  "id": "listing-1",
  "price": 3180,
  "canonicalListing": {
    "schemaVersion": "kbf.canonical-listing.v1",
    "identity": {"id": "listing-1"},
    "pricing": {"rent": 3180, "rentMin": null, "rentMax": null},
    "policies": {"petsAllowed": null, "parkingAvailable": true},
    "evidence": {"detailVerified": false},
    "completeness": {
      "unknownFields": ["policies.petsAllowed"],
      "decisionReady": false
    }
  }
}
```

The original card fields remain. Adding `canonicalListing` is therefore an
additive change: old clients can ignore it, while new clients can use it.

`null` has an important meaning: the source did not establish the fact. It is
not the same as `false`. For example:

- `petsAllowed: true` means the available evidence says pets are allowed.
- `petsAllowed: false` means the evidence says pets are not allowed.
- `petsAllowed: null` means the answer is unknown.

The backend models allow future extra fields inside V1 and preserve them. An
existing field may not be renamed or given a different meaning. A breaking
change requires `kbf.canonical-listing.v2`.

## Structured comparison contract

`POST /api/compare` returns the ordinary Agent message and a separate comparison:

```json
{
  "conversationId": "conversation-1",
  "message": "Option one is cheaper, but parking still needs verification.",
  "listings": [
    {
      "id": "one",
      "canonicalListing": {
        "schemaVersion": "kbf.canonical-listing.v1",
        "identity": {"id": "one"},
        "location": {},
        "pricing": {},
        "property": {},
        "availability": {},
        "policies": {"petsAllowed": true},
        "features": {},
        "media": {},
        "contact": {},
        "source": {},
        "evidence": {"detailVerified": true},
        "completeness": {}
      }
    }
  ],
  "comparison": {
    "schemaVersion": "kbf.canonical-comparison.v1",
    "listingIds": ["one", "two"],
    "results": [
      {
        "listingId": "one",
        "hardConstraintStatus": "pass",
        "satisfiesCurrentRequirements": true,
        "softPreferenceEvidence": [],
        "tradeoffs": [],
        "comparisonUnknowns": [],
        "decisionUnknowns": [],
        "decisionReady": true,
        "score": 90,
        "rank": 1
      }
    ]
  },
  "searchPerformed": false,
  "mode": "adk"
}
```

The backend reads the `compare_candidates` function response. It never parses
the Agent's prose to recover facts. The same structured input produces the same
normalized comparison output.

`searchPerformed: false` tells the frontend that this turn was a comparison,
not a replacement search. The comparison response's `listings` contains only
the selected candidates refreshed during detail verification. The frontend
merges them into its current cards by `id` instead of replacing all cards.

The backend also performs that merge before updating Firestore. For example, if
a search produced listings A, B, and C but the user compares A and B, verified
fields for A and B are updated while C remains in `lastListings`. Card fields
such as rank, score, source postings, and commute are retained when the detail
response does not repeat them.

## Firestore persistence

The existing documents are extended, not replaced:

```text
conversations/{hashed-conversation-id}
  lastListings[]             includes canonicalListing when available
  lastComparison             kbf.canonical-comparison.v1 object

users/{hashed-firebase-uid}/shortlist/{hashed-listing-id}
  listingSnapshot            includes canonicalListing when available
  note                       string or null
```

No composite Firestore index is needed. The existing shortlist query still
orders only one user's subcollection by `savedAt`.

## Shortlist CRUD

CRUD means Create, Read, Update, Delete:

| Operation | HTTP route | Meaning |
|---|---|---|
| Create | `POST /api/shortlist` | Save a trusted server-side listing snapshot |
| Read | `GET /api/shortlist` | Load the signed-in user's saved homes |
| Update | `PATCH /api/shortlist/{listingId}` | Add, replace, or clear a note |
| Delete | `DELETE /api/shortlist/{listingId}` | Remove a saved home |

The browser still does not send a listing object to Firestore. The backend finds
the listing in conversation metadata, which prevents a browser from changing a
real `$3,800` rent to `$800` before saving it.

## Automated tests on macOS

From Terminal, open the repository root:

```bash
cd /Users/ayushiiamin/Documents/keys-by-friday
```

Install/refresh dependencies if needed:

```bash
uv sync --extra dev --extra backend
cd frontend
npm install
cd ..
```

Run the focused Milestone 5 backend tests:

```bash
uv run pytest backend/tests/test_api.py backend/tests/test_persistence.py backend/tests/test_firestore_adapter.py -q
```

Desired result: all tests pass. These tests use memory/fake Firestore, so they do
not consume Gemini, RealtyAPI, Maps, or Firestore quota.

Run the frontend comparison test:

```bash
cd frontend
npm test -- --run components/rental-search.test.tsx
cd ..
```

Then run the complete repository checks used before a pull request:

```bash
uv run pytest backend/tests tests -q
uv run python -m compileall backend rental_agent -q
cd frontend
npm run check
cd ..
```

## Manual browser test on macOS

Start the product from the repository root:

```bash
./kbf start
```

Open `http://localhost:3000`, then:

1. Search for: `2 bedroom under $4,000 in Mountain View with parking`.
2. Select **Compare** on two result cards.
3. Click **Compare homes**.
4. Confirm the panel shows a hard-requirement status for each home.
5. Confirm missing facts appear under **Still unknown** rather than as yes/no.
6. Confirm the **Agent explanation** appears separately above the fact columns.
7. Save a result, refresh the browser, and confirm it remains in the shortlist
   when Firestore persistence is enabled.

Also open `http://localhost:8000/docs`. The generated API page should list:

- `POST /api/compare`
- `GET /api/shortlist`
- `POST /api/shortlist`
- `PATCH /api/shortlist/{listing_id}`
- `DELETE /api/shortlist/{listing_id}`

## What good output looks like

A correct comparison has three separate layers:

1. Card/canonical facts such as rent and bathrooms.
2. Deterministic result fields such as `hardConstraintStatus`, evidence, and
   explicit unknowns.
3. Gemini's readable explanation of those structured facts.

A wrong result would claim `petsAllowed: true` when the canonical listing says
`null`, hide a hard-constraint failure, or create comparison facts by extracting
them from the Gemini paragraph.
