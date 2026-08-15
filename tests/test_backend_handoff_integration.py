from __future__ import annotations

from backend.app.services.agent_service import _normalize_tool_listings
from rental_agent import agent as agent_module
from rental_agent.models import SearchRequirements
from rental_agent.providers.realtyapi import normalize_realtyapi_listing


class _FakeProvider:
    raw = {
        "listingKey": "min-only-1",
        "oneLineAddress": "100 Castro St, Mountain View, CA 94041",
        "address": {
            "city": "Mountain View",
            "state": "CA",
            "postalCode": "94041",
        },
        "minRent": 3100,
        "minBeds": 2,
        "minBaths": 1.5,
    }

    def search(self, requirements: SearchRequirements):
        return [normalize_realtyapi_listing(self.raw, requirements=requirements)]

    def get_listing(self, listing_id: str):
        assert listing_id == "min-only-1"
        return normalize_realtyapi_listing(self.raw, detail_verified=True)

    def health(self) -> dict[str, object]:
        return {"provider": "fake-realtyapi", "search_complete": True, "failed_sources": []}


def test_production_tool_handoff_preserves_min_only_semantics(monkeypatch) -> None:
    provider = _FakeProvider()
    monkeypatch.setattr(agent_module, "get_provider", lambda: provider)

    search_payload = agent_module.search_listings(
        city="Mountain View",
        state="CA",
        min_bedrooms=2,
        min_bathrooms=1.5,
    )

    representative = search_payload["top_5"][0]
    assert representative["listing"]["rent"] == 3100.0
    assert representative["listing"]["bedrooms"] == 2.0
    assert representative["backend_listing"]["schemaVersion"] == "kbf.canonical-listing.v1"
    assert representative["backend_listing"]["pricing"] == {
        "rent": None,
        "rentMin": 3100.0,
        "rentMax": None,
    }
    assert representative["backend_listing"]["property"]["bedrooms"] is None
    assert representative["backend_listing"]["property"]["bedroomsMin"] == 2.0
    assert representative["backend_listing"]["property"]["bathrooms"] is None
    assert representative["backend_listing"]["property"]["bathroomsMinEvidence"] == 1.5

    backend_results = _normalize_tool_listings(search_payload, [])
    assert len(backend_results) == 1
    backend_listing = backend_results[0]
    assert backend_listing.price is None
    assert backend_listing.priceMin == 3100.0
    assert backend_listing.priceMax is None
    assert backend_listing.bedrooms is None
    assert backend_listing.bedroomsMin == 2.0
    assert backend_listing.bedroomsMax is None
    assert backend_listing.bathrooms is None
    assert backend_listing.bathroomsMinEvidence == 1.5
    assert len(backend_listing.sourcePostings) == 1
    assert backend_listing.sourcePostings[0].price is None
    assert backend_listing.sourcePostings[0].priceMin == 3100.0

    detail_payload = agent_module.get_listing_details("min-only-1")
    assert detail_payload["backend_listing"]["schemaVersion"] == "kbf.canonical-listing.v1"
    detail_results = _normalize_tool_listings(None, [detail_payload])
    assert detail_results[0].price is None
    assert detail_results[0].priceMin == 3100.0
    assert detail_results[0].bathrooms is None
    assert detail_results[0].bathroomsMinEvidence == 1.5


def test_backend_drops_listing_without_required_identity(monkeypatch) -> None:
    class MissingIdentityProvider(_FakeProvider):
        raw = {"address": {"city": "Mountain View", "state": "CA"}}

    monkeypatch.setattr(agent_module, "get_provider", lambda: MissingIdentityProvider())
    search_payload = agent_module.search_listings(city="Mountain View", state="CA")

    canonical = search_payload["top_5"][0]["backend_listing"]
    assert "identity.id" in canonical["completeness"]["criticalUnknownFields"]
    assert _normalize_tool_listings(search_payload, []) == []
