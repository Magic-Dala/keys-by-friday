# Project Status

> **Document type: Living Document**  
> This file is expected to change as implementation progresses. Update it when a capability becomes working, blocked, replaced, or verified. Do not copy stable architecture or API rules here.

## Current Stage

**Project baseline established: the web integration, shared API contract, structured listing flow, and Google ADK Agent path are all runnable together.**

Current end-to-end shape:

```text
Next.js Frontend
→ POST /api/chat
→ FastAPI Backend
→ Verified Firebase uid
→ AgentService
→ Google ADK Rental Agent
→ RealtyAPI / Apartments.com
→ Google Routes when commute is requested and configured
→ Agent response
```

## Working Now

### Web Integration

- ✅ Next.js frontend skeleton
- ✅ FastAPI backend
- ✅ `GET /health`
- ✅ `POST /api/chat`
- ✅ Frontend → backend HTTP integration
- ✅ Backend → Google ADK adapter
- ✅ `conversationId` mapped to ADK session continuity
- ✅ Explicit `AGENT_MODE=stub` for contract testing
- ✅ Real ADK mode is the normal path
- ✅ Structured `listings[]` normalized from ADK tool responses
- ✅ Basic frontend listing cards consume the shared contract

### Agent / Rental Decision Flow

- ✅ Google ADK Single Rental Agent
- ✅ `search_listings()`
- ✅ `get_listing_details()`
- ✅ Gemini natural-language requirement parsing
- ✅ ADK Session State for follow-up refinement
- ✅ RealtyAPI / Apartments.com real listing search
- ✅ Canonical normalization
- ✅ Deterministic hard filtering and ranking
- ✅ Top-3 detail verification
- ✅ Search/detail merge and hard-filter revalidation
- ✅ Source-backed final recommendation text
- ✅ Listing latitude/longitude preserved through the Agent → backend contract
- ✅ Google Route Matrix summaries for complete commute requirements
- ✅ Deterministic hard commute filtering before ranking
- ✅ Explicit `unknown` / `unavailable` commute states instead of guessed passes
- ✅ On-demand `POST /api/route` selected-listing geometry contract
- ✅ Firebase ownership protection on both `/api/chat` and `/api/route`
- ✅ Ordinary rental search remains available when Maps is not configured

### Development Foundation

- ✅ `frontend/**`, `backend/**`, and `rental_agent/**` ownership boundaries
- ✅ Shared API contract
- ✅ Centralized backend environment settings
- ✅ Request validation and stable Agent failure boundary
- ✅ Verified hard-filter failures excluded from structured web results
- ✅ Frontend runtime validation for backend responses
- ✅ Small server/client component boundary for the Next.js App Router
- ✅ `uv` Python environment
- ✅ npm / Next.js frontend environment
- ✅ `.env` secrets ignored by Git
- ✅ Stable-reference documentation structure
- ✅ Cloud Run-compatible backend container
- ✅ Backend configuration validation for environment, logging, and Agent timeout
- ✅ Cloud-friendly structured JSON request logs and request IDs
- ✅ Separate liveness (`/health`) and configuration readiness (`/ready`) checks
- ✅ Bounded Agent execution time with a stable API failure boundary
- ✅ Secret Manager-based deployment instructions for macOS
- ✅ Optional anonymous Firebase sign-in in the Next.js frontend
- ✅ Firebase Admin ID-token verification in FastAPI
- ✅ Verified Firebase `uid` replaces the shared `web-user` ADK identity
- ✅ Conversation ownership rejects cross-user reuse with HTTP 403
- ✅ Authorization header enabled in the backend CORS policy
- ✅ Authentication configuration included in readiness checks

## In Progress / Next Product Work

- 🔄 Improve frontend rental-result UX beyond the basic listing cards
- 🔄 Run a live Google Routes smoke test with a restricted Maps key
- 🔄 Present structured commute/map evidence in the product frontend
- 🔄 Comparison and shortlist workflows remain later product work
- 🔄 Keep Cloud Run private until the hosted browser path has distributed rate limits, aggregate cost caps, and abuse monitoring

The web vertical slice now returns both the Agent's readable `message` and structured `listings[]` from the same ADK execution.

## Latest Verified Evidence

As of the current integration work:

- ✅ Python / Backend / Agent tests: 112 passed, including Firebase auth, commute integration, and cross-user isolation
- ✅ Backend container built locally with Python 3.12
- ✅ Local process and Docker smoke tests passed for `/health`, `/ready`, and `/api/chat`
- ✅ Request IDs were returned in HTTP headers and correlated with structured JSON logs
- ✅ Next.js production build passed
- ✅ TypeScript typecheck passed
- ✅ Frontend page rendered locally
- ✅ Backend health endpoint responded successfully
- ✅ Real `/api/chat` request reached Google ADK and returned real Mountain View rental matches
- ✅ Real `/api/chat` response returned 4 structured listings with normalized price / beds / baths / source URL / reason
- ✅ Real follow-up request reused the same `conversationId` and preserved the ADK session
- ✅ Empty requests return 422 and Agent-layer failures are mapped to a stable 502 response
- ✅ Frontend TypeScript typecheck passed after listing-card integration
- ✅ Firebase frontend changes pass a direct TypeScript typecheck
- ✅ Removed `/api/search` returns 404; `/api/chat` is the single primary web endpoint

Exact commit hashes and branch names are intentionally not recorded here; Git is the source of truth for those details.

## Known MVP Boundaries

- Geography is currently focused on configured Silicon Valley cities.
- Some provider fields are unavailable for some listings and must remain unknown.
- Soft preferences such as quiet / safe / modern do not yet have dedicated enrichment evidence.
- Commute is computed only when destination, limit, travel mode, coordinates,
  and a working Routes API key are available; otherwise it remains explicitly
  unknown or unavailable and must not be guessed by Gemini.
- Natural-language destination resolution has not yet been validated with a
  live key; Places API was intentionally not added by the Maps boundary PR.
- Persistent shortlist / comparison workflows are not complete.
- Conversation ownership and ADK sessions are still process memory; Firestore persistence is not complete.
- Background monitoring and landlord outreach are outside the current MVP.

## Update Rule

This file **should** change when implementation status changes.

Do not use it to redefine architecture, API contracts, or Agent behavioral rules. Those belong in the Stable Reference documents linked from the README.
