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
        def search(self, requirements):
            return [
                replace(
                    listing,
                    bathrooms_min_evidence=requirements.min_bathrooms,
                    query_backed_fields=(
                        "bathrooms_min_evidence",
                        "pets_allowed",
                        "parking_available",
                    ),
                )
                for listing in super().search(requirements)
            ]

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
    assert listing["bathrooms_min_evidence"] == 2
    assert listing["query_backed_fields"] == ("bathrooms_min_evidence",)
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


def test_narrower_followups_reuse_session_cache_before_provider_search(monkeypatch):
    class CountingProvider(MockListingProvider):
        def __init__(self):
            super().__init__()
            self.search_calls = 0

        def search(self, requirements):
            self.search_calls += 1
            return super().search(requirements)

        def health(self):
            return {"ok": True, "provider": "realtyapi-multi"}

    provider = CountingProvider()
    monkeypatch.setattr(agent_module, "get_provider", lambda: provider)
    context = SimpleNamespace(state={})

    first = search_listings(
        city="Mountain View",
        max_rent=4000,
        min_bedrooms=2,
        tool_context=context,
    )
    assert provider.search_calls == 1
    assert first["data_source"] == "realtyapi"
    assert first["provider_search_performed"] is True

    baths = search_listings(min_bathrooms=2, tool_context=context)
    assert provider.search_calls == 1
    assert baths["data_source"] == "session_cache"
    assert baths["provider_search_performed"] is False

    parking = search_listings(parking_required=True, tool_context=context)
    assert provider.search_calls == 1
    assert parking["data_source"] == "session_cache"

    pets = search_listings(pets_required=True, tool_context=context)
    assert provider.search_calls == 1
    assert pets["data_source"] == "session_cache"
    assert pets["matched_count"] > 0

    # No cached listing can satisfy this stricter budget, so one fresh provider
    # search is allowed to look for source-side matches/evidence.
    empty = search_listings(max_rent=3000, tool_context=context)
    assert provider.search_calls == 2
    assert empty["data_source"] == "realtyapi"
    assert empty["refresh_reason"] == "cache_had_no_matches"
    assert empty["matched_count"] == 0

    # Repeating the exact same empty search must not burn another provider call.
    repeated = search_listings(tool_context=context)
    assert provider.search_calls == 2
    assert repeated["data_source"] == "session_cache"
    assert repeated["matched_count"] == 0


def test_incomplete_multi_source_cache_is_retried_before_reuse(monkeypatch):
    class IncompleteThenCompleteProvider(MockListingProvider):
        def __init__(self):
            super().__init__()
            self.search_calls = 0
            self.search_complete = False

        def search(self, requirements):
            self.search_calls += 1
            self.search_complete = self.search_calls > 1
            return super().search(requirements)

        def health(self):
            return {
                "ok": True,
                "provider": "realtyapi-multi",
                "search_complete": self.search_complete,
                "failed_sources": [] if self.search_complete else ["zillow"],
            }

    provider = IncompleteThenCompleteProvider()
    monkeypatch.setattr(agent_module, "get_provider", lambda: provider)
    context = SimpleNamespace(state={})

    first = search_listings(
        city="Mountain View",
        max_rent=4000,
        min_bedrooms=2,
        tool_context=context,
    )
    assert provider.search_calls == 1
    assert first["search_complete"] is False
    assert first["failed_sources"] == ["zillow"]

    refined = search_listings(parking_required=True, tool_context=context)
    assert provider.search_calls == 2
    assert refined["provider_search_performed"] is True
    assert refined["refresh_reason"] == "incomplete_cache"
    assert refined["search_complete"] is True

    cached = search_listings(pets_required=True, tool_context=context)
    assert provider.search_calls == 2
    assert cached["provider_search_performed"] is False
    assert cached["data_source"] == "session_cache"


def test_broadened_scope_and_force_refresh_call_provider(monkeypatch):
    class CountingProvider(MockListingProvider):
        def __init__(self):
            super().__init__()
            self.search_calls = 0

        def search(self, requirements):
            self.search_calls += 1
            return super().search(requirements)

        def health(self):
            return {"ok": True, "provider": "realtyapi-multi"}

    provider = CountingProvider()
    monkeypatch.setattr(agent_module, "get_provider", lambda: provider)
    context = SimpleNamespace(state={})

    search_listings(city="Mountain View", max_rent=3500, min_bedrooms=2, tool_context=context)
    assert provider.search_calls == 1

    broader = search_listings(max_rent=4000, tool_context=context)
    assert provider.search_calls == 2
    assert broader["refresh_reason"] == "expanded_or_changed_scope"

    refreshed = search_listings(force_refresh=True, tool_context=context)
    assert provider.search_calls == 3
    assert refreshed["refresh_reason"] == "force_refresh"


def test_legacy_realtyapi_cache_without_completeness_is_refreshed(monkeypatch):
    class CountingProvider(MockListingProvider):
        def __init__(self):
            super().__init__()
            self.search_calls = 0

        def search(self, requirements):
            self.search_calls += 1
            return super().search(requirements)

        def health(self):
            return {"ok": True, "provider": "realtyapi-multi"}

    provider = CountingProvider()
    monkeypatch.setattr(agent_module, "get_provider", lambda: provider)
    context = SimpleNamespace(state={})

    search_listings(
        city="Mountain View",
        max_rent=4000,
        min_bedrooms=2,
        min_bathrooms=2,
        tool_context=context,
    )
    search_listings(parking_required=True, tool_context=context)
    assert provider.search_calls == 1

    # A legacy RealtyAPI session has no completeness evidence. It must be
    # refreshed instead of being treated as an authoritative cache.
    context.state.pop(agent_module._RAW_CACHE_STATE_KEY, None)
    context.state.pop(agent_module._CACHE_SCOPE_STATE_KEY, None)
    context.state.pop(agent_module._CACHE_PROVIDER_STATE_KEY, None)
    context.state.pop(agent_module._CACHE_COMPLETE_STATE_KEY, None)
    context.state.pop(agent_module._CACHE_FAILED_SOURCES_STATE_KEY, None)

    pets = search_listings(pets_required=True, tool_context=context)

    assert provider.search_calls == 2
    assert pets["provider_search_performed"] is True
    assert pets["data_source"] == "realtyapi"
    assert pets["refresh_reason"] == "incomplete_cache"
    assert pets["matched_count"] > 0
    assert pets["effective_requirements"]["parking_required"] is True
    assert pets["effective_requirements"]["pets_required"] is True
    assert agent_module._RAW_CACHE_STATE_KEY in context.state
    assert agent_module._CACHE_SCOPE_STATE_KEY in context.state


def test_visible_group_rank_matches_verification_rank(monkeypatch):
    class RankProvider:
        def __init__(self):
            self.by_id: dict[str, Listing] = {}

        def search(self, requirements):
            listings = [
                Listing(
                    id="cheap-single",
                    address="10 Cheap St, Mountain View, CA 94041",
                    city=requirements.city,
                    state=requirements.state,
                    zip_code="94041",
                    rent=3000,
                    bedrooms=2,
                    bathrooms=2,
                    source="realtyapi-apartments",
                    source_url="https://example.test/cheap",
                ),
                Listing(
                    id="cross-a",
                    address="20 Cross Street, Mountain View, CA 94041",
                    city=requirements.city,
                    state=requirements.state,
                    zip_code="94041",
                    rent=3500,
                    bedrooms=2,
                    bathrooms=2,
                    source="realtyapi-apartments",
                    source_url="https://example.test/cross-a",
                ),
                Listing(
                    id="cross-z",
                    address="20 Cross St, Mountain View, CA 94041",
                    city=requirements.city,
                    state=requirements.state,
                    zip_code="94041",
                    rent=3500,
                    bedrooms=2,
                    bathrooms=2,
                    source="realtyapi-zillow",
                    source_url="https://example.test/cross-z",
                ),
            ]
            self.by_id = {listing.id: listing for listing in listings}
            return listings

        def get_listing(self, listing_id):
            return replace(self.by_id[listing_id], detail_verified=True)

        def health(self):
            return {"ok": True, "provider": "realtyapi-multi"}

    provider = RankProvider()
    monkeypatch.setattr(agent_module, "get_provider", lambda: provider)
    context = SimpleNamespace(state={})

    result = search_listings(
        city="Mountain View",
        max_rent=4000,
        min_bedrooms=2,
        tool_context=context,
    )

    assert result["property_groups"][0]["representative"]["listing"]["id"] == "cross-a"
    assert result["property_groups"][0]["rank"] == 1
    assert result["display_sections"]["cross_listed"][0].startswith(
        "1. **20 Cross Street**"
    )
    assert result["display_sections"]["other_matches"][0].startswith(
        "2. **10 Cheap St**"
    )
    assert result["verification_candidates"][0] == {
        "rank": 1,
        "listing_id": "cross-a",
        "address": "20 Cross Street, Mountain View, CA 94041",
    }
    assert result["top_5"][0]["listing"]["id"] == "cross-a"

    verified_alternate = get_listing_details("cross-z", tool_context=context)
    assert verified_alternate["verification"]["current_search_rank"] == 1
