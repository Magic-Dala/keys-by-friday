from __future__ import annotations

import json
from pathlib import Path

import pytest

from rental_agent.providers.realtyapi import normalize_realtyapi_listing


FIXTURE_PATH = Path(__file__).parent / "fixtures" / "canonical_listing_v1.json"


def _fixture() -> dict[str, object]:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


def test_agent_generates_the_golden_backend_contract() -> None:
    """Any Agent-side contract drift must update this explicit backend fixture."""
    from rental_agent.models import Listing

    listing = Listing(
        id="example-001",
        source_listing_id="provider-example-001",
        property_name="Example Apartments",
        address="123 Example St, Mountain View, CA 94040",
        city="Mountain View",
        state="CA",
        zip_code="94040",
        country_code="US",
        latitude=37.4001,
        longitude=-122.1001,
        rent=3800.0,
        rent_min=3200.0,
        rent_max=3800.0,
        bedrooms=3.0,
        bedrooms_min=2.0,
        bedrooms_max=3.0,
        bathrooms=None,
        bathrooms_min_evidence=2.0,
        property_type="Apartment",
        is_multifamily=True,
        rating=4.2,
        availability="Available Now",
        has_availability=True,
        pets_allowed=True,
        parking_available=True,
        amenities=("Parking", "Gym", "Washer Dryer"),
        specialties=("Short Term",),
        rent_deals_count=1,
        primary_image_url="https://example.test/images/example-001.jpg",
        attachment_count=12,
        phone="(650) 555-0100",
        property_manager_name="Example Residential",
        property_manager_company_id="example-company-1",
        has_lead_email=True,
        source="realtyapi-apartments",
        source_url="https://example.test/listings/example-001",
        detail_verified=False,
        query_backed_fields=(
            "bathrooms_min_evidence",
            "pets_allowed",
            "parking_available",
        ),
    )

    assert listing.to_backend_dict() == _fixture()


@pytest.mark.parametrize(
    ("bounds", "expected_pricing", "expected_bedrooms"),
    [
        (
            {"minRent": 3100, "minBeds": 2, "minBaths": 1.5},
            {"rent": None, "rentMin": 3100.0, "rentMax": None},
            {"bedrooms": None, "bedroomsMin": 2.0, "bedroomsMax": None},
        ),
        (
            {"maxRent": 3900, "maxBeds": 3},
            {"rent": None, "rentMin": None, "rentMax": 3900.0},
            {"bedrooms": None, "bedroomsMin": None, "bedroomsMax": 3.0},
        ),
        (
            {"minRent": 3000, "maxRent": 3900, "minBeds": 1, "maxBeds": 3},
            {"rent": None, "rentMin": 3000.0, "rentMax": 3900.0},
            {"bedrooms": None, "bedroomsMin": 1.0, "bedroomsMax": 3.0},
        ),
        (
            {"minRent": 3200, "maxRent": 3200, "minBeds": 2, "maxBeds": 2},
            {"rent": 3200.0, "rentMin": 3200.0, "rentMax": 3200.0},
            {"bedrooms": 2.0, "bedroomsMin": 2.0, "bedroomsMax": 2.0},
        ),
        (
            {"minRent": 3900, "maxRent": 3000, "minBeds": 3, "maxBeds": 1},
            {"rent": None, "rentMin": None, "rentMax": None},
            {"bedrooms": None, "bedroomsMin": None, "bedroomsMax": None},
        ),
    ],
)
def test_canonical_bounds_do_not_become_exact_facts(
    bounds: dict[str, float],
    expected_pricing: dict[str, float | None],
    expected_bedrooms: dict[str, float | None],
) -> None:
    raw = {
        "listingKey": "bounds-1",
        "oneLineAddress": "100 Castro St, Mountain View, CA 94041",
        "address": {"city": "Mountain View", "state": "CA", "postalCode": "94041"},
        **bounds,
    }

    listing = normalize_realtyapi_listing(raw)
    canonical = listing.to_backend_dict()

    assert canonical["pricing"] == expected_pricing
    assert {
        key: canonical["property"][key]
        for key in ("bedrooms", "bedroomsMin", "bedroomsMax")
    } == expected_bedrooms
    if "minBaths" in bounds:
        assert listing.bathrooms is None
        assert canonical["property"]["bathrooms"] is None
        assert canonical["property"]["bathroomsMinEvidence"] == 1.5
        assert "property.bathroomsMinEvidence" not in canonical["evidence"][
            "queryBackedFields"
        ]


def test_missing_critical_fields_remain_unknown_without_crashing() -> None:
    canonical = normalize_realtyapi_listing({}).to_backend_dict()

    assert canonical["identity"]["id"] == ""
    assert canonical["pricing"] == {"rent": None, "rentMin": None, "rentMax": None}
    assert canonical["property"]["bedrooms"] is None
    assert "identity.id" in canonical["completeness"]["criticalUnknownFields"]
    assert "location.address" in canonical["completeness"]["criticalUnknownFields"]
    assert "source.url" in canonical["completeness"]["criticalUnknownFields"]


def test_provider_exact_values_remain_exact_even_with_range_metadata() -> None:
    listing = normalize_realtyapi_listing(
        {
            "listingKey": "exact-1",
            "oneLineAddress": "100 Castro St, Mountain View, CA 94041",
            "address": {"city": "Mountain View", "state": "CA"},
            "rent": 3500,
            "minRent": 3000,
            "maxRent": 3900,
            "beds": 2,
            "minBeds": 1,
            "maxBeds": 3,
            "baths": 2,
            "minBaths": 1.5,
        }
    )

    canonical = listing.to_backend_dict()
    assert canonical["pricing"]["rent"] == 3500.0
    assert canonical["property"]["bedrooms"] == 2.0
    assert canonical["property"]["bathrooms"] == 2.0
    assert canonical["property"]["bathroomsMinEvidence"] == 1.5


def test_legacy_representative_does_not_survive_conflicting_bounds_as_exact() -> None:
    from rental_agent.models import Listing

    canonical = Listing(
        id="legacy-conflict",
        address="100 Castro St",
        city="Mountain View",
        state="CA",
        zip_code=None,
        rent=3000,
        bedrooms=1,
        bathrooms=None,
        rent_min=3900,
        rent_max=3000,
        bedrooms_min=3,
        bedrooms_max=1,
    ).to_backend_dict()

    assert canonical["pricing"] == {"rent": None, "rentMin": None, "rentMax": None}
    assert canonical["property"]["bedrooms"] is None
    assert canonical["property"]["bedroomsMin"] is None
    assert canonical["property"]["bedroomsMax"] is None
