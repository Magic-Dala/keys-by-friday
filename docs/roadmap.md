# Roadmap

> **Document type: Living Document**  
> This file is expected to change as priorities move. Stable architecture and API rules belong in the Stable Reference documents.

## Product Direction

The target product loop is:

> **Find → Verify → Understand → Rank → Decide**

Current Hackathon priority order:

```text
Phase 1  Web integration                 ✅ Baseline complete
Phase 2  Structured API listings[]       ✅ Baseline complete
Phase 3  Frontend rental-result UX       🔄 Foundation complete; product polish next
Phase 4  Commute / Maps evidence         🔄 Backend/API complete; live setup/UI pending
Phase 5  Comparison + Shortlist          ⬜ Planned
Phase 6  Demo polish + deployment        ⬜ Planned
```

The immediate goal is to strengthen the existing vertical slice, not add orchestration frameworks.

## Phase 2 — Structured API Results

Normalize source-backed Agent search / verification state into the `/api/chat` `listings[]` response so the frontend can render rental cards without parsing arbitrary prose.

## Phase 3 — Frontend Rental UX

Build listing cards, source links, recommendation / tradeoff presentation, loading and error states, and follow-up conversation on the stable `/api/chat` contract.

## Phase 4 — Commute / Maps Evidence

The Google Routes boundary, deterministic commute filtering, map coordinates,
and selected-route API are implemented. Remaining work is live-key validation,
frontend presentation, and deciding whether natural-language destinations need
a separate Places API resolution step.

## Phase 6 — Demo Polish and Deployment

Before submission, establish a repeatable deployment path, responsive UI, representative demo scenarios, and final end-to-end verification.

The backend stays private while Firebase anonymous sign-in is the only public
protection. Before enabling direct internet access, add a reviewed public edge,
distributed per-user rate limits, an aggregate request/cost cap, provider quotas,
and abuse monitoring. Firebase identity is necessary for ownership but is not a
rate limiter.

## Later Decision Features

The detailed Comparison, Shortlist, and Commute sections below remain candidate product features after the integration and structured-result path is solid.

## P3 — Comparison Mode

### Goal

Let the user compare several returned listings without manually reconstructing the differences.

Example:

```text
Compare #1, #2, and #4.
```

Expected output should provide a compact side-by-side decision view covering source-backed fields such as:

- rent
- bedrooms / bathrooms
- property type
- availability
- pet policy
- parking
- useful amenities
- budget headroom
- important unknowns
- explicit tradeoffs

### Design Constraint

Comparison should reuse the existing canonical listing / verification evidence. Gemini may explain the differences but must not create missing facts or a second ranking authority.

### Acceptance

A user can select two or more current results and receive a deterministic evidence-based comparison with a concise recommendation for different priorities.

---

## P4 — Shortlist

### Goal

Allow a user to save promising listings and continue the decision process across follow-up turns.

Example:

```text
Save #2 and #3.
Show my saved listings.
Compare them with today's best result.
```

Shortlist state should retain enough context to support later comparison, for example:

- listing identity
- last verified canonical snapshot
- why the user saved it
- known strengths
- known concerns / unknowns

### Design Constraint

Start with the smallest persistence scope justified by the product demo. Do not introduce a broad CRM / user-profile platform before shortlist behavior itself is proven useful.

### Acceptance

The user can save, list, remove, and compare shortlisted properties without losing the original listing identity or verification evidence.

Current implementation note: FastAPI now provides authenticated save/list/remove
routes backed by repository interfaces and Firestore, and saved snapshots retain
available coordinate/commute evidence. Notes, user-authored reasons, and full ADK
session restoration remain future refinements.

---

## P5 — Commute Intelligence

### Goal

Add deterministic commute evidence so the Agent can answer requests such as:

> Find me a 2B2B under $4,000 within 20 minutes of Google Mountain View.

The intended direction is Google Maps / Routes integration.

```text
listing address
↓
Google Routes
↓
commute duration / distance evidence
↓
deterministic hard filter or ranking feature
```

### Design Constraint

Gemini must never guess commute time. Commute constraints and scores must come from a route data tool and remain deterministic once the route evidence is returned.

Time-of-day / traffic assumptions must be explicit rather than hidden in a generic `30 minutes away` score.

### Acceptance

A user can provide a work destination and commute preference, and returned listings include source-backed route evidence that participates in the deterministic decision pipeline.

---

## Later Candidates

Only after the decision workflow is strong enough to justify more scope:

- additional structured rental providers
- persistent cross-session preference profile
- listing-change monitoring
- richer saved-search workflows
- custom consumer frontend
- landlord outreach / tour scheduling
- MLS / RESO integration

## Explicitly Not a Near-Term Priority

Do not expand the project merely to look more complex for a demo.

Avoid making these blockers for P3–P5:

- multi-agent orchestration
- nationwide coverage
- Zillow scraping
- full MLS integration
- custom crawler infrastructure
- crime / school scoring without trustworthy data contracts
- autonomous landlord messaging
- broad workflow automation unrelated to rental decisions

The architectural rule remains:

> Add a new component only when it creates a clear product capability or authority boundary that the existing Single Agent + deterministic tools cannot represent cleanly.
