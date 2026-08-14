from __future__ import annotations

import json
from pathlib import Path


FIXTURE_PATH = Path(__file__).parent / "fixtures" / "canonical_listing_v1.json"
DATA_SECTIONS = (
    "identity",
    "location",
    "pricing",
    "property",
    "availability",
    "policies",
    "features",
    "media",
    "contact",
    "source",
)


def _fixture() -> dict[str, object]:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


def test_fixture_is_backend_consumer_contract() -> None:
    """Backend can consume this fixture without importing Agent/provider internals."""
    payload = _fixture()

    assert payload["schemaVersion"] == "kbf.canonical-listing.v1"
    assert set(payload) == {"schemaVersion", *DATA_SECTIONS, "evidence", "completeness"}

    for section in DATA_SECTIONS:
        assert isinstance(payload[section], dict), section

    location = payload["location"]
    assert isinstance(location["latitude"], (int, float))
    assert isinstance(location["longitude"], (int, float))

    pricing = payload["pricing"]
    assert pricing["rent"] is None
    assert pricing["rentMin"] == 3200.0
    assert pricing["rentMax"] == 3800.0
    assert pricing["rentMin"] <= pricing["rentMax"]

    property_data = payload["property"]
    assert property_data["bedrooms"] is None
    assert property_data["bedroomsMin"] == 2.0
    assert property_data["bedroomsMax"] == 3.0
    assert property_data["bedroomsMin"] <= property_data["bedroomsMax"]
    assert property_data["bathrooms"] is None
    assert property_data["bathroomsMinEvidence"] == 2.0

    evidence = payload["evidence"]
    assert evidence["detailVerified"] is False
    assert set(evidence["criticalQueryBackedFields"]) <= set(evidence["queryBackedFields"])

    completeness = payload["completeness"]
    known = completeness["knownFields"]
    unknown = completeness["unknownFields"]
    assert not (set(known) & set(unknown))
    assert completeness["knownCount"] == len(known)
    assert completeness["totalCount"] == len(known) + len(unknown)
    assert completeness["ratio"] == round(len(known) / completeness["totalCount"], 3)
    assert completeness["criticalUnknownFields"] == []
    assert completeness["mapReady"] is True
    assert completeness["cardReady"] is True
    assert completeness["comparisonReady"] is True
    assert completeness["decisionReady"] is False
    assert completeness["verificationRequired"] is True

    # The handoff is plain JSON: no dataclasses, provider objects, or ADK types leak through.
    assert json.loads(json.dumps(payload)) == payload


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
