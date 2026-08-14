from __future__ import annotations

from rental_agent.models import Listing, RankedListing, SearchRequirements


def passes_hard_filters(listing: Listing, req: SearchRequirements) -> bool:
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
    if req.min_bathrooms is not None and (listing.bathrooms is None or listing.bathrooms < req.min_bathrooms):
        return False
    if req.max_bathrooms is not None and (listing.bathrooms is None or listing.bathrooms > req.max_bathrooms):
        return False
    if req.pets_required and listing.pets_allowed is not True:
        return False
    if req.parking_required and listing.parking_available is not True:
        return False
    return True


def _score(listing: Listing, req: SearchRequirements) -> float:
    """Pure score: same listing + requirements always yields the same result."""
    score = 50.0
    if req.max_rent and listing.rent is not None:
        headroom = max(0.0, req.max_rent - listing.rent)
        score += min(25.0, 25.0 * headroom / req.max_rent)
    if req.min_bedrooms is not None and listing.bedrooms is not None:
        score += min(8.0, max(0.0, listing.bedrooms - req.min_bedrooms) * 4.0)
    if req.min_bathrooms is not None and listing.bathrooms is not None:
        score += min(8.0, max(0.0, listing.bathrooms - req.min_bathrooms) * 4.0)
    if listing.square_footage:
        score += min(6.0, listing.square_footage / 250.0)
    return score


def _explain(listing: Listing, req: SearchRequirements) -> tuple[tuple[str, ...], tuple[str, ...]]:
    reasons: list[str] = []
    tradeoffs: list[str] = []
    if req.max_rent is not None and listing.rent is not None:
        reasons.append(f"${req.max_rent - listing.rent:,.0f}/mo under budget")
    if listing.bedrooms is not None and listing.bathrooms is not None:
        reasons.append(f"{listing.bedrooms:g} bed / {listing.bathrooms:g} bath")
    if req.pets_required:
        reasons.append("pets confirmed allowed")
    elif listing.pets_allowed is None:
        tradeoffs.append("pet policy not provided by source")
    if req.parking_required:
        reasons.append("parking confirmed available")
    elif listing.parking_available is None:
        tradeoffs.append("parking not provided by source")
    return tuple(reasons), tuple(tradeoffs)


def filter_and_rank(
    listings: list[Listing], req: SearchRequirements, top_n: int = 5
) -> list[RankedListing]:
    ranked = []
    for listing in listings:
        if not passes_hard_filters(listing, req):
            continue
        reasons, tradeoffs = _explain(listing, req)
        ranked.append(
            RankedListing(
                listing=listing,
                score=_score(listing, req),
                reasons=reasons,
                tradeoffs=tradeoffs,
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
