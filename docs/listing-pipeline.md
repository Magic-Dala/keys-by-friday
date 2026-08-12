# Listing Pipeline

## Goal

Convert provider-specific rental data into one deterministic, explainable decision pipeline.

```text
Natural-language requirements
↓
search_listings()
↓
ListingProvider.search()
↓
Canonical Listing normalization
↓
Hard filters
↓
Deterministic ranking
↓
Top 5
↓
Top-3 detail verification
↓
Final recommendation evidence
```

## Active Listing Source

The current real-data provider is **RealtyAPI / Apartments.com**.

The provider implementation uses RealtyAPI search and detail endpoints, then converts provider payloads into the internal canonical listing model. Apartments.com source URLs are derived only from provider-backed listing identifiers / fields; the Agent must not invent source URLs.

A `MockListingProvider` exists for tests and credential-free local development.

## Canonical Listing Model

Provider responses are normalized before ranking. The model currently carries fields such as:

- listing ID
- address / city / state / ZIP
- rent
- bedrooms / bathrooms
- property type
- square footage
- status / listing timestamps when available
- pet / parking evidence
- source URL
- source provider
- property name
- availability
- year built
- amenities
- pet policy text
- parking policy text
- detail verification status

Missing source data remains `unknown` / `None`. Gemini must not fill unknown fields from general knowledge.

## Search Normalization

RealtyAPI search results can represent property/community placards rather than one exact unit. The MVP normalizer therefore applies conservative rules where necessary.

Examples:

- For a displayed rent range, the canonical rent uses the **upper bound** for a hard maximum-budget check.
- For bedroom ranges, the represented upper bedroom count is normalized for current search behavior.
- Bathroom search results may omit the bathroom field even when a provider-side `bathRange` filter was applied; the pipeline preserves documented provider-filter evidence rather than asking Gemini to guess.
- Exact requested city matching is enforced locally because the provider can return nearby-city results.

## Hard Filters

Hard constraints are deterministic and authoritative.

A listing fails when an explicitly required fact is contradicted or cannot satisfy the required boundary.

Current hard constraints include:

```text
listing.city == requested city
listing.state == requested state
rent <= max_rent
bedrooms >= min_bedrooms
bedrooms <= max_bedrooms
bathrooms >= min_bathrooms
bathrooms <= max_bathrooms
pets_allowed == True       when pets are required
parking_available == True  when parking is required
```

Unknown pet / parking status is not treated as proof that the requirement is satisfied.

## Deterministic Ranking

Only listings that pass the hard filters enter ranking.

The current score rewards deterministic evidence such as:

- budget headroom
- bedrooms above the minimum
- bathrooms above the minimum
- square footage when available

Ranking is pure: the same listing data plus the same requirements produces the same order. Gemini does not modify the numeric score.

User-facing output does not expose raw internal scores. Instead the pipeline emits reasons and tradeoffs that Gemini may explain.

## Top-3 Detail Verification

Search summaries are not considered sufficient evidence for the strongest recommendations.

After the Top 5 are ranked, the Agent receives a bounded `verification_candidates` list containing only the first three candidates.

It then calls `get_listing_details()` for those candidates, normally in parallel.

Detail responses can add or strengthen evidence such as:

- availability
- pet policies
- parking policies
- amenities
- property type
- year built
- updated listing data

The detail listing is merged with existing search evidence and checked against the current hard constraints again. A detail-verified listing that fails the current hard filters must not be presented as a verified match.

Ranks 4–5 remain visible as other matches but are clearly labeled as not detail-verified unless the user asks about one directly.

## Data-Source Roadmap

The provider abstraction is designed for additional sources without changing the Agent contract.

Current priority:

| Source | Role | Status / Priority |
|---|---|---|
| RealtyAPI / Apartments.com | Current structured real-data source | Active |
| Additional structured rental API | Improve coverage / redundancy | Next |
| Zillow | Important marketplace coverage | Later |
| MLS / RESO | Long-term authoritative source | Later |
| Custom crawler | Fallback only | Avoid unless necessary |

RentCast was evaluated during MVP development but is not part of the active runtime.
