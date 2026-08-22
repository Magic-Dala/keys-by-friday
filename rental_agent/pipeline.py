from __future__ import annotations

from dataclasses import replace

from rental_agent.commute import CommuteResult
from rental_agent.models import Listing, RankedListing, SearchRequirements


def passes_hard_filters(
    listing: Listing,
    req: SearchRequirements,
    commute: CommuteResult | None = None,
) -> bool:
    if listing.city.casefold() != req.city.casefold() or listing.state.upper() != req.state.upper():
        return False
    if listing.status and listing.status.casefold() != "active":
        return False
    if req.max_rent is not None and (listing.rent is None or listing.rent > req.max_rent):
        return False
    if req.min_bedrooms is not None and (listing.bedrooms is None or listing.bedrooms < req.min_bedrooms):
        return False
    if req.max_bedrooms is not None and (listing.bedrooms is None or listing.bedrooms > req.max_bedrooms):
        return False
    bathroom_floor = (
        listing.bathrooms
        if listing.bathrooms is not None
        else listing.bathrooms_min_evidence
    )
    if req.min_bathrooms is not None and (
        bathroom_floor is None or bathroom_floor < req.min_bathrooms
    ):
        return False
    if req.max_bathrooms is not None and (
        listing.bathrooms is None or listing.bathrooms > req.max_bathrooms
    ):
        return False
    if req.pets_required and listing.pets_allowed is not True:
        return False
    if req.parking_required and listing.parking_available is not True:
        return False
    if req.max_commute_minutes is not None:
        if commute is None or commute.status != "available":
            return False
        if commute.duration_minutes is None or commute.duration_minutes > req.max_commute_minutes:
            return False
    return True


def _search_admission_listing(
    listing: Listing,
    req: SearchRequirements,
) -> Listing | None:
    """Return a conservative representative only when an explicit range can satisfy the query.

    `passes_hard_filters()` remains the strict verification predicate used elsewhere.
    Search admission is slightly different: a provider-reported range should not be
    rejected just because its legacy ranking representative falls outside the query
    when some value in the explicit range can still satisfy it.
    """
    canonical = listing.to_backend_dict()
    pricing = canonical["pricing"]
    property_data = canonical["property"]
    replacements: dict[str, float] = {}

    if req.max_rent is not None and pricing["rent"] is None:
        rent_min = pricing["rentMin"]
        rent_max = pricing["rentMax"]
        if rent_min is None and rent_max is None:
            return None
        if rent_min is not None and rent_min > req.max_rent:
            return None
        if rent_min is not None:
            replacements["rent"] = float(rent_min)
        elif rent_max is not None:
            replacements["rent"] = float(min(rent_max, req.max_rent))

    if (
        (req.min_bedrooms is not None or req.max_bedrooms is not None)
        and property_data["bedrooms"] is None
    ):
        bedrooms_min = property_data["bedroomsMin"]
        bedrooms_max = property_data["bedroomsMax"]
        if bedrooms_min is None and bedrooms_max is None:
            return None

        lower = float(bedrooms_min) if bedrooms_min is not None else float("-inf")
        upper = float(bedrooms_max) if bedrooms_max is not None else float("inf")
        if req.min_bedrooms is not None:
            lower = max(lower, float(req.min_bedrooms))
        if req.max_bedrooms is not None:
            upper = min(upper, float(req.max_bedrooms))
        if lower > upper:
            return None

        if lower != float("-inf"):
            replacements["bedrooms"] = lower
        elif upper != float("inf"):
            replacements["bedrooms"] = upper

    return replace(listing, **replacements) if replacements else listing


def _admit_search_candidate(
    listing: Listing,
    req: SearchRequirements,
    commute: CommuteResult | None = None,
) -> bool:
    admission_listing = _search_admission_listing(listing, req)
    if admission_listing is None:
        return False
    return passes_hard_filters(admission_listing, req, commute)


def _score(listing: Listing, req: SearchRequirements) -> float:
    """Pure score: same listing + requirements always yields the same result."""
    score = 50.0
    canonical = listing.to_backend_dict()
    exact_rent = canonical["pricing"]["rent"]
    exact_bedrooms = canonical["property"]["bedrooms"]
    if req.max_rent and exact_rent is not None:
        headroom = max(0.0, req.max_rent - exact_rent)
        score += min(25.0, 25.0 * headroom / req.max_rent)
    if req.min_bedrooms is not None and exact_bedrooms is not None:
        score += min(8.0, max(0.0, exact_bedrooms - req.min_bedrooms) * 4.0)
    if req.min_bathrooms is not None and listing.bathrooms is not None:
        score += min(8.0, max(0.0, listing.bathrooms - req.min_bathrooms) * 4.0)
    if listing.square_footage:
        score += min(6.0, listing.square_footage / 250.0)
    return score


def _explain(
    listing: Listing,
    req: SearchRequirements,
    commute: CommuteResult | None = None,
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    reasons: list[str] = []
    tradeoffs: list[str] = []
    canonical = listing.to_backend_dict()
    pricing = canonical["pricing"]
    property_data = canonical["property"]
    exact_rent = pricing["rent"]
    exact_bedrooms = property_data["bedrooms"]
    if req.max_rent is not None and exact_rent is not None:
        reasons.append(f"${req.max_rent - exact_rent:,.0f}/mo under budget")
    elif req.max_rent is not None:
        rent_min = pricing["rentMin"]
        rent_max = pricing["rentMax"]
        if rent_max is not None and rent_max <= req.max_rent:
            reasons.append(f"rent range up to ${rent_max:,.0f}/mo within budget")
        elif rent_min is not None or rent_max is not None:
            tradeoffs.append("rent range may include units above budget; verify unit rent")
    if exact_bedrooms is not None:
        if listing.bathrooms is not None:
            reasons.append(f"{exact_bedrooms:g} bed / {listing.bathrooms:g} bath")
        else:
            reasons.append(f"{exact_bedrooms:g} bed")
    elif req.min_bedrooms is not None or req.max_bedrooms is not None:
        bedrooms_min = property_data["bedroomsMin"]
        bedrooms_max = property_data["bedroomsMax"]
        if bedrooms_min is not None or bedrooms_max is not None:
            tradeoffs.append("bedroom range requires unit-level verification")
    query_backed = set(listing.query_backed_fields)
    if req.pets_required:
        if "pets_allowed" in query_backed:
            tradeoffs.append("pet allowance is search-filter evidence; verify policy")
        else:
            reasons.append("pets confirmed allowed")
    elif listing.pets_allowed is None:
        tradeoffs.append("pet policy not provided by source")
    if req.parking_required:
        if "parking_available" in query_backed:
            tradeoffs.append("parking is search-filter evidence; verify availability")
        else:
            reasons.append("parking confirmed available")
    elif listing.parking_available is None:
        tradeoffs.append("parking not provided by source")
    if req.max_commute_minutes is not None and commute is not None and commute.status == "available":
        reasons.append(f"{commute.duration_minutes} min commute")
    return tuple(reasons), tuple(tradeoffs)


def filter_and_rank(
    listings: list[Listing],
    req: SearchRequirements,
    top_n: int = 5,
    commutes: dict[str, CommuteResult] | None = None,
) -> list[RankedListing]:
    ranked = []
    for listing in listings:
        commute = commutes.get(listing.id) if commutes is not None else None
        if not _admit_search_candidate(listing, req, commute):
            continue
        reasons, tradeoffs = _explain(listing, req, commute)
        ranked.append(
            RankedListing(
                listing=listing,
                score=_score(listing, req),
                reasons=reasons,
                tradeoffs=tradeoffs,
                commute=commute,
            )
        )
    ranked.sort(
        key=lambda item: (
            -item.score,
            item.listing.rent if item.listing.rent is not None else float("inf"),
            item.listing.id,
        )
    )
    return ranked[:top_n]
