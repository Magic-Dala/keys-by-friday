# Project Status

> **Document type: Living Document**  
> This file is expected to change as implementation progresses. Update it when a capability becomes working, blocked, replaced, or verified. Do not copy stable architecture or API rules here.

## Current Stage

**Project baseline established: the web integration, shared API contract, structured listing flow, commute evidence, comparison intelligence, and Google ADK Agent path are runnable together.**

Current end-to-end shape:

```text
Next.js Frontend
→ POST /api/chat
→ FastAPI Backend
→ Verified Firebase uid
→ Firestore repositories for conversation metadata and shortlists
→ AgentService
→ Google ADK Rental Agent
→ RealtyAPI-backed rental providers + Google Routes evidence when configured
→ Agent response + structured execution metadata
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
- ✅ `get_route_details()`
- ✅ `compare_candidates()`
- ✅ Gemini natural-language requirement parsing
- ✅ ADK Session State for follow-up refinement
- ✅ RealtyAPI-backed multi-source listing search
- ✅ Canonical normalization
- ✅ Deterministic hard filtering and ranking
- ✅ Deterministic commute enrichment / constraint evaluation when requested
- ✅ Selected-only detail verification with verified-detail reuse
- ✅ Search/detail merge and hard-filter revalidation
- ✅ Evidence-backed evaluation for supported soft preferences such as modern, quiet, near transit, and newer
- ✅ Deterministic side-by-side candidate comparison with unknown / evidence-only semantics
- ✅ `rental.agent_activity.v1` execution metadata for Agent-side observability
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
- ✅ Separate liveness (`/health`) and dependency readiness (`/ready`) checks
- ✅ Bounded Agent execution time with a stable API failure boundary
- ✅ Secret Manager-based deployment instructions for macOS
- ✅ Optional anonymous Firebase sign-in in the Next.js frontend
- ✅ Firebase Admin ID-token verification in FastAPI
- ✅ Verified Firebase `uid` replaces the shared `web-user` ADK identity
- ✅ Conversation ownership rejects cross-user reuse with HTTP 403
- ✅ Authorization header enabled in the backend CORS policy
- ✅ Authentication configuration included in readiness checks
- ✅ Backend Firestore client factory and repository interfaces
- ✅ Durable conversation ownership and normalized result metadata
- ✅ Authenticated, bounded Recent Searches metadata API with user-scoped ordering and zero-turn exclusion
- ✅ Backend-owned shortlist save, list, and remove APIs
- ✅ Shortlist snapshots preserve structured coordinate and commute evidence
- ✅ Fake in-memory repositories cover persistence without cloud quota in CI
- ✅ Firestore client rules deny direct browser access
- ✅ Configurable official ADK session service: memory locally, database in production
- ✅ Restart-safe ADK event history and Agent state through PostgreSQL / Cloud SQL
- ✅ `/ready` verifies a real ADK database lookup before serving production traffic
- ✅ Same-conversation turns serialized to prevent stale simultaneous follow-ups
- ✅ Python 3.12 pinned consistently for macOS development and the backend container
- ✅ Frozen `kbf.canonical-listing.v1` objects preserved through API and Firestore snapshots
- ✅ `POST /api/compare` returns and persists `kbf.canonical-comparison.v1`
- ✅ Frontend comparison uses deterministic facts plus a separate Gemini explanation
- ✅ Explicit comparison unknowns remain unknown instead of becoming guessed facts
- ✅ Comparison responses refresh selected canonical listing snapshots without dropping unselected persisted results
- ✅ Complete shortlist CRUD with authenticated note updates
- ✅ Distributed Firestore rate limit for anonymous `/api/chat` and `/api/compare`
- ✅ HTTP 429, `Retry-After`, and browser-visible rate-limit response headers

## In Progress / Next Product Work

- 🔄 Improve frontend rental-result UX beyond the basic listing cards
- 🔄 Expose Agent activity metadata through a backend/frontend progress transport
- 🔄 Run a live Google Routes smoke test with a restricted Maps key
- 🔄 Present structured commute/map evidence in the product frontend
- 🔄 Keep Cloud Run private until the hosted browser path also has aggregate cost caps and abuse monitoring

The web vertical slice now returns both the Agent's readable `message` and structured `listings[]` from the same ADK execution.

## Latest Verified Evidence

As of the current Agent decision-intelligence, persistence, Firebase-auth, and
anonymous rate-limit integration work:

- ✅ Full Python / Backend / Agent suite: 216 passed, including Firebase auth, Firestore persistence, bounded Recent Searches pagination, persistent ADK sessions, database connectivity readiness, restart restoration, same-conversation concurrency, commute integration, refreshed comparison snapshots, shortlist CRUD, cross-user isolation, anonymous rate limiting, decision intelligence, and Agent observability
- ✅ Milestone 4 ADK session suite: 5 passed without Gemini or cloud quota
- ✅ Agent observability contract suite: 14 passed
- ✅ Backend container built locally with Python 3.12
- ✅ Local process and Docker smoke tests passed for `/health`, `/ready`, and `/api/chat`
- ✅ Request IDs were returned in HTTP headers and correlated with structured JSON logs
- ✅ Next.js production build passed
- ✅ Frontend suite: 10 files / 78 tests passed, including Firebase auth, Recent Searches, and the structured comparison interaction
- ✅ TypeScript typecheck passed
- ✅ Frontend page rendered locally
- ✅ Backend health endpoint responded successfully
- ✅ Real `/api/chat` request reached Google ADK and returned real Mountain View rental matches
- ✅ Live August 20, 2026 `/api/chat` smoke test used `gemini-3.7-flash`; RealtyAPI successfully searched Apartments.com, Zillow, and Realtor with no failed source and returned 5 structured listings
- ✅ Real follow-up request reused the same `conversationId` and preserved the ADK session
- ✅ Empty requests return 422 and Agent-layer failures are mapped to a stable 502 response
- ✅ Frontend TypeScript typecheck passed after listing-card integration
- ✅ Firebase frontend changes pass a direct TypeScript typecheck
- ✅ Removed `/api/search` returns 404; `/api/chat` is the single primary web endpoint

Exact commit hashes and branch names are intentionally not recorded here; Git is the source of truth for those details.

## Known MVP Boundaries

- Geography is currently focused on configured Silicon Valley cities.
- Some provider fields are unavailable for some listings and must remain unknown.
- Supported soft preferences rely on explicit listing evidence; safety remains unsupported unless a trustworthy evidence source is added.
- Commute is computed only when destination, limit, travel mode, coordinates, and route evidence are available; otherwise it remains explicitly unknown or unavailable and must not be guessed by Gemini.
- Natural-language destination resolution has not yet been validated with a live key; Places API was intentionally not added by the Maps boundary PR.
- Deterministic comparison works from the current Agent results, while shortlist snapshots persist through Firestore.
- Agent execution metadata exists, but a live backend/frontend progress transport is not implemented yet.
- Full ADK sessions persist in database mode. The local memory mode intentionally
  loses them on restart, and the current whole-turn lock is process-local, so
  multi-instance deployment needs a distributed-coordination review.
- Background monitoring and landlord outreach are outside the current MVP.

## Update Rule

This file **should** change when implementation status changes.

Do not use it to redefine architecture, API contracts, or Agent behavioral rules. Those belong in the Stable Reference documents linked from the README.
