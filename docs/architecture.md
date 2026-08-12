# Architecture

## Design Goal

Keys by Friday uses **one Google ADK Rental Agent**, not a multi-agent graph. The Agent owns conversational orchestration while deterministic Python code owns listing facts and decision boundaries.

```text
User
 ↓
Google ADK session/runtime
 ↓
Single Rental Agent
 ├─ Ordered Gemini model
 ├─ search_listings()
 └─ get_listing_details()
        ↓
Provider abstraction
        ↓
RealtyAPI / Apartments.com or Mock
```

## Why Single Agent

The current product flow is bounded and sequential: understand the request, search, verify, explain. Separate agents would add orchestration overhead without creating a distinct authority boundary.

The implementation therefore keeps exactly two product tools:

- `search_listings()`
- `get_listing_details()`

Search, normalization, ranking, verification, and provider access remain implementation modules behind those tools rather than separate agents.

## Responsibility Boundary

### Gemini owns

- Natural-language requirement extraction
- Understanding follow-up refinements
- Soft-preference interpretation
- Tool selection and tool-call arguments
- User-facing recommendation and tradeoff explanations

### Deterministic Python owns

- Listing-provider access
- Canonical normalization
- City matching
- Rent / budget checks
- Bedroom / bathroom bounds
- Pet / parking hard requirements
- Deterministic ranking
- Top candidate selection
- Detail merge and hard-filter revalidation

Gemini must not re-add a listing rejected by deterministic filters or invent missing listing facts.

## ADK Session State

The Agent uses ADK session state rather than a custom memory service. Effective rental requirements and recent candidate/verification state are stored in the current session so a follow-up can update only the fields that changed.

Example:

```text
Turn 1: 2B2B under $4,000 in Mountain View
Turn 2: Change the budget to $3,500, keep everything else.
```

The second tool call may contain only `max_rent=3500`; the tool merges it with the persisted session requirements.

See [Session and UX](session-and-ux.md) for the behavioral contract.

## Gemini Model Fallback

The Agent uses an ordered model wrapper instead of binding the runtime to one quota pool.

Default order:

```text
gemini-3.5-flash-lite
→ gemini-3.1-flash-lite
→ gemini-3.6-flash
→ gemini-3.5-flash
→ gemini-2.5-flash
```

Override with:

```env
GEMINI_MODELS=model-a,model-b,model-c
```

Fallback is intentionally narrow. The next model is tried for model-layer availability failures such as:

- HTTP 404 — configured model unavailable
- HTTP 408 — request timeout
- HTTP 429 — quota / rate limit
- HTTP 5xx — model service failure
- transport / timeout failures classified as retryable by the wrapper

The Agent does **not** hide prompt/schema/authentication/application errors by cycling through every model. HTTP 400/401/403 and ordinary tool/provider failures are surfaced instead.

## Provider Boundary

Listing access is abstracted by `ListingProvider`:

```text
ListingProvider
├─ search(requirements)
├─ get_listing(listing_id)
├─ get_changes(...)
└─ health()
```

The active real provider is RealtyAPI / Apartments.com. A mock provider keeps local development and tests independent of external credentials.

The provider abstraction is intentionally more stable than any one marketplace integration. Future data sources should normalize into the same canonical model rather than leaking provider-specific fields into the Agent contract.

## Technical Source of Truth

GitHub code and Markdown docs are authoritative for implementation behavior. Notion is the team-facing project overview and should summarize or link to these documents instead of maintaining a second copy of detailed technical contracts.
