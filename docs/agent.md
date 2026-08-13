# Agent

> **Stable Reference — change only when the Agent's authority or behavior rules intentionally change.**

## Baseline

Keys by Friday uses one Google ADK Rental Agent.

The Agent exposes two product tools:

- `search_listings()`
- `get_listing_details()`

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

Gemini must not override deterministic rejection or invent unavailable listing facts.

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
