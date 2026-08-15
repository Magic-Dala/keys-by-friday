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
_RAW_CACHE_STATE_KEY = "rental_search_raw_cache"
_CACHE_SCOPE_STATE_KEY = "rental_search_cache_scope"
_CACHE_PROVIDER_STATE_KEY = "rental_search_cache_provider"
_CACHE_COMPLETE_STATE_KEY = "rental_search_cache_complete"
_CACHE_FAILED_SOURCES_STATE_KEY = "rental_search_cache_failed_sources"
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
        if key in {"query_backed_fields", "rent_is_exact", "bedrooms_is_exact"}:
            continue
        if value is not None and value != "" and value != [] and value != ():
            merged[key] = value

    if detail.rent is not None:
        merged["rent_is_exact"] = detail.rent_is_exact
    if detail.bedrooms is not None:
        merged["bedrooms_is_exact"] = detail.bedrooms_is_exact

    query_backed = list(search_listing.query_backed_fields)
    for field_name in tuple(query_backed):
        if field_name in detail.query_backed_fields:
            continue
        detail_value = (
            detail.bathrooms
            if field_name == "bathrooms_min_evidence" and detail.bathrooms is not None
            else getattr(detail, field_name, None)
        )
        if detail_value is not None:
            query_backed.remove(field_name)
            if field_name == "bathrooms_min_evidence" and detail.bathrooms is not None:
                merged["bathrooms_min_evidence"] = None
    for field_name in detail.query_backed_fields:
        if field_name not in query_backed:
            query_backed.append(field_name)
    merged["query_backed_fields"] = tuple(query_backed)
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
        return "—"
    if len(known) == 1:
        value = known[0]
        return f"{value:g}"
    return f"{known[0]:g}–{known[-1]:g}"


def _display_rent(values: list[float | None]) -> str:
    known = sorted({float(value) for value in values if value is not None})
    if not known:
        return "—"
    if len(known) == 1:
        return f"${known[0]:,.0f}"
    return f"${known[0]:,.0f}–${known[-1]:,.0f}"


def _display_bathrooms(listings: list[dict[str, object]]) -> str:
    exact = [listing.get("bathrooms") for listing in listings]
    known_exact = [float(value) for value in exact if value is not None]
    if known_exact:
        return _display_number(known_exact)
    minimums = [
        float(listing["bathrooms_min_evidence"])
        for listing in listings
        if listing.get("bathrooms_min_evidence") is not None
    ]
    if minimums:
        return f"{max(minimums):g}+"
    return "—"


def _bound_label(
    minimum: float | None, maximum: float | None, unit: str
) -> str | None:
    if minimum is not None and maximum is not None:
        if float(minimum) == float(maximum):
            return f"{minimum:g} {unit}"
        return f"{minimum:g}–{maximum:g} {unit}"
    if minimum is not None:
        return f"{minimum:g}+ {unit}"
    if maximum is not None:
        return f"≤{maximum:g} {unit}"
    return None


def _active_filters(req: SearchRequirements) -> str:
    parts = [f"{req.city}, {req.state}"]
    if req.max_rent is not None:
        parts.append(f"≤${req.max_rent:,.0f}")
    beds = _bound_label(req.min_bedrooms, req.max_bedrooms, "bd")
    baths = _bound_label(req.min_bathrooms, req.max_bathrooms, "ba")
    if beds:
        parts.append(beds)
    if baths:
        parts.append(baths)
    if req.parking_required:
        parts.append("parking")
    if req.pets_required:
        parts.append("pet-friendly")
    return " · ".join(parts)


def _short_address(address: str) -> str:
    return address.split(",", 1)[0].strip() or address


def _source_posting_text(source: dict[str, object]) -> str:
    label = str(source.get("label") or "Source")
    url = source.get("url")
    linked_label = f"[{label}]({url})" if url else label
    facts: list[str] = []
    rent = str(source.get("rent") or "—")
    beds = str(source.get("beds") or "—")
    baths = str(source.get("baths") or "—")
    if rent != "—":
        facts.append(rent)
    if beds != "—":
        facts.append(f"{beds} bd")
    if baths != "—":
        facts.append(f"{baths} ba")
    return linked_label + (f" — {' · '.join(facts)}" if facts else "")


def _compact_property_line(rank: int, display: dict[str, object]) -> str:
    sources = display.get("sources")
    source_text = ""
    if isinstance(sources, list):
        source_text = "; ".join(
            _source_posting_text(source)
            for source in sources
            if isinstance(source, dict)
        )
    return f"{rank}. **{display['address']}**" + (f" — {source_text}" if source_text else "")


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
    for key in order:
        group = groups[key]
        postings = group["postings"]
        listings = [posting["listing"] for posting in postings]
        representative = group["representative"]["listing"]
        group["source_count"] = len(group["sources"])
        group["display"] = {
            "address": _short_address(representative["address"]),
            "full_address": representative["address"],
            "rent": _display_rent([listing.get("rent") for listing in listings]),
            "beds": _display_number([listing.get("bedrooms") for listing in listings]),
            "baths": _display_bathrooms(listings),
            "sources": [
                {
                    "label": posting["source_label"],
                    "url": posting["listing"].get("source_url"),
                    "rent": _display_rent([posting["listing"].get("rent")]),
                    "beds": _display_number([posting["listing"].get("bedrooms")]),
                    "baths": _display_bathrooms([posting["listing"]]),
                }
                for posting in postings
            ],
        }
        result.append(group)

    # Cross-listed properties are intentionally displayed first. This is the
    # canonical group order used by every rank-dependent output below.
    result.sort(key=lambda group: 0 if group["source_count"] > 1 else 1)
    for rank, group in enumerate(result, start=1):
        group["rank"] = rank
    return result


def _is_narrower_or_equal(current: SearchRequirements, cached: SearchRequirements) -> bool:
    """Return True when current hard constraints are a subset of cached search scope."""
    if current.city.casefold() != cached.city.casefold():
        return False
    if current.state.upper() != cached.state.upper():
        return False

    def max_is_narrower(value: float | None, base: float | None) -> bool:
        if base is None:
            return True
        return value is not None and value <= base

    def min_is_narrower(value: float | None, base: float | None) -> bool:
        if base is None:
            return True
        return value is not None and value >= base

    if not max_is_narrower(current.max_rent, cached.max_rent):
        return False
    if not min_is_narrower(current.min_bedrooms, cached.min_bedrooms):
        return False
    if not max_is_narrower(current.max_bedrooms, cached.max_bedrooms):
        return False
    if not min_is_narrower(current.min_bathrooms, cached.min_bathrooms):
        return False
    if not max_is_narrower(current.max_bathrooms, cached.max_bathrooms):
        return False
    if cached.pets_required and not current.pets_required:
        return False
    if cached.parking_required and not current.parking_required:
        return False
    return True


def _same_hard_scope(left: SearchRequirements, right: SearchRequirements) -> bool:
    return _is_narrower_or_equal(left, right) and _is_narrower_or_equal(right, left)


def _cached_listings(value: object) -> list[Listing]:
    if not isinstance(value, list):
        return []
    result: list[Listing] = []
    for item in value:
        if isinstance(item, dict):
            try:
                result.append(_listing_from_dict(item))
            except (TypeError, ValueError):
                continue
    return result


def _cached_candidate_listings(value: object) -> list[Listing]:
    """Recover prior ranked candidates from sessions created before raw caching."""
    if not isinstance(value, list):
        return []
    result: list[Listing] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        listing_payload = item.get("listing")
        if not isinstance(listing_payload, dict):
            continue
        try:
            result.append(_listing_from_dict(listing_payload))
        except (TypeError, ValueError):
            continue
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
    force_refresh: bool = False,
    tool_context: Optional[ToolContext] = None,
) -> dict[str, object]:
    """Search rentals, remembering omitted requirements within this ADK session.

    On a follow-up search, pass only requirements the user changed. Omitted values
    inherit from the previous search in the same session. Narrower/equal follow-ups
    reuse the last raw session cache before calling the provider again. Set
    reset_search=True only when the user explicitly wants to start over; set
    force_refresh=True only when the user explicitly asks for fresh data. Broad
    searches return all matching property_groups; detail verification is on demand.
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

    cached_scope = None
    cached_raw: list[Listing] = []
    cached_provider = None
    cached_complete = False
    cached_failed_sources: tuple[str, ...] = ()
    migrated_candidate_cache = False
    if tool_context is not None:
        cached_scope = _requirements_from_dict(
            tool_context.state.get(_CACHE_SCOPE_STATE_KEY)
        )
        cached_raw = _cached_listings(tool_context.state.get(_RAW_CACHE_STATE_KEY))
        provider_value = tool_context.state.get(_CACHE_PROVIDER_STATE_KEY)
        cached_provider = str(provider_value) if provider_value else None
        cached_complete = tool_context.state.get(_CACHE_COMPLETE_STATE_KEY) is True
        failed_value = tool_context.state.get(_CACHE_FAILED_SOURCES_STATE_KEY)
        if isinstance(failed_value, (list, tuple)):
            cached_failed_sources = tuple(str(item) for item in failed_value if str(item))

        # Sessions created before raw-cache support still have the full ranked
        # candidate set from their previous search. For narrower refinements,
        # that set is safe to use as a bounded fallback cache and avoids burning
        # another multi-source RealtyAPI search just to migrate the session.
        if cached_scope is None and previous is not None and not reset_search:
            legacy_candidates = _cached_candidate_listings(
                tool_context.state.get(_CANDIDATES_STATE_KEY)
            )
            if legacy_candidates:
                cached_scope = previous
                cached_raw = legacy_candidates
                migrated_candidate_cache = True
                # Legacy sessions have no completeness evidence. Refresh once
                # rather than guessing that a partial provider result was complete.
                cached_complete = False
                if cached_provider is None:
                    cached_provider = (
                        "realtyapi-multi"
                        if any(item.source.startswith("realtyapi-") for item in legacy_candidates)
                        else "session-cache"
                    )

    use_cache = (
        not reset_search
        and not force_refresh
        and cached_scope is not None
        and cached_complete
        and _is_narrower_or_equal(req, cached_scope)
    )
    normalized = cached_raw if use_cache else []
    ranked = (
        filter_and_rank(normalized, req, top_n=max(1, len(normalized)))
        if use_cache
        else []
    )

    # If a stricter refinement has no deterministic matches in the cached raw
    # postings, query the provider once with the complete new constraints. This
    # lets source-side filters provide evidence that the broad cache did not carry.
    needs_provider = not use_cache or (
        not ranked
        and cached_scope is not None
        and not _same_hard_scope(req, cached_scope)
    )
    provider_search_performed = False
    refresh_reason = "session_cache"
    provider_name = cached_provider or "unknown"
    search_complete = cached_complete
    failed_sources = list(cached_failed_sources)
    if needs_provider:
        provider = get_provider()
        normalized = provider.search(req)
        provider_health = provider.health()
        provider_name = str(provider_health["provider"])
        search_complete = provider_health.get("search_complete") is not False
        failed_value = provider_health.get("failed_sources", [])
        failed_sources = (
            [str(item) for item in failed_value if str(item)]
            if isinstance(failed_value, (list, tuple))
            else []
        )
        provider_search_performed = True
        if force_refresh:
            refresh_reason = "force_refresh"
        elif reset_search or cached_scope is None:
            refresh_reason = "initial_or_reset_search"
        elif not cached_complete:
            refresh_reason = "incomplete_cache"
        elif not _is_narrower_or_equal(req, cached_scope):
            refresh_reason = "expanded_or_changed_scope"
        else:
            refresh_reason = "cache_had_no_matches"
        ranked = filter_and_rank(normalized, req, top_n=max(1, len(normalized)))
        if tool_context is not None:
            tool_context.state[_RAW_CACHE_STATE_KEY] = [item.to_dict() for item in normalized]
            tool_context.state[_CACHE_SCOPE_STATE_KEY] = _requirements_to_dict(req)
            tool_context.state[_CACHE_PROVIDER_STATE_KEY] = provider_name
            tool_context.state[_CACHE_COMPLETE_STATE_KEY] = search_complete
            tool_context.state[_CACHE_FAILED_SOURCES_STATE_KEY] = failed_sources

    data_source = (
        "session_cache_migrated"
        if migrated_candidate_cache and not provider_search_performed
        else (
            "session_cache"
            if not provider_search_performed
            else ("realtyapi" if provider_name.startswith("realtyapi") else provider_name)
        )
    )

    if migrated_candidate_cache and tool_context is not None and not provider_search_performed:
        tool_context.state[_RAW_CACHE_STATE_KEY] = [item.to_dict() for item in cached_raw]
        tool_context.state[_CACHE_SCOPE_STATE_KEY] = _requirements_to_dict(cached_scope)
        tool_context.state[_CACHE_PROVIDER_STATE_KEY] = provider_name
        tool_context.state[_CACHE_COMPLETE_STATE_KEY] = cached_complete
        tool_context.state[_CACHE_FAILED_SOURCES_STATE_KEY] = list(cached_failed_sources)

    property_groups = _group_ranked_properties(ranked)
    representative_payload = [group["representative"] for group in property_groups]
    candidate_payload: list[dict[str, object]] = []
    for group in property_groups:
        for posting in group["postings"]:
            candidate = dict(posting)
            candidate["current_search_rank"] = group["rank"]
            candidate_payload.append(candidate)

    cross_listed_groups = [group for group in property_groups if group["source_count"] > 1]
    other_groups = [group for group in property_groups if group["source_count"] <= 1]
    display_sections = {
        "cross_listed": [
            _compact_property_line(int(group["rank"]), group["display"])
            for group in cross_listed_groups
        ],
        "other_matches": [
            _compact_property_line(int(group["rank"]), group["display"])
            for group in other_groups
        ],
    }
    verification_candidates = [
        {
            "rank": group["rank"],
            "listing_id": group["representative"]["listing"]["id"],
            "address": group["representative"]["listing"]["address"],
        }
        for group in property_groups[:3]
    ]

    if tool_context is not None:
        tool_context.state[_REQUIREMENTS_STATE_KEY] = _requirements_to_dict(req)
        tool_context.state[_CANDIDATES_STATE_KEY] = candidate_payload
        tool_context.state[_VERIFIED_STATE_KEY] = {}

    return {
        "provider": provider_name,
        "data_source": data_source,
        "provider_search_performed": provider_search_performed,
        "search_complete": search_complete,
        "failed_sources": failed_sources,
        "refresh_reason": refresh_reason,
        "active_filters": _active_filters(req),
        "matched_count": len(property_groups),
        "posting_count": sum(len(group["postings"]) for group in property_groups),
        "property_groups": property_groups,
        "display_sections": display_sections,
        "cross_listed_count": len(cross_listed_groups),
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
            rank_value = candidate.get("current_search_rank")
            current_rank = int(rank_value) if isinstance(rank_value, (int, float)) else index + 1
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
        "backend_listing": merged.to_backend_dict(),
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
5. For every initial or refined search, call search_listings exactly once. The tool is
   cache-first: narrower/equal refinements reuse session data and do not call RealtyAPI
   when cached candidates can satisfy the new hard constraints.
6. Pass force_refresh=True only when the user explicitly asks to refresh, search again
   from the source, or fetch fresh listings. Do NOT use it for normal refinements.
7. Do NOT automatically call get_listing_details after a broad search.
8. Broad searches must show every entry in property_groups, not only top_10.
   Each property group represents the same physical address/unit across sources.
9. For each property group, show the property once, then list every source posting
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
13. Start every broad-search/refinement answer with exactly these two short lines:
    Start with `**Active filters:** ` followed by the exact `active_filters` value from
    the latest search_listings tool result. Then show counts using matched_count,
    posting_count, and cross_listed_count, for example:
    `25 properties · 27 postings · 1 cross-listed`. Do not treat active_filters as
    an ADK context variable; read it only from the tool result.
14. Do NOT use a Markdown table for broad search results.
15. If display_sections.cross_listed is non-empty, show `## Cross-listed` first and
    copy every precomputed line from that list verbatim. These are the same physical
    property/unit found on multiple sites and are the highest-value discovery results.
16. Then show `## Other matches` and copy every precomputed line from
    display_sections.other_matches verbatim. Do not omit results.
17. Each precomputed line is already complete and compact: short street/unit address,
    then each linked source with that source's own known rent and beds/baths. Preserve
    those source-to-fact mappings verbatim. Do not expand a line into bullets,
    subheadings, explanations, or repeated city/state/ZIP text.
18. Do not print `Unknown`; missing broad-search facts are intentionally omitted from
    the line. Do not expose raw scores, internal IDs, provider names, or internal
    source names such as `realtyapi-zillow`.
19. After the result list, add only one brief sentence inviting the user to refine by
    budget, beds/baths, parking, pets, source, or a specific property.
20. Never invent listing facts, safety, commute, schools, crime, or unavailable data.

""".strip(),
    tools=[search_listings, get_listing_details],
)
