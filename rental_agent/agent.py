from __future__ import annotations

from dataclasses import fields
from datetime import datetime
import os
import re
from typing import Any, Optional

from dotenv import load_dotenv
from google.adk import Agent
from google.adk.tools.tool_context import ToolContext

from rental_agent.commute import (
    CommuteOrigin,
    CommuteResult,
    RouteDetail,
    get_commute_service,
    normalize_travel_mode,
)
from rental_agent.llm import build_ordered_gemini
from rental_agent.models import Listing, SearchRequirements
from rental_agent.pipeline import filter_and_rank, passes_hard_filters
from rental_agent.providers import get_provider
from rental_agent.us_states import normalize_us_state

load_dotenv()
if os.getenv("GEMINI_API_KEY") and not os.getenv("GOOGLE_API_KEY"):
    os.environ["GOOGLE_API_KEY"] = os.environ["GEMINI_API_KEY"]
os.environ.setdefault("GOOGLE_GENAI_USE_VERTEXAI", "FALSE")

_REQUIREMENTS_STATE_KEY = "rental_search_requirements"
_CANDIDATES_STATE_KEY = "rental_last_candidates"
_RAW_CACHE_STATE_KEY = "rental_search_raw_cache"
_CACHE_SCOPE_STATE_KEY = "rental_search_cache_scope"
_CACHE_PROVIDER_STATE_KEY = "rental_search_cache_provider"
_CACHE_COMPLETE_STATE_KEY = "rental_search_cache_complete"
_CACHE_FAILED_SOURCES_STATE_KEY = "rental_search_cache_failed_sources"
_VERIFIED_STATE_KEY = "rental_verified_details"
_SEARCH_RESULT_LIMIT = 20
_COMPARISON_LIMIT = 4
_ACTIVITY_SCHEMA = "rental.agent_activity.v1"
_CANONICAL_LISTING_SCHEMA = "kbf.canonical-listing.v1"
_CANONICAL_COMPARISON_SCHEMA = "kbf.canonical-comparison.v1"


def _agent_activity(
    *,
    operation: str,
    stage: str,
    status: str,
    stage_outcomes: list[tuple[str, str]],
    facts: dict[str, object],
) -> dict[str, object]:
    """Return deterministic execution metadata for backend/frontend integrations.

    This intentionally contains no UI copy, percentages, timestamps, or model
    reasoning. ADK tool-call events can represent operation start; this payload
    describes only execution facts known when the tool returns.
    """
    return {
        "schema": _ACTIVITY_SCHEMA,
        "operation": operation,
        "stage": stage,
        "status": status,
        "completed_stages": [
            name for name, outcome in stage_outcomes if outcome == "completed"
        ],
        "stage_outcomes": [
            {"stage": name, "status": outcome} for name, outcome in stage_outcomes
        ],
        "facts": dict(facts),
    }


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
        "commute_destination": req.commute_destination,
        "max_commute_minutes": req.max_commute_minutes,
        "commute_travel_mode": req.commute_travel_mode,
        "soft_preferences": list(req.soft_preferences),
        "limit": req.limit,
    }


def _requirements_from_dict(value: object) -> SearchRequirements | None:
    if not isinstance(value, dict) or not value.get("city"):
        return None
    return SearchRequirements(
        city=str(value["city"]),
        state=normalize_us_state(str(value.get("state") or "CA")),
        max_rent=value.get("max_rent"),
        min_bedrooms=value.get("min_bedrooms"),
        max_bedrooms=value.get("max_bedrooms"),
        min_bathrooms=value.get("min_bathrooms"),
        max_bathrooms=value.get("max_bathrooms"),
        pets_required=bool(value.get("pets_required", False)),
        parking_required=bool(value.get("parking_required", False)),
        commute_destination=(
            str(value["commute_destination"])
            if value.get("commute_destination")
            else None
        ),
        max_commute_minutes=value.get("max_commute_minutes"),
        commute_travel_mode=(
            str(value["commute_travel_mode"])
            if value.get("commute_travel_mode")
            else None
        ),
        soft_preferences=tuple(
            str(item) for item in (value.get("soft_preferences") or []) if str(item)
        ),
        limit=min(max(1, int(value.get("limit") or _SEARCH_RESULT_LIMIT)), _SEARCH_RESULT_LIMIT),
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
    commute_destination: str | None,
    max_commute_minutes: float | None,
    commute_travel_mode: str | None,
    clear_commute: bool,
    soft_preferences: str,
    reset_search: bool,
) -> SearchRequirements:
    prior = None if reset_search else previous
    effective_city = city.strip() or (prior.city if prior else "")
    if not effective_city:
        raise ValueError("A city is required for the first rental search.")
    effective_state = normalize_us_state(state) or (prior.state if prior else "CA")

    def numeric(value: float | None, prior_value: float | None) -> float | None:
        explicit = _positive_number(value)
        return explicit if explicit is not None else prior_value

    prior_soft = prior.soft_preferences if prior else ()
    destination = None if clear_commute else (
        commute_destination.strip()
        if commute_destination and commute_destination.strip()
        else (prior.commute_destination if prior else None)
    )
    commute_mode = None if clear_commute else normalize_travel_mode(commute_travel_mode)
    if (
        not clear_commute
        and commute_mode is None
        and prior is not None
        and not commute_travel_mode
    ):
        commute_mode = prior.commute_travel_mode
    return SearchRequirements(
        city=effective_city,
        state=effective_state,
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
        commute_destination=destination,
        max_commute_minutes=(
            None
            if clear_commute
            else numeric(max_commute_minutes, prior.max_commute_minutes if prior else None)
        ),
        commute_travel_mode=commute_mode,
        soft_preferences=_merge_soft_preferences(
            prior_soft, soft_preferences, reset_search=reset_search
        ),
        limit=_SEARCH_RESULT_LIMIT,
    )


def _listing_from_dict(value: dict[str, Any]) -> Listing:
    names = {item.name for item in fields(Listing)}
    payload = {key: value.get(key) for key in names if key in value}
    return Listing(**payload)


def _try_listing_from_dict(value: object) -> Listing | None:
    if not isinstance(value, dict):
        return None
    try:
        return _listing_from_dict(value)
    except (TypeError, ValueError):
        return None


def _canonical_datetime(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _listing_from_canonical_v1(value: dict[str, Any]) -> Listing:
    """Restore the frozen canonical listing contract without inventing facts."""
    if value.get("schemaVersion") != _CANONICAL_LISTING_SCHEMA:
        raise ValueError(f"Expected {_CANONICAL_LISTING_SCHEMA} input.")

    def section(name: str) -> dict[str, Any]:
        current = value.get(name)
        return current if isinstance(current, dict) else {}

    identity = section("identity")
    identifier = identity.get("id")
    if not isinstance(identifier, str) or not identifier.strip():
        raise ValueError("Canonical listing identity.id is required.")

    location = section("location")
    pricing = section("pricing")
    property_data = section("property")
    availability = section("availability")
    policies = section("policies")
    features = section("features")
    media = section("media")
    contact = section("contact")
    source = section("source")
    evidence = section("evidence")

    query_backed_paths = evidence.get("queryBackedFields")
    query_backed = query_backed_paths if isinstance(query_backed_paths, list) else []
    query_backed_reverse = {
        "property.bathrooms": "bathrooms",
        "property.bathroomsMinEvidence": "bathrooms_min_evidence",
        "policies.petsAllowed": "pets_allowed",
        "policies.parkingAvailable": "parking_available",
    }

    rent = pricing.get("rent")
    rent_min = pricing.get("rentMin")
    rent_max = pricing.get("rentMax")
    bedrooms = property_data.get("bedrooms")
    bedrooms_min = property_data.get("bedroomsMin")
    bedrooms_max = property_data.get("bedroomsMax")

    return Listing(
        id=identifier,
        address=str(location.get("address") or ""),
        city=str(location.get("city") or ""),
        state=str(location.get("state") or ""),
        zip_code=location.get("zipCode"),
        rent=rent,
        bedrooms=bedrooms,
        bathrooms=property_data.get("bathrooms"),
        rent_is_exact=(
            True if rent is not None else False if rent_min is not None or rent_max is not None else None
        ),
        bedrooms_is_exact=(
            True
            if bedrooms is not None
            else False
            if bedrooms_min is not None or bedrooms_max is not None
            else None
        ),
        source_listing_id=identity.get("sourceListingId"),
        country_code=location.get("countryCode"),
        latitude=location.get("latitude"),
        longitude=location.get("longitude"),
        primary_image_url=media.get("primaryImageUrl"),
        rent_min=rent_min,
        rent_max=rent_max,
        bedrooms_min=bedrooms_min,
        bedrooms_max=bedrooms_max,
        days_on_market=availability.get("daysOnMarket"),
        property_type=property_data.get("propertyType"),
        square_footage=property_data.get("squareFootage"),
        status=availability.get("status"),
        listed_date=_canonical_datetime(availability.get("listedAt")),
        last_seen_date=_canonical_datetime(availability.get("lastSeenAt")),
        pets_allowed=policies.get("petsAllowed"),
        parking_available=policies.get("parkingAvailable"),
        source_url=source.get("url"),
        source=str(source.get("provider") or "unknown"),
        property_name=identity.get("propertyName"),
        availability=availability.get("availabilityText"),
        year_built=property_data.get("yearBuilt"),
        amenities=tuple(str(item) for item in (features.get("amenities") or [])),
        pet_policy=policies.get("petPolicy"),
        parking_policy=policies.get("parkingPolicy"),
        detail_verified=bool(evidence.get("detailVerified", False)),
        bathrooms_min_evidence=property_data.get("bathroomsMinEvidence"),
        phone=contact.get("phone"),
        rating=property_data.get("rating"),
        multimedia_url=media.get("multimediaUrl"),
        virtual_tour_url=media.get("virtualTourUrl"),
        has_availability=availability.get("hasAvailability"),
        is_multifamily=property_data.get("isMultifamily"),
        attachment_count=media.get("attachmentCount"),
        specialties=tuple(str(item) for item in (features.get("specialties") or [])),
        property_manager_name=contact.get("propertyManagerName"),
        property_manager_company_id=contact.get("propertyManagerCompanyId"),
        has_lead_email=contact.get("hasLeadEmail"),
        description=property_data.get("description"),
        rent_deals_count=features.get("rentDealsCount"),
        query_backed_fields=tuple(
            query_backed_reverse.get(str(path), str(path)) for path in query_backed
        ),
    )


def _commute_from_dict(value: object) -> CommuteResult | None:
    if not isinstance(value, dict) or not value.get("destination"):
        return None
    destination_place_id = value.get("destination_place_id")
    if destination_place_id is None:
        destination_place_id = value.get("destinationPlaceId")
    duration = value.get("duration_minutes")
    if duration is None:
        duration = value.get("durationMinutes")
    distance = value.get("distance_meters")
    if distance is None:
        distance = value.get("distanceMeters")
    routing_preference = value.get("routing_preference")
    if routing_preference is None:
        routing_preference = value.get("routingPreference")
    return CommuteResult(
        destination=str(value["destination"]),
        destination_place_id=(
            str(destination_place_id) if destination_place_id else None
        ),
        mode=str(value["mode"]) if value.get("mode") else None,
        duration_minutes=(
            int(duration) if isinstance(duration, (int, float)) else None
        ),
        distance_meters=(
            int(distance) if isinstance(distance, (int, float)) else None
        ),
        status=str(value.get("status") or "unknown"),
        routing_preference=(
            str(routing_preference) if routing_preference else None
        ),
    )


def _merge_listing_detail(search_listing: Listing | None, detail: Listing) -> Listing:
    if search_listing is None:
        return detail
    merged = search_listing.to_dict()
    for key, value in detail.to_dict().items():
        if key in {"id", "query_backed_fields", "rent_is_exact", "bedrooms_is_exact"}:
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
    if req.commute_destination and req.max_commute_minutes is not None:
        mode = f" {req.commute_travel_mode}" if req.commute_travel_mode else ""
        parts.append(
            f"≤{req.max_commute_minutes:g} min{mode} to {req.commute_destination}"
        )
    return " · ".join(parts)


def _compute_commutes(
    listings: list[Listing], req: SearchRequirements
) -> dict[str, CommuteResult]:
    if req.max_commute_minutes is None or not req.commute_destination:
        return {}
    mode = normalize_travel_mode(req.commute_travel_mode)
    results: dict[str, CommuteResult] = {}
    for listing in listings:
        if listing.latitude is None or listing.longitude is None:
            results[listing.id] = CommuteResult(
                destination=req.commute_destination,
                mode=mode,
                status="unknown",
            )
    if mode is None:
        for listing in listings:
            results.setdefault(
                listing.id,
                CommuteResult(
                    destination=req.commute_destination,
                    mode=None,
                    status="unknown",
                ),
            )
        return results
    origins = [
        CommuteOrigin(
            listing_id=listing.id,
            latitude=listing.latitude,
            longitude=listing.longitude,
        )
        for listing in listings
        if listing.latitude is not None and listing.longitude is not None
    ]
    results.update(
        get_commute_service().compute_commutes(
            origins,
            destination=req.commute_destination,
            mode=mode,
        )
    )
    return results


def _commute_summary(
    req: SearchRequirements,
    commutes: dict[str, CommuteResult],
) -> dict[str, object]:
    if req.max_commute_minutes is None:
        return {
            "status": "not_requested",
            "evaluated_count": 0,
            "available_count": 0,
            "unavailable_count": 0,
            "unknown_count": 0,
            "within_limit_count": 0,
            "over_limit_count": 0,
        }
    values = list(commutes.values())
    available = [item for item in values if item.status == "available"]
    unavailable_count = sum(item.status == "unavailable" for item in values)
    unknown_count = sum(item.status == "unknown" for item in values)
    within_limit_count = sum(
        item.duration_minutes is not None
        and item.duration_minutes <= req.max_commute_minutes
        for item in available
    )
    over_limit_count = sum(
        item.duration_minutes is not None
        and item.duration_minutes > req.max_commute_minutes
        for item in available
    )
    if values and len(available) == len(values):
        status = "available"
    elif available:
        status = "partial"
    elif unavailable_count:
        status = "unavailable"
    else:
        status = "unknown"
    return {
        "status": status,
        "evaluated_count": len(values),
        "available_count": len(available),
        "unavailable_count": unavailable_count,
        "unknown_count": unknown_count,
        "within_limit_count": within_limit_count,
        "over_limit_count": over_limit_count,
    }


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
    commute_destination: str | None = None,
    max_commute_minutes: float | None = None,
    commute_travel_mode: str | None = None,
    clear_commute: bool = False,
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
        commute_destination=commute_destination,
        max_commute_minutes=max_commute_minutes,
        commute_travel_mode=commute_travel_mode,
        clear_commute=clear_commute,
        soft_preferences=soft_preferences,
        reset_search=reset_search,
    )

    missing_commute_requirements: list[str] = []
    if req.max_commute_minutes is not None:
        if not req.commute_destination:
            missing_commute_requirements.append("commute_destination")
        if not req.commute_travel_mode:
            missing_commute_requirements.append("commute_travel_mode")
    if missing_commute_requirements:
        if tool_context is not None:
            tool_context.state[_REQUIREMENTS_STATE_KEY] = _requirements_to_dict(req)
        return {
            "activity": _agent_activity(
                operation="search_listings",
                stage="requirements",
                status="requires_input",
                stage_outcomes=[("requirements", "requires_input")],
                facts={
                    "provider_search_performed": False,
                    "missing_requirements": list(missing_commute_requirements),
                },
            ),
            "status": "requires_input",
            "missing_requirements": missing_commute_requirements,
            "provider": "not_called",
            "data_source": "none",
            "provider_search_performed": False,
            "search_complete": True,
            "failed_sources": [],
            "refresh_reason": "missing_commute_requirement",
            "active_filters": _active_filters(req),
            "matched_count": 0,
            "posting_count": 0,
            "property_groups": [],
            "display_sections": {"cross_listed": [], "other_matches": []},
            "cross_listed_count": 0,
            "top_10": [],
            "top_5": [],
            "soft_preferences_unverified": list(req.soft_preferences),
            "commute_evaluations": {},
            "commute_summary": {
                "status": "requires_input",
                "evaluated_count": 0,
                "available_count": 0,
                "unavailable_count": 0,
                "unknown_count": 0,
                "within_limit_count": 0,
                "over_limit_count": 0,
            },
            "effective_requirements": _requirements_to_dict(req),
            "memory_used": previous is not None and not reset_search,
            "verification_candidates": [],
        }

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
        cached_raw = _cached_listings(tool_context.state.get(_RAW_CACHE_STATE_KEY))[:_SEARCH_RESULT_LIMIT]
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
            )[:_SEARCH_RESULT_LIMIT]
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
    normalized = cached_raw[:_SEARCH_RESULT_LIMIT] if use_cache else []
    commutes = _compute_commutes(normalized, req) if use_cache else {}
    ranked = (
        filter_and_rank(
            normalized,
            req,
            top_n=max(1, len(normalized)),
            commutes=commutes,
        )
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
        normalized = provider.search(req)[:_SEARCH_RESULT_LIMIT]
        provider_health = provider.health()
        provider_name = str(provider_health["provider"])
        failed_value = provider_health.get("failed_sources", [])
        failed_sources = (
            [str(item) for item in failed_value if str(item)]
            if isinstance(failed_value, (list, tuple))
            else []
        )
        search_complete = (
            provider_health.get("search_complete") is not False and not failed_sources
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
        commutes = _compute_commutes(normalized, req)
        ranked = filter_and_rank(
            normalized,
            req,
            top_n=max(1, len(normalized)),
            commutes=commutes,
        )
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

    commute_summary = _commute_summary(req, commutes)
    stage_outcomes: list[tuple[str, str]] = [("requirements", "completed")]
    if provider_search_performed:
        stage_outcomes.append(
            ("listing_search", "completed" if search_complete else "partial")
        )
    else:
        stage_outcomes.append(("session_reuse", "completed"))
    if req.max_commute_minutes is not None:
        stage_outcomes.append(
            (
                "commute_check",
                "completed" if commute_summary["status"] == "available" else "partial",
            )
        )
    stage_outcomes.append(("hard_filter", "completed"))
    activity_status = (
        "partial"
        if any(outcome == "partial" for _, outcome in stage_outcomes)
        else "completed"
    )

    return {
        "activity": _agent_activity(
            operation="search_listings",
            stage="listing_search" if provider_search_performed else "session_reuse",
            status=activity_status,
            stage_outcomes=stage_outcomes,
            facts={
                "provider_search_performed": provider_search_performed,
                "data_source": data_source,
                "search_complete": search_complete,
                "failed_source_count": len(failed_sources),
                "matched_count": len(property_groups),
                "posting_count": sum(len(group["postings"]) for group in property_groups),
            },
        ),
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
        "commute_evaluations": {
            listing_id: commute.to_dict() for listing_id, commute in commutes.items()
        },
        "commute_summary": commute_summary,
        "effective_requirements": _requirements_to_dict(req),
        "memory_used": previous is not None and not reset_search,
        "verification_candidates": verification_candidates,
        "verification_policy": (
            "Do not automatically verify broad search results. Use "
            "get_listing_details only when the user asks about a specific "
            "property/source posting or narrows the candidate set."
        ),
    }


def _route_details_from_state(
    listing_id: str,
    destination: str,
    travel_mode: str,
    state: object,
) -> dict[str, object]:
    state_get = getattr(state, "get", None)
    req = (
        _requirements_from_dict(state_get(_REQUIREMENTS_STATE_KEY))
        if callable(state_get)
        else None
    )
    candidates: list[dict[str, Any]] = []
    if callable(state_get):
        stored = state_get(_CANDIDATES_STATE_KEY, [])
        if isinstance(stored, list):
            candidates = [item for item in stored if isinstance(item, dict)]

    selected: Listing | None = None
    for candidate in candidates:
        listing_payload = candidate.get("listing")
        if isinstance(listing_payload, dict) and str(listing_payload.get("id")) == listing_id:
            selected = _listing_from_dict(listing_payload)
            break

    effective_destination = destination.strip() or (req.commute_destination if req else None)
    effective_mode = (
        normalize_travel_mode(travel_mode)
        if travel_mode.strip()
        else (req.commute_travel_mode if req else None)
    )
    if selected is None or not effective_destination or effective_mode is None:
        return RouteDetail(
            listing_id=listing_id,
            destination=effective_destination or destination.strip(),
            mode=effective_mode,
            status="unknown",
        ).to_dict()
    if selected.latitude is None or selected.longitude is None:
        return RouteDetail(
            listing_id=listing_id,
            destination=effective_destination,
            mode=effective_mode,
            status="unknown",
        ).to_dict()
    return get_commute_service().compute_route(
        CommuteOrigin(
            listing_id=selected.id,
            latitude=selected.latitude,
            longitude=selected.longitude,
        ),
        destination=effective_destination,
        mode=effective_mode,
    ).to_dict()


def get_route_details(
    listing_id: str,
    destination: str = "",
    travel_mode: str = "",
    tool_context: Optional[ToolContext] = None,
) -> dict[str, object]:
    """Compute on-demand route geometry for one already-selected search candidate."""
    state = tool_context.state if tool_context is not None else {}
    result = _route_details_from_state(listing_id, destination, travel_mode, state)
    route_outcome = "completed" if result.get("status") == "available" else "partial"
    result["activity"] = _agent_activity(
        operation="get_route_details",
        stage="commute_check",
        status=route_outcome,
        stage_outcomes=[("commute_check", route_outcome)],
        facts={
            "listing_id": listing_id,
            "route_status": result.get("status"),
        },
    )
    return result


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
    prior_commute = None
    current_rank = None
    for index, candidate in enumerate(candidates):
        listing_payload = candidate.get("listing")
        if not isinstance(listing_payload, dict):
            continue
        if str(listing_payload.get("id")) == listing_id:
            prior_listing = _try_listing_from_dict(listing_payload)
            prior_commute = _commute_from_dict(candidate.get("commute"))
            rank_value = candidate.get("current_search_rank")
            current_rank = int(rank_value) if isinstance(rank_value, (int, float)) else index + 1
            break

    merged = _merge_listing_detail(prior_listing, detail)
    passes = passes_hard_filters(merged, req, prior_commute) if req is not None else None

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
        "activity": _agent_activity(
            operation="get_listing_details",
            stage="detail_verification",
            status="completed" if detail.detail_verified else "partial",
            stage_outcomes=(
                [
                    (
                        "detail_verification",
                        "completed" if detail.detail_verified else "partial",
                    ),
                    ("hard_filter", "completed"),
                ]
                if req is not None
                else [
                    (
                        "detail_verification",
                        "completed" if detail.detail_verified else "partial",
                    )
                ]
            ),
            facts={
                "listing_id": listing_id,
                "detail_verified": detail.detail_verified,
                "passes_current_hard_filters": passes,
                "remaining_unknown_count": len(unknowns),
            },
        ),
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


def _candidate_references(value: str) -> list[str]:
    normalized = re.sub(r"\s+and\s+", ",", value.strip(), flags=re.IGNORECASE)
    raw = [item.strip() for item in re.split(r"[,\s]+", normalized) if item.strip()]
    return list(dict.fromkeys(raw))


def _soft_preference_text_fields(listing: Listing) -> list[tuple[str, str]]:
    values: list[tuple[str, str]] = []
    if listing.description:
        values.append(("description", listing.description))
    for amenity in listing.amenities:
        if amenity:
            values.append(("amenities", amenity))
    return values


def _matched_text_evidence(
    listing: Listing,
    phrases: tuple[str, ...],
) -> list[dict[str, object]]:
    evidence: list[dict[str, object]] = []
    for field_name, value in _soft_preference_text_fields(listing):
        folded = value.casefold()
        for phrase in phrases:
            pattern = re.compile(rf"(?<!\w){re.escape(phrase)}(?!\w)")
            match = pattern.search(folded)
            if match is not None:
                prefix = folded[max(0, match.start() - 8) : match.start()]
                if not phrase.startswith(("not ", "no ")) and re.search(
                    r"\b(?:not|no)\s+$", prefix
                ):
                    continue
                evidence.append({"field": field_name, "match": phrase})
    return evidence


def _soft_preference_evidence(
    listing: Listing,
    preferences: tuple[str, ...],
) -> list[dict[str, object]]:
    supported_phrases = {
        "modern": (
            "modern",
            "contemporary",
            "renovated",
            "remodeled",
            "updated interior",
            "updated kitchen",
            "updated bathroom",
        ),
        "quiet": ("quiet", "peaceful", "serene", "soundproof"),
        "near transit": (
            "near transit",
            "public transit",
            "caltrain",
            "bart",
            "light rail",
            "vta",
        ),
        "newer": ("new construction", "newly built", "newer construction"),
    }
    contradicted_phrases = {
        "modern": (
            "not modern",
            "dated interior",
            "needs renovation",
            "original kitchen",
            "original bathroom",
        ),
        "quiet": ("not quiet", "noisy", "noise-prone"),
        "near transit": (
            "no public transit",
            "not near transit",
            "no caltrain",
            "not near caltrain",
            "no bart",
            "not near bart",
            "no light rail",
            "no vta",
        ),
        "newer": ("not new construction", "not newly built"),
    }
    result: list[dict[str, object]] = []
    for preference in preferences:
        normalized = preference.strip().casefold()
        if normalized in {"in-unit laundry", "in unit laundry"}:
            amenities = {
                amenity.strip().casefold(): amenity
                for amenity in listing.amenities
                if amenity.strip()
            }
            installed_laundry_names = {
                "in-unit washer/dryer",
                "in unit washer/dryer",
                "in-unit laundry",
                "in unit laundry",
                "in-apartment laundry",
                "in apartment laundry",
            }
            installed_laundry = next(
                (
                    original
                    for folded, original in amenities.items()
                    if folded in installed_laundry_names
                ),
                None,
            )
            if installed_laundry is not None:
                result.append(
                    {
                        "preference": preference,
                        "status": "supported",
                        "evidence": [
                            {"field": "amenities", "match": installed_laundry}
                        ],
                    }
                )
                continue

            ambiguous_laundry_names = {
                "washer/dryer",
                "washer and dryer",
            }
            ambiguous_laundry = next(
                (
                    original
                    for folded, original in amenities.items()
                    if folded in ambiguous_laundry_names
                ),
                None,
            )
            if ambiguous_laundry is not None:
                result.append(
                    {
                        "preference": preference,
                        "status": "evidence_only",
                        "evidence": [
                            {"field": "amenities", "match": ambiguous_laundry}
                        ],
                    }
                )
                continue

            laundry_hookup = next(
                (
                    original
                    for folded, original in amenities.items()
                    if "hookup" in folded
                    and ("washer" in folded or "laundry" in folded)
                ),
                None,
            )
            if laundry_hookup is not None:
                result.append(
                    {
                        "preference": preference,
                        "status": "evidence_only",
                        "evidence": [
                            {"field": "amenities", "match": laundry_hookup}
                        ],
                    }
                )
                continue

            description_evidence = _matched_text_evidence(
                listing,
                (
                    "in-unit laundry",
                    "in unit laundry",
                    "in-apartment laundry",
                    "in apartment laundry",
                    "in-unit washer/dryer",
                ),
            )
            if description_evidence:
                result.append(
                    {
                        "preference": preference,
                        "status": "evidence_only",
                        "evidence": description_evidence,
                    }
                )
                continue

            result.append(
                {"preference": preference, "status": "unknown", "evidence": []}
            )
            continue

        if normalized not in supported_phrases:
            result.append({"preference": preference, "status": "unknown", "evidence": []})
            continue
        negative = _matched_text_evidence(listing, contradicted_phrases[normalized])
        if negative:
            result.append(
                {"preference": preference, "status": "contradicted", "evidence": negative}
            )
            continue
        positive = _matched_text_evidence(listing, supported_phrases[normalized])
        if positive:
            result.append(
                {"preference": preference, "status": "supported", "evidence": positive}
            )
            continue
        if normalized == "newer" and listing.year_built is not None:
            result.append(
                {
                    "preference": preference,
                    "status": "evidence_only",
                    "evidence": [{"field": "year_built", "value": listing.year_built}],
                }
            )
            continue
        result.append({"preference": preference, "status": "unknown", "evidence": []})
    return result


def _canonical_hard_constraint_result(
    canonical: dict[str, Any],
    req: SearchRequirements | None,
    commute: CommuteResult | None,
) -> tuple[str, bool | None]:
    """Evaluate hard constraints as pass/fail/evidence_only/unknown."""
    if req is None:
        return "unknown", None

    def section(name: str) -> dict[str, Any]:
        current = canonical.get(name)
        return current if isinstance(current, dict) else {}

    def number(value: object) -> float | None:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return None
        return float(value)

    outcomes: list[str] = []
    location = section("location")
    pricing = section("pricing")
    property_data = section("property")
    availability = section("availability")
    policies = section("policies")
    evidence = section("evidence")
    query_backed_value = evidence.get("queryBackedFields")
    query_backed = {
        str(item) for item in query_backed_value
    } if isinstance(query_backed_value, list) else set()

    city = location.get("city")
    if not isinstance(city, str) or not city.strip():
        outcomes.append("unknown")
    elif city.casefold() != req.city.casefold():
        outcomes.append("fail")

    state = location.get("state")
    if not isinstance(state, str) or not state.strip():
        outcomes.append("unknown")
    elif state.upper() != req.state.upper():
        outcomes.append("fail")

    listing_status = availability.get("status")
    if isinstance(listing_status, str) and listing_status.strip():
        if listing_status.casefold() != "active":
            outcomes.append("fail")

    if req.max_rent is not None:
        exact = number(pricing.get("rent"))
        minimum = number(pricing.get("rentMin"))
        maximum = number(pricing.get("rentMax"))
        if exact is not None:
            outcomes.append("fail" if exact > req.max_rent else "pass")
        elif minimum is not None and minimum > req.max_rent:
            outcomes.append("fail")
        elif maximum is not None and maximum <= req.max_rent:
            outcomes.append("pass")
        else:
            outcomes.append("unknown")

    if req.min_bedrooms is not None:
        exact = number(property_data.get("bedrooms"))
        minimum = number(property_data.get("bedroomsMin"))
        maximum = number(property_data.get("bedroomsMax"))
        if exact is not None:
            outcomes.append("fail" if exact < req.min_bedrooms else "pass")
        elif maximum is not None and maximum < req.min_bedrooms:
            outcomes.append("fail")
        elif minimum is not None and minimum >= req.min_bedrooms:
            outcomes.append("pass")
        else:
            outcomes.append("unknown")

    if req.max_bedrooms is not None:
        exact = number(property_data.get("bedrooms"))
        minimum = number(property_data.get("bedroomsMin"))
        maximum = number(property_data.get("bedroomsMax"))
        if exact is not None:
            outcomes.append("fail" if exact > req.max_bedrooms else "pass")
        elif minimum is not None and minimum > req.max_bedrooms:
            outcomes.append("fail")
        elif maximum is not None and maximum <= req.max_bedrooms:
            outcomes.append("pass")
        else:
            outcomes.append("unknown")

    if req.min_bathrooms is not None:
        exact = number(property_data.get("bathrooms"))
        minimum_evidence = number(property_data.get("bathroomsMinEvidence"))
        if exact is not None:
            if "property.bathrooms" in query_backed:
                outcomes.append("evidence_only")
            else:
                outcomes.append("fail" if exact < req.min_bathrooms else "pass")
        elif minimum_evidence is not None:
            if minimum_evidence < req.min_bathrooms:
                outcomes.append("unknown")
            elif "property.bathroomsMinEvidence" in query_backed:
                outcomes.append("evidence_only")
            else:
                outcomes.append("pass")
        else:
            outcomes.append("unknown")

    if req.max_bathrooms is not None:
        exact = number(property_data.get("bathrooms"))
        minimum_evidence = number(property_data.get("bathroomsMinEvidence"))
        if exact is not None and "property.bathrooms" in query_backed:
            outcomes.append("evidence_only")
        elif exact is not None:
            outcomes.append("fail" if exact > req.max_bathrooms else "pass")
        elif minimum_evidence is not None and minimum_evidence > req.max_bathrooms:
            if "property.bathroomsMinEvidence" in query_backed:
                outcomes.append("evidence_only")
            else:
                outcomes.append("fail")
        else:
            outcomes.append("unknown")

    if req.pets_required:
        pets = policies.get("petsAllowed")
        if pets is None:
            outcomes.append("unknown")
        elif "policies.petsAllowed" in query_backed:
            outcomes.append("evidence_only")
        else:
            outcomes.append("pass" if pets is True else "fail")

    if req.parking_required:
        parking = policies.get("parkingAvailable")
        if parking is None:
            outcomes.append("unknown")
        elif "policies.parkingAvailable" in query_backed:
            outcomes.append("evidence_only")
        else:
            outcomes.append("pass" if parking is True else "fail")

    if req.max_commute_minutes is not None:
        expected_destination = (
            req.commute_destination.strip().casefold()
            if req.commute_destination and req.commute_destination.strip()
            else None
        )
        expected_mode = normalize_travel_mode(req.commute_travel_mode)
        commute_destination = (
            commute.destination.strip().casefold()
            if commute is not None and commute.destination.strip()
            else None
        )
        commute_mode = (
            normalize_travel_mode(commute.mode) if commute is not None else None
        )
        if (
            commute is None
            or commute.status != "available"
            or commute.duration_minutes is None
            or expected_destination is None
            or expected_mode is None
            or commute_destination != expected_destination
            or commute_mode != expected_mode
        ):
            outcomes.append("unknown")
        else:
            outcomes.append(
                "fail"
                if commute.duration_minutes > req.max_commute_minutes
                else "pass"
            )

    if "fail" in outcomes:
        return "fail", False
    if "unknown" in outcomes:
        return "unknown", None
    if "evidence_only" in outcomes:
        return "evidence_only", None
    return "pass", True


def _canonical_comparison_result(
    canonical: dict[str, Any],
    req: SearchRequirements | None,
    commute: CommuteResult | None,
) -> dict[str, object]:
    listing = _listing_from_canonical_v1(canonical)
    completeness_value = canonical.get("completeness")
    completeness = completeness_value if isinstance(completeness_value, dict) else {}
    evidence_value = canonical.get("evidence")
    evidence = evidence_value if isinstance(evidence_value, dict) else {}

    critical_unknown_value = completeness.get("criticalUnknownFields")
    critical_unknown = (
        [str(item) for item in critical_unknown_value]
        if isinstance(critical_unknown_value, list)
        else []
    )
    critical_query_value = evidence.get("criticalQueryBackedFields")
    critical_query_backed = (
        [str(item) for item in critical_query_value]
        if isinstance(critical_query_value, list)
        else []
    )
    comparison_unknowns = list(
        dict.fromkeys([*critical_unknown, *critical_query_backed])
    )
    hard_status, satisfies = _canonical_hard_constraint_result(canonical, req, commute)

    policies_value = canonical.get("policies")
    policies = policies_value if isinstance(policies_value, dict) else {}
    tradeoffs: list[str] = []
    if req is not None and not req.pets_required and policies.get("petsAllowed") is None:
        tradeoffs.append("pet policy not provided by source")
    if req is not None and not req.parking_required and policies.get("parkingAvailable") is None:
        tradeoffs.append("parking not provided by source")

    return {
        "listingId": listing.id,
        "hardConstraintStatus": hard_status,
        "satisfiesCurrentRequirements": satisfies,
        "softPreferenceEvidence": _soft_preference_evidence(
            listing, req.soft_preferences if req is not None else ()
        ),
        "tradeoffs": tradeoffs,
        "comparisonUnknowns": comparison_unknowns,
        "decisionUnknowns": list(comparison_unknowns),
        "decisionReady": bool(completeness.get("decisionReady")) and hard_status == "pass",
        "score": None,
        "rank": None,
    }


def compare_canonical_listings(
    canonical_listings: list[dict[str, Any]],
    requirements: SearchRequirements | dict[str, Any] | None = None,
    *,
    commutes: dict[str, CommuteResult | dict[str, Any]] | None = None,
) -> dict[str, object]:
    """Compare restored canonical listings without ADK, backend, or provider coupling."""
    if isinstance(requirements, SearchRequirements):
        req = requirements
    elif requirements is None:
        req = None
    else:
        req = _requirements_from_dict(requirements)

    commute_values = commutes or {}
    listing_ids: list[str] = []
    results: list[dict[str, object]] = []
    seen: set[str] = set()
    for canonical in canonical_listings:
        listing = _listing_from_canonical_v1(canonical)
        if listing.id in seen:
            continue
        seen.add(listing.id)
        commute_value = commute_values.get(listing.id)
        commute = (
            commute_value
            if isinstance(commute_value, CommuteResult)
            else _commute_from_dict(commute_value)
        )
        listing_ids.append(listing.id)
        results.append(_canonical_comparison_result(canonical, req, commute))

    return {
        "schemaVersion": _CANONICAL_COMPARISON_SCHEMA,
        "listingIds": listing_ids,
        "results": results,
    }


def _comparison_candidate(
    *,
    candidate: dict[str, Any],
    listing: Listing,
    req: SearchRequirements | None,
    commute: CommuteResult | None,
    verification_attempted: bool,
    verification_error: str | None = None,
) -> dict[str, object]:
    canonical = listing.to_backend_dict()
    completeness = canonical["completeness"]
    evidence = canonical["evidence"]
    critical_unknown = list(completeness["criticalUnknownFields"])
    critical_query_backed = list(evidence["criticalQueryBackedFields"])
    comparison_unknowns = list(
        dict.fromkeys([*critical_unknown, *critical_query_backed])
    )
    decision_unknowns = list(comparison_unknowns)
    rank_value = candidate.get("current_search_rank")
    current_rank = int(rank_value) if isinstance(rank_value, (int, float)) else None
    score_value = candidate.get("score")
    current_score = float(score_value) if isinstance(score_value, (int, float)) else None
    pricing = canonical["pricing"]
    property_data = canonical["property"]
    policies = canonical["policies"]
    query_backed = set(evidence["queryBackedFields"])
    pets_query_backed = "policies.petsAllowed" in query_backed
    parking_query_backed = "policies.parkingAvailable" in query_backed
    required_query_backed: list[str] = []
    if req is not None:
        if req.pets_required and pets_query_backed:
            required_query_backed.append("policies.petsAllowed")
        if req.parking_required and parking_query_backed:
            required_query_backed.append("policies.parkingAvailable")
        if req.min_bathrooms is not None:
            if listing.bathrooms is not None:
                if "property.bathrooms" in query_backed:
                    required_query_backed.append("property.bathrooms")
            elif "property.bathroomsMinEvidence" in query_backed:
                required_query_backed.append("property.bathroomsMinEvidence")
        if req.max_bathrooms is not None and "property.bathrooms" in query_backed:
            required_query_backed.append("property.bathrooms")
    required_query_backed = list(dict.fromkeys(required_query_backed))
    hard_constraint_status, satisfies_current_requirements = (
        _canonical_hard_constraint_result(canonical, req, commute)
    )
    comparison_ready = bool(completeness["comparisonReady"])
    decision_ready = (
        bool(completeness["decisionReady"]) and hard_constraint_status == "pass"
    )

    return {
        "listing_id": listing.id,
        "current_search_rank": current_rank,
        "score": current_score,
        "address": listing.address,
        "source": listing.source,
        "price": pricing["rent"],
        "price_range": {"min": pricing["rentMin"], "max": pricing["rentMax"]},
        "beds": property_data["bedrooms"],
        "bedroom_bounds": {
            "min": property_data["bedroomsMin"],
            "max": property_data["bedroomsMax"],
        },
        "bathrooms": {
            "exact": property_data["bathrooms"],
            "minimum_evidence": property_data["bathroomsMinEvidence"],
        },
        "square_footage": property_data["squareFootage"],
        "year_built": property_data["yearBuilt"],
        "pet_policy": {
            "allowed": None if pets_query_backed else policies["petsAllowed"],
            "query_backed_evidence": policies["petsAllowed"] if pets_query_backed else None,
            "policy": policies["petPolicy"],
            "confirmed": (
                policies["petsAllowed"] is not None
                and not pets_query_backed
            ),
        },
        "parking_policy": {
            "available": None if parking_query_backed else policies["parkingAvailable"],
            "query_backed_evidence": (
                policies["parkingAvailable"] if parking_query_backed else None
            ),
            "policy": policies["parkingPolicy"],
            "confirmed": (
                policies["parkingAvailable"] is not None
                and not parking_query_backed
            ),
        },
        "commute": commute.to_dict() if commute is not None else None,
        "hard_constraint_status": hard_constraint_status,
        "satisfies_current_requirements": satisfies_current_requirements,
        "hard_constraint_evidence_only": required_query_backed,
        "detail_verified": listing.detail_verified,
        "comparison_unknowns": comparison_unknowns,
        "decision_unknowns": decision_unknowns,
        "soft_preference_evidence": _soft_preference_evidence(
            listing, req.soft_preferences if req is not None else ()
        ),
        "comparison_ready": comparison_ready,
        "decision_ready": decision_ready,
        "verification_attempted": verification_attempted,
        "verification_error": verification_error,
        "canonical_listing": canonical,
    }


def compare_candidates(
    listing_ids: str,
    verify_missing: bool = True,
    tool_context: Optional[ToolContext] = None,
) -> dict[str, object]:
    """Compare up to four candidates already present in the current ADK session.

    `listing_ids` accepts comma/space-separated listing IDs and visible rank references
    such as `#1,#3`. This tool never performs a broad provider search. Existing verified
    detail state is reused; with `verify_missing=True`, only selected unverified listings
    may call the provider detail path.
    """
    state = tool_context.state if tool_context is not None else {}
    state_get = getattr(state, "get", None)
    req = (
        _requirements_from_dict(state_get(_REQUIREMENTS_STATE_KEY))
        if callable(state_get)
        else None
    )
    stored = state_get(_CANDIDATES_STATE_KEY, []) if callable(state_get) else []
    candidates = [item for item in stored if isinstance(item, dict)] if isinstance(stored, list) else []
    verified_value = state_get(_VERIFIED_STATE_KEY, {}) if callable(state_get) else {}
    verified = dict(verified_value) if isinstance(verified_value, dict) else {}

    requested_all = _candidate_references(listing_ids)
    too_many = len(requested_all) > _COMPARISON_LIMIT
    requested_refs = requested_all[:_COMPARISON_LIMIT]

    by_id: dict[str, dict[str, Any]] = {}
    by_rank: dict[int, dict[str, Any]] = {}
    for candidate in candidates:
        listing_payload = candidate.get("listing")
        if not isinstance(listing_payload, dict) or not listing_payload.get("id"):
            continue
        identifier = str(listing_payload["id"])
        by_id.setdefault(identifier, candidate)
        rank_value = candidate.get("current_search_rank")
        if isinstance(rank_value, (int, float)):
            by_rank.setdefault(int(rank_value), candidate)

    selected: list[tuple[str, dict[str, Any]]] = []
    missing: list[str] = []
    seen_ids: set[str] = set()
    for reference in requested_refs:
        candidate = None
        if reference.startswith("#") and reference[1:].isdigit():
            candidate = by_rank.get(int(reference[1:]))
        else:
            candidate = by_id.get(reference)
        if candidate is None:
            missing.append(reference)
            continue
        listing_payload = candidate.get("listing")
        identifier = str(listing_payload["id"])
        if identifier in seen_ids:
            continue
        seen_ids.add(identifier)
        selected.append((identifier, candidate))

    comparisons: list[dict[str, object]] = []
    canonical_inputs: list[dict[str, Any]] = []
    canonical_commutes: dict[str, CommuteResult] = {}
    resolved_requested: list[str] = []
    invalid: list[str] = []
    verification_attempted_count = 0
    verification_error_count = 0
    for identifier, candidate in selected:
        resolved_requested.append(identifier)
        verification_attempted = False
        verification_error = None
        cached = verified.get(identifier)
        listing_payload: object = None
        if isinstance(cached, dict):
            listing_payload = cached.get("listing")
        listing = _try_listing_from_dict(listing_payload)
        if listing_payload is not None and listing is None:
            verification_error = "invalid_cached_detail"
        if listing is None:
            candidate_payload = candidate.get("listing")
            listing = _try_listing_from_dict(candidate_payload)
            if verify_missing and tool_context is not None:
                verification_attempted = True
                verification_attempted_count += 1
                try:
                    cached = get_listing_details(identifier, tool_context=tool_context)
                except Exception:
                    verification_error = "detail_lookup_failed"
                else:
                    verified_listing = _try_listing_from_dict(cached.get("listing"))
                    if verified_listing is None:
                        verification_error = "invalid_detail_payload"
                    else:
                        listing = verified_listing
                        verification_error = None

        if verification_error is not None:
            verification_error_count += 1
        if listing is None:
            invalid.append(identifier)
            continue
        commute = _commute_from_dict(candidate.get("commute"))
        canonical_inputs.append(listing.to_backend_dict())
        if commute is not None:
            canonical_commutes[listing.id] = commute
        comparisons.append(
            _comparison_candidate(
                candidate=candidate,
                listing=listing,
                req=req,
                commute=commute,
                verification_attempted=verification_attempted,
                verification_error=verification_error,
            )
        )

    requested_output = []
    for reference in requested_refs:
        if reference in missing:
            requested_output.append(reference)
            continue
        if reference.startswith("#") and reference[1:].isdigit():
            candidate = by_rank.get(int(reference[1:]))
            listing_payload = candidate.get("listing") if candidate else None
            if isinstance(listing_payload, dict) and listing_payload.get("id"):
                identifier = str(listing_payload["id"])
                if identifier not in requested_output:
                    requested_output.append(identifier)
            continue
        if reference not in requested_output:
            requested_output.append(reference)

    stage_outcomes: list[tuple[str, str]] = []
    if verification_attempted_count:
        stage_outcomes.append(
            (
                "detail_verification",
                "partial" if verification_error_count else "completed",
            )
        )
    if comparisons and req is not None and req.soft_preferences:
        stage_outcomes.append(("soft_preference_evidence", "completed"))
    comparison_outcome = (
        "requires_input"
        if not requested_refs
        else ("partial" if too_many or missing or invalid else "completed")
    )
    stage_outcomes.append(("candidate_comparison", comparison_outcome))
    activity_status = (
        "requires_input"
        if comparison_outcome == "requires_input"
        else (
            "partial"
            if comparison_outcome == "partial" or verification_error_count
            else "completed"
        )
    )
    canonical_comparison = compare_canonical_listings(
        canonical_inputs,
        req,
        commutes=canonical_commutes,
    )
    comparison_by_id = {
        str(item["listing_id"]): item
        for item in comparisons
        if item.get("listing_id") is not None
    }
    canonical_results = canonical_comparison.get("results")
    if isinstance(canonical_results, list):
        for result in canonical_results:
            if not isinstance(result, dict):
                continue
            comparison = comparison_by_id.get(str(result.get("listingId")))
            if comparison is None:
                continue
            result["rank"] = comparison.get("current_search_rank")
            result["score"] = comparison.get("score")

    return {
        **canonical_comparison,
        "activity": _agent_activity(
            operation="compare_candidates",
            stage="candidate_comparison",
            status=activity_status,
            stage_outcomes=stage_outcomes,
            facts={
                "requested_count": len(requested_all),
                "bounded_requested_count": len(requested_refs),
                "compared_count": len(comparisons),
                "missing_count": len(set(missing)),
                "invalid_count": len(set(invalid)),
                "verification_attempted_count": verification_attempted_count,
                "verification_error_count": verification_error_count,
                "decision_ready_count": sum(
                    item.get("decision_ready") is True for item in comparisons
                ),
                "hard_fail_count": sum(
                    item.get("hard_constraint_status") == "fail" for item in comparisons
                ),
            },
        ),
        "requested": requested_output,
        "selection_limit": _COMPARISON_LIMIT,
        "too_many_requested": too_many,
        "missing_listing_ids": list(dict.fromkeys(missing)),
        "invalid_listing_ids": list(dict.fromkeys(invalid)),
        "candidate_count": len(comparisons),
        "candidates": comparisons,
        "comparison_policy": {
            "provider_search_performed": False,
            "selected_only_verification": True,
            "unknown_is_not_pass": True,
        },
    }


root_agent = Agent(
    name="single_rental_agent",
    model=build_ordered_gemini(),
    description="Finds, verifies, compares, and explains rentals across the United States.",
    instruction="""
You are Keys by Friday's single rental search agent. There are no sub-agents.

Memory and search behavior:
1. Extract explicit hard constraints: city, state, budget, bedroom/bathroom
   bounds, required pets, and required parking. Search coverage is nationwide across
   the United States; do not reject a city because it is outside California. Pass the
   state whenever it is known; full state names and postal abbreviations are accepted.
2. Treat a plain numeric room count such as "2 bedroom", "2-bedroom", "2 bed",
   or "2 bathroom" as an exact count: pass the same value as both the minimum and
   maximum bound. Use a one-sided bound only when the user says "at least", "2+",
   "minimum", "up to", "at most", or similar bound language. Preserve the existing
   shorthand convention: "2B2B" means minimum 2 bedrooms and minimum 2 bathrooms
   unless the user explicitly says "exactly".
3. The search_listings tool keeps the previous search requirements in ADK session
   state. For follow-up refinements, pass only values the user changed; omitted
   values are inherited. Use reset_search=True only when the user explicitly asks
   to start over or replace the whole search.
4. If the user says "cheaper" without a new number, do not invent a new hard
   budget. Keep the current budget and add "prefer cheaper" as a soft preference.
   Treat quiet, newer, modern, near transit, or similar language as soft preferences.
5. A hard commute request must include a destination, maximum minutes, and an explicit
   travel mode. If search_listings returns status=requires_input, ask only for the
   listed missing_requirements; the rental provider was not called. Pass complete
   commute constraints to search_listings so route-matrix enrichment happens before
   deterministic filtering/ranking. If the user removes commute as a requirement,
   pass clear_commute=True instead of resetting unrelated rental requirements.
5a. Tool responses may include an `activity` object. It is machine-readable execution
    metadata for integration observability, not user-facing copy or hidden reasoning.
    Do not quote its schema, invent activity states, percentages, or narrate steps that
    did not actually occur.

Candidate-first behavior:
5. For every initial or refined search, call search_listings exactly once. The tool is
   cache-first: narrower/equal refinements reuse session data and do not call RealtyAPI
   when cached candidates can satisfy the new hard constraints.
5b. Search results are intentionally bounded to at most 20 source postings per search
    workflow to control provider/model context cost. Do not bypass this bound with repeated
    searches. Ask the user to refine requirements instead when they need a narrower set.
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
11a. For a normal detail question, call get_listing_details at most once in that user
     request. For multi-property comparison, use compare_candidates, which enforces its
     own bounded selected-only verification instead of issuing repeated detail calls.
12. A verified candidate with passes_current_hard_filters=false must not be presented
    as satisfying the current hard constraints.
12a. Use get_route_details only for a selected/specific listing when route geometry or
     route detail is requested. Never calculate full route polylines for broad results.
     Commute status unknown/unavailable is not evidence that a hard commute limit passed.
12b. When the user asks to compare selected results (for example "compare #1 and #3",
     "compare these two", or "which of these is better"), use compare_candidates.
     Do not call search_listings again unless the user actually changed search requirements.
     compare_candidates may verify only the selected candidates, reuses prior verified
     details, and deterministically re-checks the current hard constraints.
12c. In comparison answers, use only structured facts and soft_preference_evidence from
     compare_candidates. `supported` requires explicit provider text, `evidence_only`
     is evidence without a deterministic conclusion, and `unknown` is not a pass.
     Never fabricate a soft-preference score or infer quiet/safety/transit from location.

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
21. The broad-search formatting rules above apply only to search/refinement answers.
    Comparison answers should focus only on the selected candidates: verified facts,
    hard-constraint failures, trade-offs, explicit unknowns, and soft-preference evidence.
    A candidate with hard_constraint_status=fail must not be recommended as satisfying
    the current requirements. Conditional recommendations are allowed when uncertainty
    is stated explicitly.
22. End every comparison answer with a `## Decision` section. Do not omit the decision
    merely because a required fact is unknown. If any otherwise viable candidate has
    decision_ready=false, state that the decision is pending or conditional and name its
    decision_unknowns (for example an unverified bathroom count). Treat unknown and
    evidence_only as unresolved, never as pass. Only make a final recommendation when the
    structured comparison evidence supports it.

""".strip(),
    tools=[search_listings, get_listing_details, get_route_details, compare_candidates],
)
