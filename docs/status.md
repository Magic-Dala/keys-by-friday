# Project Status

## Current Stage

**Runnable Silicon Valley Rental Agent MVP**

Current development branch:

```text
feat/rental-agent-mvp
```

This document tracks the current implementation state. Git history remains the authoritative record for individual commits; commit hashes are intentionally not hard-coded here because they become stale immediately.

## Completed Capabilities

### Agent / AI

- ✅ Google ADK Single Rental Agent
- ✅ Exactly two product tools: `search_listings()` and `get_listing_details()`
- ✅ Gemini natural-language requirement parsing
- ✅ Follow-up refinement through ADK Session State
- ✅ Ordered Gemini model fallback
- ✅ Narrow fallback behavior for quota / model / service failures
- ✅ Structured recommendation and tradeoff output

### Listing Data / Decision Pipeline

- ✅ `ListingProvider` abstraction
- ✅ RealtyAPI / Apartments.com real-data provider
- ✅ Mock provider for local / test mode
- ✅ Canonical listing normalization
- ✅ Exact supported-city filtering
- ✅ Deterministic budget / bed / bath / pet / parking constraints
- ✅ Deterministic ranking
- ✅ Clickable Apartments.com source URLs
- ✅ Top-3 detail verification
- ✅ Search/detail evidence merge and hard-filter revalidation
- ✅ Availability / pet / parking / amenities enrichment when supplied by provider

### Developer Experience

- ✅ `uv`-based environment
- ✅ `.env.example`
- ✅ Git-ignored local credentials
- ✅ PowerShell credential setup script
- ✅ ADK Web local developer UI
- ✅ CLI query path
- ✅ ADK local runtime data ignored from Git

## Validation Status

Latest focused suite at this MVP stage:

```text
17 tests passed
Python compile PASS
```

Real integration paths have also been exercised successfully:

- ✅ Natural language → Gemini → ADK tool calling
- ✅ RealtyAPI real listing search
- ✅ Canonical normalization + deterministic filter/rank
- ✅ Apartments.com source URLs in final output
- ✅ `search_listings → get_listing_details × Top 3 → final recommendation`
- ✅ Top-3 detail calls issued in parallel by the Agent
- ✅ Real two-turn ADK session requirement memory
- ✅ Second-turn partial update preserving prior city / 2B2B requirements
- ✅ Primary Gemini Flash-Lite model successfully performing function calling

## Current Real E2E Shape

```text
User request
↓
Gemini
↓
search_listings()
↓
RealtyAPI search
↓
normalize / filter / rank
↓
Top 5
↓
parallel detail verification for Top 3
↓
verified recommendations + other matches
```

A validated refinement flow also looks like:

```text
Turn 1:
2B2B under $4,000 in Mountain View

Turn 2:
Change the budget to $3,500, keep everything else.

Resulting effective constraints:
Mountain View + 2B2B + $3,500 max
```

## Known MVP Boundaries

- Supported geography is currently limited to the configured Silicon Valley cities.
- RealtyAPI search rows can represent property/community ranges rather than exact individual units; the normalizer uses conservative deterministic handling.
- Some provider fields remain unavailable for some listings and must stay unknown.
- The current ADK Web UI is a development interface, not a final consumer frontend.
- Soft preferences such as quiet / safe / modern are not yet backed by dedicated enrichment data.
- Commute time is not yet computed; it must not be guessed by Gemini.
- No persistent shortlist / comparison workflow exists yet.
- No background monitoring or landlord outreach exists yet.

## Documentation Policy

GitHub code and Markdown docs are the authoritative technical source of truth.

Notion is the human-friendly project overview / dashboard and should summarize current state and link to GitHub docs. Implementation changes should update the relevant Markdown file in the same PR whenever the documented contract changes.
