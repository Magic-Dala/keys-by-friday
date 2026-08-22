import pytest

from rental_agent import agent as agent_module
from rental_agent.agent import root_agent, search_listings
from rental_agent.models import Listing
from rental_agent.providers import get_provider


def test_agent_has_listing_route_and_comparison_tools():
    assert root_agent.name == "single_rental_agent"
    assert [tool.__name__ for tool in root_agent.tools] == [
        "search_listings",
        "get_listing_details",
        "get_route_details",
        "compare_candidates",
    ]


def test_agent_output_contract_requires_compact_grouped_lists():
    instruction = str(root_agent.instruction)
    assert "display_sections.cross_listed" in instruction
    assert "**Active filters:** " in instruction
    assert "{active_filters}" not in instruction
    assert "## Cross-listed" in instruction
    assert "## Other matches" in instruction
    assert "Do NOT use a Markdown table" in instruction
    assert "Do not print `Unknown`" in instruction
    assert "internal IDs" in instruction
    assert "Do NOT automatically call get_listing_details" in instruction
    assert '"2 bedroom", "2-bedroom", "2 bed"' in instruction
    assert "same value as both the minimum and" in instruction
    assert '"2B2B" means minimum 2 bedrooms' in instruction
    assert "bounded to at most 20 source postings" in instruction
    assert "call get_listing_details at most once" in instruction


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


def test_agent_search_caps_provider_request_and_returned_postings(monkeypatch):
    seen_limits: list[int] = []

    class OversizedProvider:
        def search(self, requirements):
            seen_limits.append(requirements.limit)
            return [
                Listing(
                    id=f"oversized-{index:02d}",
                    address=f"{200 + index} Cost Guardrail St",
                    city=requirements.city,
                    state=requirements.state,
                    zip_code=None,
                    rent=3000 + index,
                    bedrooms=2,
                    bathrooms=2,
                    source="test-source",
                    source_url=f"https://example.test/oversized/{index}",
                )
                for index in range(30)
            ]

        def health(self):
            return {"ok": True, "provider": "oversized-provider"}

    monkeypatch.setattr(agent_module, "get_provider", lambda: OversizedProvider())

    result = search_listings(city="Mountain View", max_rent=4000, min_bedrooms=2)

    assert seen_limits == [20]
    assert result["effective_requirements"]["limit"] == 20
    assert result["matched_count"] == 20
    assert result["posting_count"] == 20
    assert len(result["property_groups"]) == 20



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
                listing("z-main", "100 Castro St", "realtyapi-zillow", 4000),
                listing("r-main", "100 Castro St", "realtyapi-realtor", 3900),
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
    assert groups[0]["display"]["rent"] == "$3,800–$4,000"
    assert {source["label"] for source in groups[0]["display"]["sources"]} == {
        "Apartments.com", "Zillow", "Realtor.com"
    }
    sources = {source["label"]: source for source in groups[0]["display"]["sources"]}
    assert sources["Apartments.com"]["rent"] == "$3,800"
    assert sources["Zillow"]["rent"] == "$4,000"
    assert sources["Realtor.com"]["rent"] == "$3,900"
    assert {item["listing"]["id"] for item in groups[1]["postings"]} == {
        "apt-unit2", "z-unit2"
    }
    assert groups[1]["source_count"] == 2
    assert groups[0]["display"]["address"] == "100 Castro Street"
    assert groups[0]["display"]["full_address"] == "100 Castro Street, Mountain View, CA 94041"
    assert groups[0]["display"]["beds"] == "2"
    assert groups[0]["display"]["baths"] == "2"
    sections = result["display_sections"]
    assert result["cross_listed_count"] == 2
    assert sections["cross_listed"][0].startswith("1. **100 Castro Street** — [Apartments.com]")
    assert "[Apartments.com](https://example.test/apt-main) — $3,800 · 2 bd · 2 ba" in sections["cross_listed"][0]
    assert "[Zillow](https://example.test/z-main) — $4,000 · 2 bd · 2 ba" in sections["cross_listed"][0]
    assert "[Realtor.com](https://example.test/r-main) — $3,900 · 2 bd · 2 ba" in sections["cross_listed"][0]
    assert sections["cross_listed"][1].startswith("2. **100 Castro St Apt 2** — [Apartments.com]")
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
    display = result["property_groups"][0]["display"]
    assert display["baths"] == "2+"
    assert display["sources"][0]["baths"] == "2+"
    assert "[Zillow](https://www.zillow.com/homedetails/123_zpid/) — $3,500 · 2 bd · 2+ ba" in (
        result["display_sections"]["other_matches"][0]
    )
