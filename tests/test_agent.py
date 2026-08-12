import pytest

from rental_agent.agent import root_agent, search_listings
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
    assert len(result["top_5"]) == 4
    assert result["soft_preferences_unverified"] == ["quiet", "near transit"]


def test_real_mode_without_realtyapi_key_fails_clearly(monkeypatch):
    monkeypatch.setenv("LISTING_PROVIDER", "realtyapi")
    monkeypatch.delenv("REALTYAPI_API_KEY", raising=False)
    get_provider.cache_clear()

    with pytest.raises(RuntimeError, match="REALTYAPI_API_KEY is missing"):
        get_provider()

    get_provider.cache_clear()
