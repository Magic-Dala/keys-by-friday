# Keys by Friday — AI Rental Search Agent

Keys by Friday is a **single-agent rental decision MVP** for Silicon Valley. It turns natural-language rental requirements into a ranked, verified, explainable shortlist of real listings.

```text
Natural-language request
→ Google ADK Single Rental Agent
→ Gemini requirement parsing + tool calling
→ RealtyAPI / Apartments.com listings
→ Canonical normalization
→ Deterministic hard filters + ranking
→ Top-3 detail verification
→ Verified recommendations + tradeoffs
```

## Current Capabilities

- Real Silicon Valley rental search through RealtyAPI / Apartments.com
- Supported cities: San Jose, Santa Clara, Sunnyvale, Mountain View, Palo Alto, Menlo Park, Redwood City
- Deterministic budget / bedroom / bathroom / pet / parking constraints
- Ranked Top 5 with clickable source URLs
- Automatic detail verification for the Top 3
- Verified availability, pet policy, parking policy, amenities, and other provider details when available
- ADK Session State for follow-up refinements such as: `Change the budget to $3,500; keep everything else.`
- Ordered Gemini fallback for quota / model availability failures
- Mock provider for credential-free local development

The Agent intentionally exposes only two product tools:

- `search_listings()`
- `get_listing_details()`

## Quick Start

Requires Python 3.11+ and `uv`.

```powershell
uv sync --extra dev
```

### Mock mode

No listing-provider credential is required:

```env
LISTING_PROVIDER=mock
```

### Real listing mode

Create a RealtyAPI key, then run:

```powershell
.\scripts\setup_keys.ps1
```

This writes credentials only to the git-ignored `.env` file.

Start the Google ADK developer UI:

```powershell
uv run adk web . --no-reload --port 8765
```

Or run a CLI query:

```powershell
uv run adk run rental_agent "2B2B under $4,000 in Mountain View"
```

Then refine it in the same ADK session, for example:

```text
Change the budget to $3,500, keep everything else.
```

## Architecture at a Glance

```text
User
 ↓
Google ADK
 ↓
Single Rental Agent
 ├─ Gemini: language understanding, tool choice, soft preferences, explanation
 └─ Python: provider access, normalization, hard filtering, ranking, verification
        ↓
RealtyAPI / Apartments.com
```

Hard facts remain deterministic; Gemini must not override the filter/ranking boundary or invent unavailable listing data.

## Documentation

GitHub Markdown is the **authoritative technical source of truth**. Notion is the human-friendly project overview / dashboard and should link back to these docs instead of duplicating all implementation details.

- [Architecture](docs/architecture.md) — ADK Single Agent, responsibility boundaries, Gemini fallback
- [Listing Pipeline](docs/listing-pipeline.md) — RealtyAPI, canonical model, hard filters, ranking, Top-3 verification
- [Session and UX](docs/session-and-ux.md) — ADK Session State, refinement behavior, output contract, E2E flow
- [Status](docs/status.md) — completed capabilities, tests, real E2E evidence
- [Roadmap](docs/roadmap.md) — Comparison, Shortlist, Commute Intelligence

## Tests

```powershell
uv run pytest -q
```

The current focused suite covers deterministic filtering/ranking, RealtyAPI request and detail normalization, ADK session requirement memory, Top-3 verification merging, Gemini fallback, mock mode, and credential boundaries.

## Scope Boundary

Current development focuses on:

> **Find → Verify → Understand → Rank → Decide**

Not current blockers: nationwide coverage, Zillow scraping, full MLS integration, multi-agent orchestration, crime/school scoring, continuous monitoring, landlord outreach, viewing automation, or a large custom frontend.
