# Agent

> **Stable Reference — change only when the Agent's authority or behavior rules intentionally change.**

## Baseline

Keys by Friday uses one Google ADK Rental Agent.

The Agent exposes four product tools:

- `search_listings()`
- `get_listing_details()`
- `get_route_details()`
- `compare_candidates()`

## Authority

### Gemini

- understand natural-language rental requirements
- understand follow-up refinements
- choose tools and arguments
- explain results and tradeoffs

### Deterministic Python

- access rental providers
- normalize listing data
- enforce hard constraints
- rank eligible listings
- merge verification evidence
- re-check hard constraints
- evaluate supported soft preferences from listing evidence
- build deterministic side-by-side comparison data

Gemini must not override deterministic rejection or invent unavailable listing facts.

## Observability Contract

Each product tool returns a top-level `activity` object using schema
`rental.agent_activity.v1`. This is deterministic execution metadata for integration
layers, not presentation copy and not model reasoning.

The contract exposes:

- `operation` — the tool that actually ran
- `stage` — the primary machine-readable execution stage
- `status` — execution outcome such as `completed`, `partial`, or `requires_input`
- `completed_stages` — only stages that actually executed
- `facts` — bounded execution facts such as provider-search reuse, result counts,
  verification counts, missing candidates, or route availability

It intentionally does not expose UI messages, fake percentages, timestamps, or
chain-of-thought. ADK tool-call lifecycle events can represent the start of work;
the returned `activity` object describes what is known when that tool completes.

Stable stage names are `requirements`, `listing_search`, `hard_filter`,
`commute_check`, `detail_verification`, `soft_preference_evidence`, and
`candidate_comparison`.

## Search Flow

```text
User request
→ search_listings()
→ provider data
→ normalization
→ hard filters
→ deterministic ranking
→ strongest candidates
→ get_listing_details()
→ compare_candidates()
→ final explanation
```

## Session Rule

ADK session state preserves the current rental requirements for follow-up turns.

A follow-up may change only one field while retaining the rest. Explicit changes replace previous values; omitted constraints remain unchanged unless the user intentionally starts over.

The backend maps its `conversationId` to this session behavior.

## Evidence Rule

Provider and deterministic data are authoritative facts. Unknown data stays unknown.

The Agent must not invent unsupported facts such as safety, crime, commute time, school quality, pet rules, parking, or property details.

## Provider Rule

Rental providers stay behind the provider abstraction and normalize into the shared internal listing model. Frontend-specific types do not belong in the Agent layer.

## Change Rule

Do not edit this document for prompt wording, UI work, test changes, one provider payload, or routine implementation details.

Update it only when the Agent tool boundary, decision authority, session semantics, evidence rules, or provider boundary intentionally changes.
