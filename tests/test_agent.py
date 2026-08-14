import pytest

from rental_agent import agent as agent_module
from rental_agent.agent import root_agent, search_listings
from rental_agent.models import Listing
from rental_agent.providers import get_provider


def test_agent_has_only_two_listing_tools():
    assert root_agent.name == "single_rental_agent"
    assert [tool.__name__ for tool in root_agent.tools] == [
        "search_listings",
        "get_listing_details",
    ]


def test_agent_output_contract_requires_links_and_markdown():
    instruction = str(root_agent.instruction)
    assert "[ADDRESS](SOURCE_URL)" in instruction
    assert "**Why it fits:**" in instruction
    assert "**Tradeoffs:**" in instruction
    assert "Do not show raw scores" in instruction
    assert "top_10" in instruction
    assert "Do NOT automatically call get_listing_details" in instruction


def test_mock_tool_path_works_without_external_keys(monkeypatch):
    monkeypatch.setenv("LISTING_PROVIDER", "mock")
    monkeypatch.delenv("REALTYAPI_API_KEY", raising=False)
    get_provider.cache_clear()

    result = search_listings(
        city="Mountain View",
        max_rent=4000,
        min_bedrooms=2,
        min_bathrooms=2,
        soft_preferences="quiet, near transit",
    )

    assert result["provider"] == "mock"
    assert result["matched_count"] == 4
    assert len(result["top_10"]) == 4
    assert len(result["top_5"]) == 4
    assert result["soft_preferences_unverified"] == ["quiet", "near transit"]


def test_search_returns_up_to_ten_candidates_and_keeps_top5_alias(monkeypatch):
    class TwelveListingProvider:
        def search(self, requirements):
            return [
                Listing(
                    id=f"candidate-{index:02d}",
                    address=f"{100 + index} Test St",
                    city=requirements.city,
                    state=requirements.state,
                    zip_code=None,
                    rent=3000 + index,
                    bedrooms=2,
                    bathrooms=2,
                    property_type="Apartment",
                    status="active",
                    source="test-source",
                    source_url=f"https://example.test/{index}",
                )
                for index in range(12)
            ]

        def get_listing(self, listing_id):
            raise AssertionError("detail lookup should not be needed for broad search")

        def health(self):
            return {"ok": True, "provider": "twelve-listings"}

    monkeypatch.setattr(agent_module, "get_provider", lambda: TwelveListingProvider())

    result = search_listings(
        city="Mountain View",
        max_rent=4000,
        min_bedrooms=2,
    )

    assert result["provider"] == "twelve-listings"
    assert result["matched_count"] == 10
    assert len(result["top_10"]) == 10
    assert len(result["top_5"]) == 5
    assert result["top_5"] == result["top_10"][:5]
    assert [item["listing"]["id"] for item in result["top_10"]] == [
        f"candidate-{index:02d}" for index in range(10)
    ]


def test_real_mode_without_realtyapi_key_fails_clearly(monkeypatch):
    monkeypatch.setenv("LISTING_PROVIDER", "realtyapi")
    monkeypatch.delenv("REALTYAPI_API_KEY", raising=False)
    get_provider.cache_clear()

    with pytest.raises(RuntimeError, match="REALTYAPI_API_KEY is missing"):
        get_provider()

    get_provider.cache_clear()
