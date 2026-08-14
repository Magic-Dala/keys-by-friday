from dataclasses import replace
from types import SimpleNamespace

from rental_agent import agent as agent_module
from rental_agent.agent import get_listing_details, search_listings
from rental_agent.models import Listing
from rental_agent.providers import get_provider
from rental_agent.providers.mock import MockListingProvider


def test_session_memory_inherits_omitted_requirements_and_can_reset(monkeypatch):
    monkeypatch.setenv("LISTING_PROVIDER", "mock")
    get_provider.cache_clear()
    context = SimpleNamespace(state={})

    first = search_listings(
        city="Mountain View",
        max_rent=4000,
        min_bedrooms=2,
        min_bathrooms=2,
        soft_preferences="quiet, near transit",
        tool_context=context,
    )
    assert first["memory_used"] is False
    assert [item["listing"]["id"] for item in first["top_5"]] == [
        "mv-6",
        "mv-1",
        "mv-5",
        "mv-2",
    ]
    assert [item["listing_id"] for item in first["verification_candidates"]] == [
        "mv-6",
        "mv-1",
        "mv-5",
    ]

    refined = search_listings(
        max_rent=3800,
        soft_preferences="prefer cheaper",
        tool_context=context,
    )
    req = refined["effective_requirements"]
    assert refined["memory_used"] is True
    assert req["city"] == "Mountain View"
    assert req["max_rent"] == 3800
    assert req["min_bedrooms"] == 2
    assert req["min_bathrooms"] == 2
    assert req["soft_preferences"] == ["quiet", "near transit", "prefer cheaper"]
    assert [item["listing"]["id"] for item in refined["top_5"]] == [
        "mv-1",
        "mv-5",
    ]

    reset = search_listings(
        city="Sunnyvale",
        max_rent=4000,
        min_bedrooms=2,
        reset_search=True,
        tool_context=context,
    )
    reset_req = reset["effective_requirements"]
    assert reset["memory_used"] is False
    assert reset_req["city"] == "Sunnyvale"
    assert reset_req["min_bathrooms"] is None
    assert reset_req["soft_preferences"] == []

    get_provider.cache_clear()


def test_detail_verification_merges_search_evidence_and_rechecks_hard_filters(monkeypatch):
    class DetailMockProvider(MockListingProvider):
        def get_listing(self, listing_id: str) -> Listing:
            base = super().get_listing(listing_id)
            return replace(
                base,
                rent=None,
                bathrooms=None,
                availability="Available now",
                amenities=("Gym", "Washer/Dryer"),
                pet_policy="Cats Allowed; Dogs Allowed",
                parking_policy="Covered",
                detail_verified=True,
            )

    provider = DetailMockProvider()
    monkeypatch.setattr(agent_module, "get_provider", lambda: provider)
    context = SimpleNamespace(state={})

    search = search_listings(
        city="Mountain View",
        max_rent=4000,
        min_bedrooms=2,
        min_bathrooms=2,
        tool_context=context,
    )
    first_id = search["verification_candidates"][0]["listing_id"]

    verified = get_listing_details(first_id, tool_context=context)
    listing = verified["listing"]
    verification = verified["verification"]

    assert listing["rent"] == 3990
    assert listing["bathrooms"] == 2.5
    assert listing["availability"] == "Available now"
    assert listing["amenities"] == ("Gym", "Washer/Dryer")
    assert listing["pet_policy"] == "Cats Allowed; Dogs Allowed"
    assert listing["parking_policy"] == "Covered"
    assert listing["detail_verified"] is True
    assert verification["current_search_rank"] == 1
    assert verification["passes_current_hard_filters"] is True


def test_session_memory_accumulates_bath_parking_pet_and_budget(monkeypatch):
    monkeypatch.setenv("LISTING_PROVIDER", "mock")
    get_provider.cache_clear()
    context = SimpleNamespace(state={})

    search_listings(
        city="Mountain View",
        max_rent=4000,
        min_bedrooms=2,
        min_bathrooms=2,
        tool_context=context,
    )
    search_listings(parking_required=True, tool_context=context)
    search_listings(pets_required=True, tool_context=context)
    final = search_listings(max_rent=3600, tool_context=context)

    req = final["effective_requirements"]
    assert final["memory_used"] is True
    assert req["city"] == "Mountain View"
    assert req["state"] == "CA"
    assert req["max_rent"] == 3600
    assert req["min_bedrooms"] == 2
    assert req["min_bathrooms"] == 2
    assert req["parking_required"] is True
    assert req["pets_required"] is True
    assert final["active_filters"] == (
        "Mountain View, CA · ≤$3,600 · 2+ bd · 2+ ba · parking · pet-friendly"
    )

    get_provider.cache_clear()
