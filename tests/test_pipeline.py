from dataclasses import replace

from rental_agent.models import SearchRequirements
from rental_agent.pipeline import filter_and_rank
from rental_agent.providers.mock import MockListingProvider


def test_filters_budget_beds_baths_and_ranks_deterministically():
    req = SearchRequirements(
        city="Mountain View",
        max_rent=4000,
        min_bedrooms=2,
        min_bathrooms=2,
    )
    provider = MockListingProvider()
    listings = provider.search(req)

    first = filter_and_rank(listings, req)
    second = filter_and_rank(listings, req)

    assert first == second
    assert [item.listing.id for item in first] == ["mv-6", "mv-1", "mv-5", "mv-2"]
    assert all(item.listing.rent <= 4000 for item in first)
    assert all(item.listing.bedrooms >= 2 for item in first)
    assert all(item.listing.bathrooms >= 2 for item in first)


def test_required_pets_and_parking_reject_false_or_unknown():
    req = SearchRequirements(
        city="Mountain View",
        max_rent=4000,
        min_bedrooms=2,
        min_bathrooms=2,
        pets_required=True,
        parking_required=True,
    )
    ranked = filter_and_rank(MockListingProvider().search(req), req)

    assert [item.listing.id for item in ranked] == ["mv-6", "mv-1"]
    assert all(item.listing.pets_allowed is True for item in ranked)
    assert all(item.listing.parking_available is True for item in ranked)


def test_mock_provider_is_keyless_and_city_bounded():
    provider = MockListingProvider()
    req = SearchRequirements(city="Sunnyvale", max_rent=4000, min_bedrooms=2)

    results = provider.search(req)

    assert provider.health()["ok"] is True
    assert [listing.id for listing in results] == ["sv-1"]


def test_search_admits_ambiguous_rent_range_but_rejects_definitive_over_budget_range():
    req = SearchRequirements(city="Mountain View", max_rent=4000)
    base = MockListingProvider().search(SearchRequirements(city="Mountain View"))[0]
    ambiguous = replace(
        base,
        id="ambiguous",
        rent=4500,
        rent_is_exact=False,
        rent_min=3200,
        rent_max=4500,
    )
    over_budget = replace(
        base,
        id="over-budget",
        rent=4500,
        rent_is_exact=False,
        rent_min=4200,
        rent_max=4500,
    )

    ranked = filter_and_rank([ambiguous, over_budget], req, top_n=10)

    assert [item.listing.id for item in ranked] == ["ambiguous"]
    assert "rent range may include units above budget; verify unit rent" in ranked[0].tradeoffs
    assert not any("under budget" in reason for reason in ranked[0].reasons)


def test_search_admits_overlapping_bedroom_range_without_treating_representative_as_exact():
    req = SearchRequirements(city="Mountain View", min_bedrooms=2, max_bedrooms=2)
    base = MockListingProvider().search(SearchRequirements(city="Mountain View"))[0]
    overlapping = replace(
        base,
        id="overlap",
        bedrooms=3,
        bedrooms_is_exact=False,
        bedrooms_min=1,
        bedrooms_max=3,
    )
    incompatible = replace(
        base,
        id="incompatible",
        bedrooms=3,
        bedrooms_is_exact=False,
        bedrooms_min=3,
        bedrooms_max=4,
    )

    ranked = filter_and_rank([overlapping, incompatible], req, top_n=10)

    assert [item.listing.id for item in ranked] == ["overlap"]
    assert "bedroom range requires unit-level verification" in ranked[0].tradeoffs


def test_exact_bedroom_is_not_marked_as_range_unknown_when_bathroom_is_missing():
    req = SearchRequirements(city="Mountain View", min_bedrooms=2, max_bedrooms=2)
    base = MockListingProvider().search(SearchRequirements(city="Mountain View"))[0]
    listing = replace(
        base,
        id="exact-bedroom-missing-bath",
        bedrooms=2,
        bedrooms_is_exact=True,
        bedrooms_min=2,
        bedrooms_max=2,
        bathrooms=None,
        bathrooms_min_evidence=None,
    )

    ranked = filter_and_rank([listing], req, top_n=10)

    assert [item.listing.id for item in ranked] == ["exact-bedroom-missing-bath"]
    assert "2 bed" in ranked[0].reasons
    assert "bedroom range requires unit-level verification" not in ranked[0].tradeoffs


def test_query_backed_pet_and_parking_evidence_is_not_described_as_confirmed():
    req = SearchRequirements(
        city="Mountain View",
        pets_required=True,
        parking_required=True,
    )
    base = MockListingProvider().search(SearchRequirements(city="Mountain View"))[0]
    query_backed = replace(
        base,
        id="query-backed",
        pets_allowed=True,
        parking_available=True,
        query_backed_fields=("pets_allowed", "parking_available"),
    )

    ranked = filter_and_rank([query_backed], req, top_n=10)

    assert [item.listing.id for item in ranked] == ["query-backed"]
    assert "pets confirmed allowed" not in ranked[0].reasons
    assert "parking confirmed available" not in ranked[0].reasons
    assert "pet allowance is search-filter evidence; verify policy" in ranked[0].tradeoffs
    assert "parking is search-filter evidence; verify availability" in ranked[0].tradeoffs
