from __future__ import annotations

from dataclasses import fields
import os
import re
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


def _property_group_key(listing: Listing) -> tuple[str, str, str]:
    """Conservative property identity for cross-source grouping.

    Keep unit identifiers in the key so Apt 2 and Apt 3 never collapse together,
    while normalizing common address/source formatting differences.
    """
    street = listing.address.split(",", 1)[0].strip().casefold()
    street = re.sub(
        r"\b(?:apartment|apt|unit)\s*#?\s*([a-z0-9-]+)\b",
        r" #\1",
        street,
    )
    street = re.sub(r"#\s+([a-z0-9-]+)", r"#\1", street)
    replacements = {
        "street": "st",
        "avenue": "ave",
        "road": "rd",
        "drive": "dr",
        "boulevard": "blvd",
        "lane": "ln",
        "court": "ct",
        "highway": "hwy",
    }
    tokens = re.findall(r"[a-z0-9#-]+", street)
    normalized_street = " ".join(replacements.get(token, token) for token in tokens)
    if not normalized_street:
        normalized_street = f"listing:{listing.source}:{listing.id}"
    return (
        normalized_street,
        listing.city.casefold().strip(),
        listing.state.upper().strip(),
    )


_SOURCE_LABELS = {
    "realtyapi-apartments": "Apartments.com",
    "realtyapi-zillow": "Zillow",
    "realtyapi-realtor": "Realtor.com",
}


def _source_label(source: str) -> str:
    return _SOURCE_LABELS.get(source, source)


def _display_number(values: list[float | None]) -> str:
    known = sorted({float(value) for value in values if value is not None})
    if not known:
        return "Unknown"
    if len(known) == 1:
        value = known[0]
        return f"{value:g}"
    return f"{known[0]:g}–{known[-1]:g}"


def _display_rent(values: list[float | None]) -> str:
    known = sorted({float(value) for value in values if value is not None})
    if not known:
        return "Unknown"
    if len(known) == 1:
        return f"${known[0]:,.0f}"
    return f"${known[0]:,.0f}–${known[-1]:,.0f}"


def _group_ranked_properties(ranked: list[object]) -> list[dict[str, object]]:
    groups: dict[tuple[str, str, str], dict[str, object]] = {}
    seen_sources: dict[tuple[str, str, str], set[str]] = {}
    order: list[tuple[str, str, str]] = []
    for item in ranked:
        listing = item.listing
        key = _property_group_key(listing)
        if key not in groups:
            groups[key] = {
                "representative": item.to_dict(),
                "postings": [],
                "sources": [],
            }
            seen_sources[key] = set()
            order.append(key)
        # The same source can emit duplicate rows for the same physical unit.
        # Keep its highest-ranked posting only; cross-source postings remain separate.
        if listing.source in seen_sources[key]:
            continue
        seen_sources[key].add(listing.source)
        posting = item.to_dict()
        posting["source_label"] = _source_label(listing.source)
        group = groups[key]
        group["postings"].append(posting)
        group["sources"].append(listing.source)

    result: list[dict[str, object]] = []
    for rank, key in enumerate(order, start=1):
        group = groups[key]
        postings = group["postings"]
        listings = [posting["listing"] for posting in postings]
        representative = group["representative"]["listing"]
        group["rank"] = rank
        group["source_count"] = len(group["sources"])
        group["display"] = {
            "address": representative["address"],
            "rent": _display_rent([listing.get("rent") for listing in listings]),
            "beds": _display_number([listing.get("bedrooms") for listing in listings]),
            "baths": _display_number([listing.get("bathrooms") for listing in listings]),
            "sources": [
                {
                    "label": posting["source_label"],
                    "url": posting["listing"].get("source_url"),
                }
                for posting in postings
            ],
        }
        result.append(group)
    return result


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
    only when the user explicitly wants to start over. Broad searches return all
    matching property_groups; detail verification is on demand.
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
    ranked = filter_and_rank(normalized, req, top_n=max(1, len(normalized)))
    ranked_payload = [item.to_dict() for item in ranked]
    property_groups = _group_ranked_properties(ranked)
    representative_payload = [group["representative"] for group in property_groups]
    property_rows = []
    for group in property_groups:
        display = dict(group["display"])
        display["sources"] = " · ".join(
            f"[{source['label']}]({source['url']})" if source.get("url") else source["label"]
            for source in group["display"]["sources"]
        )
        property_rows.append(display | {"rank": group["rank"]})
    verification_candidates = [
        {
            "rank": index + 1,
            "listing_id": item["listing"]["id"],
            "address": item["listing"]["address"],
        }
        for index, item in enumerate(representative_payload[:3])
    ]

    if tool_context is not None:
        tool_context.state[_REQUIREMENTS_STATE_KEY] = _requirements_to_dict(req)
        tool_context.state[_CANDIDATES_STATE_KEY] = ranked_payload
        tool_context.state[_VERIFIED_STATE_KEY] = {}

    return {
        "provider": provider.health()["provider"],
        "matched_count": len(property_groups),
        "posting_count": sum(len(group["postings"]) for group in property_groups),
        "property_groups": property_groups,
        "property_rows": property_rows,
        "top_10": representative_payload[:10],
        "top_5": representative_payload[:5],
        "soft_preferences_unverified": list(req.soft_preferences),
        "effective_requirements": _requirements_to_dict(req),
        "memory_used": previous is not None and not reset_search,
        "verification_candidates": verification_candidates,
        "verification_policy": (
            "Do not automatically verify broad search results. Use "
            "get_listing_details only when the user asks about a specific "
            "property/source posting or narrows the candidate set."
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
6. Do NOT automatically call get_listing_details after a broad search.
7. Broad searches must show every entry in property_groups, not only top_10.
   Each property group represents the same physical address/unit across sources.
8. For each property group, show the property once, then list every source posting
   underneath it. Preserve source-specific rent, beds, baths, URL, and source name.
   If sources disagree, show their values separately rather than inventing a merged fact.
9. Never collapse different unit numbers in the same building. A group may contain
   Zillow, Realtor.com, Apartments.com, or any subset that actually returned it.
10. When the user adds or changes requirements, call search_listings again with only
    the changed fields and show all newly matching property_groups.
11. Use get_listing_details only when the user asks about a specific property/source
    posting, asks to compare a small subset, or has narrowed results enough that
    verification is useful. Never verify the whole candidate set automatically.
12. A verified candidate with passes_current_hard_filters=false must not be presented
    as satisfying the current hard constraints.

Answer format:
13. Start with one concise sentence summarizing the effective search and report the
    unique property count (matched_count). Do not narrate every row.
14. For a broad search/refinement, render every entry in property_rows in ONE compact
    Markdown table with exactly these columns:
    `| # | Property | Rent | Beds | Baths | Sources |`
15. Use the precomputed property_rows display values exactly. The `sources` field is
    already a Markdown string such as `[Zillow](url) · [Apartments.com](url)`. Copy it
    into the Sources cell; do not rewrite source names or expose internal names such as
    `realtyapi-zillow` or `realtyapi-realtor`.
16. Do not create a separate heading or bullet list for each property. Keep the full
    result set scannable in one table even when there are 20+ properties.
17. If multiple sources disagree on rent/beds/baths, the precomputed display value may
    be a range. Do not choose one source as truth during a broad search.
18. Do not show raw scores, internal IDs, provider names, or internal source names.
19. Never invent listing facts, safety, commute, schools, crime, or unavailable data.

""".strip(),
    tools=[search_listings, get_listing_details],
)
