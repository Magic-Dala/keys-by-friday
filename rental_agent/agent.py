from __future__ import annotations

from dataclasses import fields
import os
from typing import Any, Optional

from dotenv import load_dotenv
from google.adk import Agent
from google.adk.tools.tool_context import ToolContext

from rental_agent.llm import build_ordered_gemini
from rental_agent.models import Listing, SearchRequirements
from rental_agent.pipeline import filter_and_rank, passes_hard_filters
from rental_agent.providers import get_provider

load_dotenv()
if os.getenv("GEMINI_API_KEY") and not os.getenv("GOOGLE_API_KEY"):
    os.environ["GOOGLE_API_KEY"] = os.environ["GEMINI_API_KEY"]
os.environ.setdefault("GOOGLE_GENAI_USE_VERTEXAI", "FALSE")

SUPPORTED_CITIES = {
    "san jose",
    "santa clara",
    "sunnyvale",
    "mountain view",
    "palo alto",
    "menlo park",
    "redwood city",
}

_REQUIREMENTS_STATE_KEY = "rental_search_requirements"
_CANDIDATES_STATE_KEY = "rental_last_candidates"
_VERIFIED_STATE_KEY = "rental_verified_details"


def _positive_number(value: float | None) -> float | None:
    if value is None or value <= 0:
        return None
    return float(value)


def _requirements_to_dict(req: SearchRequirements) -> dict[str, object]:
    return {
        "city": req.city,
        "state": req.state,
        "max_rent": req.max_rent,
        "min_bedrooms": req.min_bedrooms,
        "max_bedrooms": req.max_bedrooms,
        "min_bathrooms": req.min_bathrooms,
        "max_bathrooms": req.max_bathrooms,
        "pets_required": req.pets_required,
        "parking_required": req.parking_required,
        "soft_preferences": list(req.soft_preferences),
        "limit": req.limit,
    }


def _requirements_from_dict(value: object) -> SearchRequirements | None:
    if not isinstance(value, dict) or not value.get("city"):
        return None
    return SearchRequirements(
        city=str(value["city"]),
        state=str(value.get("state") or "CA"),
        max_rent=value.get("max_rent"),
        min_bedrooms=value.get("min_bedrooms"),
        max_bedrooms=value.get("max_bedrooms"),
        min_bathrooms=value.get("min_bathrooms"),
        max_bathrooms=value.get("max_bathrooms"),
        pets_required=bool(value.get("pets_required", False)),
        parking_required=bool(value.get("parking_required", False)),
        soft_preferences=tuple(
            str(item) for item in (value.get("soft_preferences") or []) if str(item)
        ),
        limit=int(value.get("limit") or 50),
    )


def _merge_soft_preferences(
    previous: tuple[str, ...], incoming: str, *, reset_search: bool
) -> tuple[str, ...]:
    base = [] if reset_search else list(previous)
    additions = [item.strip() for item in incoming.split(",") if item.strip()]
    return tuple(dict.fromkeys([*base, *additions]))


def _merge_requirements(
    *,
    previous: SearchRequirements | None,
    city: str,
    state: str,
    max_rent: float | None,
    min_bedrooms: float | None,
    max_bedrooms: float | None,
    min_bathrooms: float | None,
    max_bathrooms: float | None,
    pets_required: bool | None,
    parking_required: bool | None,
    soft_preferences: str,
    reset_search: bool,
) -> SearchRequirements:
    prior = None if reset_search else previous
    effective_city = city.strip() or (prior.city if prior else "")
    if not effective_city:
        raise ValueError("A supported city is required for the first rental search.")
    if effective_city.casefold() not in SUPPORTED_CITIES:
        raise ValueError(
            "MVP supports only San Jose, Santa Clara, Sunnyvale, Mountain View, "
            "Palo Alto, Menlo Park, and Redwood City."
        )

    def numeric(value: float | None, prior_value: float | None) -> float | None:
        explicit = _positive_number(value)
        return explicit if explicit is not None else prior_value

    prior_soft = prior.soft_preferences if prior else ()
    return SearchRequirements(
        city=effective_city,
        state=(state.strip().upper() or (prior.state if prior else "CA")),
        max_rent=numeric(max_rent, prior.max_rent if prior else None),
        min_bedrooms=numeric(
            min_bedrooms, prior.min_bedrooms if prior else None
        ),
        max_bedrooms=numeric(
            max_bedrooms, prior.max_bedrooms if prior else None
        ),
        min_bathrooms=numeric(
            min_bathrooms, prior.min_bathrooms if prior else None
        ),
        max_bathrooms=numeric(
            max_bathrooms, prior.max_bathrooms if prior else None
        ),
        pets_required=(
            pets_required
            if pets_required is not None
            else (prior.pets_required if prior else False)
        ),
        parking_required=(
            parking_required
            if parking_required is not None
            else (prior.parking_required if prior else False)
        ),
        soft_preferences=_merge_soft_preferences(
            prior_soft, soft_preferences, reset_search=reset_search
        ),
        limit=50,
    )


def _listing_from_dict(value: dict[str, Any]) -> Listing:
    names = {item.name for item in fields(Listing)}
    payload = {key: value.get(key) for key in names if key in value}
    return Listing(**payload)


def _merge_listing_detail(search_listing: Listing | None, detail: Listing) -> Listing:
    if search_listing is None:
        return detail
    merged = search_listing.to_dict()
    for key, value in detail.to_dict().items():
        if value is not None and value != "" and value != [] and value != ():
            merged[key] = value
    return _listing_from_dict(merged)


def search_listings(
    city: str = "",
    state: str = "",
    max_rent: float | None = None,
    min_bedrooms: float | None = None,
    max_bedrooms: float | None = None,
    min_bathrooms: float | None = None,
    max_bathrooms: float | None = None,
    pets_required: bool | None = None,
    parking_required: bool | None = None,
    soft_preferences: str = "",
    reset_search: bool = False,
    tool_context: Optional[ToolContext] = None,
) -> dict[str, object]:
    """Search rentals, remembering omitted requirements within this ADK session.

    On a follow-up search, pass only requirements the user changed. Omitted values
    inherit from the previous search in the same session. Set reset_search=True
    only when the user explicitly wants to start over. The returned
    verification_candidates must be checked with get_listing_details before the
    final recommendation.
    """
    previous = None
    if tool_context is not None:
        previous = _requirements_from_dict(
            tool_context.state.get(_REQUIREMENTS_STATE_KEY)
        )

    req = _merge_requirements(
        previous=previous,
        city=city,
        state=state,
        max_rent=max_rent,
        min_bedrooms=min_bedrooms,
        max_bedrooms=max_bedrooms,
        min_bathrooms=min_bathrooms,
        max_bathrooms=max_bathrooms,
        pets_required=pets_required,
        parking_required=parking_required,
        soft_preferences=soft_preferences,
        reset_search=reset_search,
    )

    provider = get_provider()
    normalized = provider.search(req)
    ranked = filter_and_rank(normalized, req, top_n=10)
    ranked_payload = [item.to_dict() for item in ranked]
    verification_candidates = [
        {
            "rank": index + 1,
            "listing_id": item.listing.id,
            "address": item.listing.address,
        }
        for index, item in enumerate(ranked[:3])
    ]

    if tool_context is not None:
        tool_context.state[_REQUIREMENTS_STATE_KEY] = _requirements_to_dict(req)
        tool_context.state[_CANDIDATES_STATE_KEY] = ranked_payload
        tool_context.state[_VERIFIED_STATE_KEY] = {}

    return {
        "provider": provider.health()["provider"],
        "matched_count": len(ranked),
        "top_10": ranked_payload,
        "top_5": ranked_payload[:5],
        "soft_preferences_unverified": list(req.soft_preferences),
        "effective_requirements": _requirements_to_dict(req),
        "memory_used": previous is not None and not reset_search,
        "verification_candidates": verification_candidates,
        "verification_policy": (
            "Verify exactly these top candidates with get_listing_details before "
            "giving the final recommendation. Do not verify lower-ranked results "
            "unless the user asks about one specifically."
        ),
    }


def get_listing_details(
    listing_id: str,
    tool_context: Optional[ToolContext] = None,
) -> dict[str, object]:
    """Verify one candidate with provider detail data and current hard constraints."""
    provider = get_provider()
    detail = provider.get_listing(listing_id)

    req = None
    candidates: list[dict[str, Any]] = []
    if tool_context is not None:
        req = _requirements_from_dict(
            tool_context.state.get(_REQUIREMENTS_STATE_KEY)
        )
        stored = tool_context.state.get(_CANDIDATES_STATE_KEY, [])
        if isinstance(stored, list):
            candidates = [item for item in stored if isinstance(item, dict)]

    prior_listing = None
    current_rank = None
    for index, candidate in enumerate(candidates):
        listing_payload = candidate.get("listing")
        if not isinstance(listing_payload, dict):
            continue
        if str(listing_payload.get("id")) == listing_id:
            prior_listing = _listing_from_dict(listing_payload)
            current_rank = index + 1
            break

    merged = _merge_listing_detail(prior_listing, detail)
    passes = passes_hard_filters(merged, req) if req is not None else None

    unknowns: list[str] = []
    if merged.pets_allowed is None:
        unknowns.append("pet policy")
    if merged.parking_available is None:
        unknowns.append("parking")
    if merged.year_built is None:
        unknowns.append("year built")

    verification = {
        "detail_verified": detail.detail_verified,
        "current_search_rank": current_rank,
        "passes_current_hard_filters": passes,
        "remaining_unknowns": unknowns,
    }
    result: dict[str, object] = {
        "listing": merged.to_dict(),
        "verification": verification,
    }

    if tool_context is not None:
        verified = tool_context.state.get(_VERIFIED_STATE_KEY, {})
        verified_map = dict(verified) if isinstance(verified, dict) else {}
        verified_map[listing_id] = result
        tool_context.state[_VERIFIED_STATE_KEY] = verified_map

    return result


root_agent = Agent(
    name="single_rental_agent",
    model=build_ordered_gemini(),
    description="Finds, verifies, and explains the best Silicon Valley rentals.",
    instruction="""
You are Keys by Friday's single rental search agent. There are no sub-agents.

Memory and search behavior:
1. Extract explicit hard constraints: supported city, state, budget, bedroom/
   bathroom bounds, required pets, and required parking.
2. Treat shorthand such as "2B2B" as minimum 2 bedrooms and minimum 2 bathrooms
   unless the user explicitly says "exactly".
3. The search_listings tool keeps the previous search requirements in ADK session
   state. For follow-up refinements, pass only values the user changed; omitted
   values are inherited. Use reset_search=True only when the user explicitly asks
   to start over or replace the whole search.
4. If the user says "cheaper" without a new number, do not invent a new hard
   budget. Keep the current budget and add "prefer cheaper" as a soft preference.
   Treat quiet, newer, modern, near transit, or similar language as soft preferences.

Candidate-first behavior:
5. For every initial or refined search, call search_listings exactly once.
6. Do NOT automatically call get_listing_details after a broad search. First show
   up to ten entries from top_10 so the user can review the candidate pool and
   refine it conversationally.
7. Keep broad-search results compact. For each candidate show rank, linked address,
   rent, beds, baths when known, property type when known, and source. Unknown
   fields must stay unknown; never invent them.
8. Do not force source diversity in the displayed ten. Deterministic ranking decides
   order; the multi-source provider supplies the candidate pool.
9. When the user adds or changes requirements, call search_listings again with only
   the changed fields and present the newly filtered/ranked top ten.
10. Use get_listing_details only when the user asks about a specific listing, asks
    to compare a small subset, or has narrowed the results enough that verification
    is useful. Never verify all ten automatically.
11. A verified candidate with passes_current_hard_filters=false must not be
    presented as satisfying the current hard constraints.

Answer format:
12. Start with one concise sentence summarizing the effective search. On a follow-up,
    briefly state which previous constraints were kept and what changed.
13. For a broad search/refinement, use `## Candidates` and list up to ten results.
    Use Markdown links in the literal form `[ADDRESS](SOURCE_URL)`. Keep each item
    concise: rank, linked address, rent, beds, baths if known, property type if
    known, and source.
14. Do not show raw scores or internal scores.
15. For a specific verified listing or small comparison, you may use `**Why it fits:**`
    and `**Tradeoffs:**`, but clearly distinguish verified facts from unknown fields.
16. Never invent listing facts, safety, commute, schools, crime, or unavailable data.
""".strip(),
    tools=[search_listings, get_listing_details],
)
