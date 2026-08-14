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


def test_agent_output_contract_requires_compact_grouped_lists():
    instruction = str(root_agent.instruction)
    assert "display_sections.cross_listed" in instruction
    assert "**Active filters:** {active_filters}" in instruction
    assert "## Cross-listed" in instruction
    assert "## Other matches" in instruction
    assert "Do NOT use a Markdown table" in instruction
    assert "Do not print `Unknown`" in instruction
    assert "internal IDs" in instruction
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


def test_search_returns_all_properties_and_keeps_top_aliases(monkeypatch):
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
    assert result["matched_count"] == 12
    assert result["posting_count"] == 12
    assert len(result["property_groups"]) == 12
    assert len(result["top_10"]) == 10
    assert len(result["top_5"]) == 5
    assert result["top_5"] == result["top_10"][:5]
    assert [item["representative"]["listing"]["id"] for item in result["property_groups"]] == [
        f"candidate-{index:02d}" for index in range(12)
    ]


def test_same_property_posted_on_multiple_sources_is_grouped_but_units_stay_separate(monkeypatch):
    class MultiPostProvider:
        def search(self, requirements):
            def listing(identifier, address, source, rent=3800):
                return Listing(
                    id=identifier,
                    address=address,
                    city=requirements.city,
                    state=requirements.state,
                    zip_code="94041",
                    rent=rent,
                    bedrooms=2,
                    bathrooms=2,
                    property_type="Apartment",
                    status="active",
                    source=source,
                    source_url=f"https://example.test/{identifier}",
                )
            return [
                listing("apt-main", "100 Castro Street, Mountain View, CA 94041", "realtyapi-apartments"),
                listing("apt-main-duplicate", "100 Castro St", "realtyapi-apartments", 3810),
                listing("z-main", "100 Castro St", "realtyapi-zillow"),
                listing("r-main", "100 Castro St", "realtyapi-realtor"),
                listing("apt-unit2", "100 Castro St Apt 2, Mountain View, CA 94041", "realtyapi-apartments", 3900),
                listing("z-unit2", "100 Castro St #2", "realtyapi-zillow", 3900),
            ]

        def get_listing(self, listing_id):
            raise AssertionError("detail lookup should not be needed for broad search")

        def health(self):
            return {"ok": True, "provider": "multi-post"}

    monkeypatch.setattr(agent_module, "get_provider", lambda: MultiPostProvider())
    result = search_listings(city="Mountain View", max_rent=4000, min_bedrooms=2)

    assert result["posting_count"] == 5
    assert result["matched_count"] == 2
    groups = result["property_groups"]
    assert {item["listing"]["id"] for item in groups[0]["postings"]} == {
        "apt-main", "z-main", "r-main"
    }
    assert groups[0]["source_count"] == 3
    assert groups[0]["display"]["rent"] == "$3,800"
    assert {source["label"] for source in groups[0]["display"]["sources"]} == {
        "Apartments.com", "Zillow", "Realtor.com"
    }
    assert {item["listing"]["id"] for item in groups[1]["postings"]} == {
        "apt-unit2", "z-unit2"
    }
    assert groups[1]["source_count"] == 2
    rows = result["property_rows"]
    assert rows[0]["address"] == "100 Castro Street"
    assert rows[0]["full_address"] == "100 Castro Street, Mountain View, CA 94041"
    assert rows[0]["beds"] == "2"
    assert rows[0]["baths"] == "2"
    assert "[Apartments.com](https://example.test/apt-main)" in rows[0]["sources"]
    assert "[Zillow](https://example.test/z-main)" in rows[0]["sources"]
    assert "[Realtor.com](https://example.test/r-main)" in rows[0]["sources"]
    sections = result["display_sections"]
    assert result["cross_listed_count"] == 2
    assert sections["cross_listed"][0].startswith("1. **100 Castro Street** — $3,800 · 2 bd · 2 ba")
    assert "Apartments.com" in sections["cross_listed"][0]
    assert "Zillow" in sections["cross_listed"][0]
    assert "Realtor.com" in sections["cross_listed"][0]
    assert sections["cross_listed"][1].startswith("2. **100 Castro St Apt 2** — $3,900 · 2 bd · 2 ba")
    assert sections["other_matches"] == []


def test_real_mode_without_realtyapi_key_fails_clearly(monkeypatch):
    monkeypatch.setenv("LISTING_PROVIDER", "realtyapi")
    monkeypatch.delenv("REALTYAPI_API_KEY", raising=False)
    get_provider.cache_clear()

    with pytest.raises(RuntimeError, match="REALTYAPI_API_KEY is missing"):
        get_provider()

    get_provider.cache_clear()


def test_query_backed_bathroom_minimum_displays_as_lower_bound(monkeypatch):
    class ZillowEvidenceProvider:
        def search(self, requirements):
            return [
                Listing(
                    id="zillow:123",
                    address="123 Test Ave",
                    city=requirements.city,
                    state=requirements.state,
                    zip_code="94040",
                    rent=3500,
                    bedrooms=2,
                    bathrooms=None,
                    source="realtyapi-zillow",
                    source_url="https://www.zillow.com/homedetails/123_zpid/",
                    bathrooms_min_evidence=2,
                )
            ]

        def get_listing(self, listing_id):
            raise AssertionError("detail lookup should not be needed")

        def health(self):
            return {"ok": True, "provider": "zillow-evidence"}

    monkeypatch.setattr(agent_module, "get_provider", lambda: ZillowEvidenceProvider())
    result = search_listings(
        city="Mountain View",
        max_rent=4000,
        min_bedrooms=2,
        min_bathrooms=2,
    )

    assert result["matched_count"] == 1
    assert result["property_rows"][0]["baths"] == "2+"
    assert "[Zillow](https://www.zillow.com/homedetails/123_zpid/)" in (
        result["property_rows"][0]["sources"]
    )
