# Session and UX

## Goal

Make rental search conversational without sacrificing deterministic requirements or source-backed evidence.

The Agent should feel like a rental decision assistant, not a stateless search box.

## ADK Session Requirement Memory

`search_listings()` stores the effective rental requirements in Google ADK Session State.

This lets the user refine only one part of the search while preserving omitted constraints.

Example:

```text
User: 2B2B under $4,000 in Mountain View.
Agent: searches and verifies candidates.

User: Change the budget to $3,500, keep everything else.
```

The second Gemini tool call may contain only:

```text
max_rent = 3500
```

The tool merges that change with the persisted session state:

```text
city = Mountain View
min_bedrooms = 2
min_bathrooms = 2
max_rent = 3500
```

This behavior was verified through a real two-turn ADK session, not only through direct Python unit tests.

## Refinement Rules

- Omitted hard constraints are inherited from the current session search.
- Explicitly changed constraints replace their previous value.
- `reset_search=True` is reserved for an explicit start-over / replace-the-search request.
- Relative language such as `cheaper` without a concrete numeric limit must not invent a new hard budget. It can become a soft preference while retaining the current hard maximum.
- Soft preferences such as quiet, newer, modern, or near transit must not silently become hard filters.

## Search and Verification Conversation Flow

For an initial or refined search:

```text
User message
↓
Gemini extracts changed requirements
↓
search_listings() exactly once
↓
Top 5 + bounded Top-3 verification list
↓
get_listing_details() for Top 3
↓
Verified final answer
```

The three detail calls may be issued in parallel.

For a follow-up about one specific already-listed property, the Agent can call `get_listing_details()` directly when the search requirements did not change.

## Output Contract

The final response should be decision-oriented and readable.

Preferred structure:

```markdown
A short sentence summarizing the effective search.

## Best verified matches

### 1. [Address](source_url)
**$X/mo · X bed · X bath · Property type**
- **Why it fits:** deterministic / source-backed reasons
- **Verified details:** availability; pet / parking; useful amenities
- **Tradeoffs:** missing or weaker evidence
- **Source:** Apartments.com

## Other matches
- Rank 4 / 5 candidates, clearly marked as not detail-verified yet
```

Do not display internal numeric ranking scores to users.

## Evidence Rules

The Agent must distinguish between:

- **hard evidence** — provider / deterministic pipeline facts
- **soft preference interpretation** — user language that can guide explanation or future ranking work
- **unknown** — information the provider does not supply

Unknown information should be stated as unknown. The Agent must not invent:

- safety / crime conditions
- commute time
- school quality
- pet rules
- parking availability
- property age
- other listing facts

unless the relevant tool or provider supplied evidence.

## Current E2E Example

```text
User:
2B2B under $4,000 in Mountain View

↓ Gemini
search_listings(...)

↓ RealtyAPI
real search results

↓ deterministic Python
normalize → filter → rank

↓ Gemini / ADK
get_listing_details(#1)
get_listing_details(#2)
get_listing_details(#3)

↓ final response
verified Top 3 + other matches + clickable URLs + tradeoffs
```

Follow-up in the same session:

```text
User:
Change the budget to $3,500, keep everything else.

↓ Gemini
search_listings(max_rent=3500)

↓ ADK Session State
Mountain View + 2B2B retained

↓ new search / verification
```

## UX Direction

The current ADK Web UI is a developer interface, not the final product frontend. Product work should preserve the same behavioral contract if a custom UI is introduced later:

> **Find → Verify → Understand → Rank → Decide**
