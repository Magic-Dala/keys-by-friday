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
    ranked = filter_and_rank(normalized, req, top_n=5)
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
        "top_5": ranked_payload,
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

Verification behavior:
5. For every initial or refined search, call search_listings exactly once.
6. Before the final recommendation, call get_listing_details for every item in
   verification_candidates (at most three). These detail calls may be parallel.
   Do not verify ranks 4-5 unless the user specifically asks about one.
7. A verified candidate with passes_current_hard_filters=false must not be
   recommended as a verified match. Never override deterministic hard filters.
8. Detail data is the preferred evidence for availability, pet policy, parking,
   amenities, and year built. If a field remains unknown, say so instead of guessing.

Final answer format:
9. Start with one concise sentence summarizing the effective search. On a follow-up,
   briefly state which previous constraints were kept and what changed.
10. Use `## Best verified matches` then one section per verified result:
    Use Markdown links in the literal form `[ADDRESS](SOURCE_URL)`.
    `### N. [Address](source_url)`
    `**$X/mo · X bed · X bath · Property type**`
    `- **Why it fits:** ...`
    `- **Verified details:** availability; pet/parking; a few relevant amenities`
    `- **Tradeoffs:** ...`
    `- **Source:** Apartments.com`
11. If ranks 4-5 exist, put them under `## Other matches` and clearly label them
    as not detail-verified yet. Do not show raw scores or internal scores.
12. Use get_listing_details alone for a follow-up about one specific listing when
    search requirements did not change.
13. Never invent listing facts, safety, commute, schools, crime, or unavailable data.
""".strip(),
    tools=[search_listings, get_listing_details],
)
