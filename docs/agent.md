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
- `stage_outcomes` — ordered list of `{stage, status}` node outcomes; each node is
  `completed`, `partial`, or `requires_input`
- `completed_stages` — derived convenience list containing only nodes whose outcome
  is actually `completed`
- `facts` — bounded execution facts such as provider-search reuse, result counts,
  verification counts, missing candidates, or route availability

All `activity` statuses describe a returned terminal outcome. `partial` means the
tool returned with incomplete evidence or coverage; it does **not** mean the tool is
still running. In-progress state comes from the ADK tool-call lifecycle before the
tool response exists.

It intentionally does not expose UI messages, fake percentages, timestamps, or
chain-of-thought. ADK tool-call lifecycle events can represent the start of work;
the returned `activity` object describes what is known when that tool returns. If a
tool raises before producing a response, the ADK tool-error lifecycle is the failure
boundary; integrations must not invent a successful `activity` response.

Stable stage names are `requirements`, `listing_search`, `session_reuse`,
`commute_check`, `hard_filter`, `detail_verification`, `soft_preference_evidence`,
and `candidate_comparison`.

## Search Flow

```text
User request
→ search_listings()
→ requirements
→ [provider search → normalization] OR [session reuse]
→ commute check (only when requested)
→ hard filters
→ deterministic ranking
→ strongest candidates
→ selected-only get_listing_details() (when needed)
→ soft-preference evidence evaluation (when requested)
→ compare_candidates() (when comparing)
→ final explanation
```

The order above is the logical decision path exposed to integrations. A cache-first
search must report `session_reuse`, not pretend that a provider search occurred.
Partial provider coverage, unavailable/unknown commute data, and incomplete detail
verification stay `partial`; they are never upgraded to completed progress for UI
convenience.

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
