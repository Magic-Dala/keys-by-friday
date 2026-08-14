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
