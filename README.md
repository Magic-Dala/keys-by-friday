# Keys by Friday — MVP

A single Google ADK + Gemini rental agent for a bounded Silicon Valley search flow:

```text
natural-language request
→ Single Rental Agent
→ ADK session requirement memory
→ RealtyAPI Apartments or mock provider
→ canonical listings
→ deterministic hard filters + ranking
→ detail-verify Top 3
→ verified recommendations + tradeoffs
```

## Scope

Supported cities: San Jose, Santa Clara, Sunnyvale, Mountain View, Palo Alto, Menlo Park, and Redwood City.

The agent still has exactly two tools:

- `search_listings()`
- `get_listing_details()`

Gemini handles natural-language understanding, follow-up refinements, soft preferences, tool selection, and explanations. Rent, bedrooms, bathrooms, pets, parking, normalization, hard filtering, and ranking stay deterministic.

### Session memory and verification

Within one ADK session, `search_listings()` stores the effective rental requirements in ADK session state. A follow-up can therefore change only one constraint while omitted constraints remain unchanged.

Example:

```text
2B2B under $4,000 in Mountain View
→ Change the budget to $3,500; keep everything else.
```

The second search keeps Mountain View and 2B2B while changing only the budget. `reset_search=True` is reserved for an explicit start-over request.

After each initial or refined search, the agent detail-verifies only the Top 3 candidates with `get_listing_details()`. Detail verification enriches the recommendation with evidence such as availability, pet policy, parking policy, amenities, and year built when the provider supplies it. Ranks 4-5 remain clearly marked as not detail-verified unless the user asks about one specifically.

## Gemini model fallback

The single Agent tries Gemini models in this order by default:

```text
gemini-3.5-flash-lite
→ gemini-3.1-flash-lite
→ gemini-3.6-flash
→ gemini-3.5-flash
→ gemini-2.5-flash
```

Override the order with `GEMINI_MODELS`, using a comma-separated list. Fallback only occurs for quota/rate-limit, missing-model, timeout, or server-side model failures (HTTP 404/408/429/5xx). Prompt/schema/auth errors are surfaced instead of silently switching models.

## Setup

Requires Python 3.11+ and `uv`.

```powershell
uv sync --extra dev
```

Mock mode needs no listing-provider key:

```env
LISTING_PROVIDER=mock
```

For the real provider, create a RealtyAPI key and run:

```powershell
.\scripts\setup_keys.ps1
```

The script preserves an existing Google/Gemini key, securely prompts for the RealtyAPI key, writes the default model fallback order, and writes only to the git-ignored `.env` file.

Start the Google ADK developer UI:

```powershell
uv run adk web . --no-reload
```

Or run one ADK CLI query:

```powershell
uv run adk run rental_agent "2B2B under $4,000 in Mountain View"
```

## Real listing mode

```env
LISTING_PROVIDER=realtyapi
REALTYAPI_API_KEY=your_key
GOOGLE_API_KEY=your_gemini_key
GEMINI_MODELS=gemini-3.5-flash-lite,gemini-3.1-flash-lite,gemini-3.6-flash,gemini-3.5-flash,gemini-2.5-flash
```

The MVP uses RealtyAPI's Apartments search endpoint. Provider-side filters narrow rent, beds, integer bathroom bounds, generic pet-friendly, and parking requirements before the canonical deterministic filter runs again locally.

The current boolean `pets_required` model is intentionally conservative: generic pet-friendly requests use the provider's `Dog_and_Cat` filter until the product models pet species explicitly.

If `LISTING_PROVIDER=realtyapi` is requested without `REALTYAPI_API_KEY`, startup fails immediately with a clear credential error.

## Tests

```powershell
uv run pytest -q
```

The focused suite verifies deterministic filtering/ranking, mock operation without external keys, RealtyAPI request/auth construction and detail normalization, ADK session requirement memory, Top-3 verification merging, ordered Gemini fallback behavior, the two-tool single-agent surface, and the real-mode credential boundary.
