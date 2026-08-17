from __future__ import annotations

from types import SimpleNamespace

from rental_agent import agent as agent_module
from rental_agent.agent import (
    compare_candidates,
    get_listing_details,
    get_route_details,
    search_listings,
)
from rental_agent.providers.mock import MockListingProvider


def _assert_activity(
    result: dict[str, object],
    *,
    operation: str,
    stage: str,
    status: str = "completed",
) -> dict[str, object]:
    activity = result["activity"]
    assert isinstance(activity, dict)
    assert activity["schema"] == "rental.agent_activity.v1"
    assert activity["operation"] == operation
    assert activity["stage"] == stage
    assert activity["status"] == status
    assert isinstance(activity["completed_stages"], list)
    assert isinstance(activity["facts"], dict)
    assert "message" not in activity
    assert "percent" not in activity
    return activity


def test_search_activity_reports_execution_facts_without_ui_copy(monkeypatch):
    provider = MockListingProvider()
    monkeypatch.setattr(agent_module, "get_provider", lambda: provider)
    context = SimpleNamespace(state={})

    result = search_listings(
        city="Mountain View",
        max_rent=4000,
        min_bedrooms=2,
        tool_context=context,
    )

    activity = _assert_activity(
        result,
        operation="search_listings",
        stage="listing_search",
    )
    assert activity["completed_stages"] == [
        "requirements",
        "listing_search",
        "hard_filter",
    ]
    assert activity["facts"] == {
        "provider_search_performed": True,
        "data_source": "mock",
        "search_complete": True,
        "failed_source_count": 0,
        "matched_count": result["matched_count"],
        "posting_count": result["posting_count"],
    }


def test_search_activity_distinguishes_session_reuse_from_provider_search(monkeypatch):
    class CountingProvider(MockListingProvider):
        def __init__(self):
            super().__init__()
            self.search_calls = 0

        def search(self, requirements):
            self.search_calls += 1
            return super().search(requirements)

    provider = CountingProvider()
    monkeypatch.setattr(agent_module, "get_provider", lambda: provider)
    context = SimpleNamespace(state={})

    search_listings(
        city="Mountain View",
        max_rent=4000,
        min_bedrooms=2,
        tool_context=context,
    )
    cached = search_listings(max_rent=3900, tool_context=context)

    activity = _assert_activity(
        cached,
        operation="search_listings",
        stage="listing_search",
    )
    assert provider.search_calls == 1
    assert activity["facts"]["provider_search_performed"] is False
    assert activity["facts"]["data_source"] == "session_cache"


def test_requires_input_activity_is_machine_readable_and_provider_free():
    result = search_listings(
        city="Mountain View",
        max_commute_minutes=30,
    )

    activity = _assert_activity(
        result,
        operation="search_listings",
        stage="requirements",
        status="requires_input",
    )
    assert activity["completed_stages"] == ["requirements"]
    assert activity["facts"] == {
        "provider_search_performed": False,
        "missing_requirements": ["commute_destination", "commute_travel_mode"],
    }


def test_detail_route_and_compare_expose_stable_activity_contract(monkeypatch):
    provider = MockListingProvider()
    monkeypatch.setattr(agent_module, "get_provider", lambda: provider)
    context = SimpleNamespace(state={})

    search = search_listings(
        city="Mountain View",
        max_rent=4000,
        min_bedrooms=2,
        soft_preferences="modern, quiet",
        tool_context=context,
    )
    listing_id = search["verification_candidates"][0]["listing_id"]

    detail = get_listing_details(listing_id, tool_context=context)
    detail_activity = _assert_activity(
        detail,
        operation="get_listing_details",
        stage="detail_verification",
    )
    assert detail_activity["facts"]["listing_id"] == listing_id
    assert detail_activity["facts"]["detail_verified"] == detail["verification"][
        "detail_verified"
    ]
    assert "hard_filter" in detail_activity["completed_stages"]

    route = get_route_details(listing_id, tool_context=context)
    route_activity = _assert_activity(
        route,
        operation="get_route_details",
        stage="commute_check",
    )
    assert route_activity["completed_stages"] == ["commute_check"]
    assert route_activity["facts"]["listing_id"] == listing_id
    assert route_activity["facts"]["route_status"] == route["status"]

    comparison = compare_candidates(listing_id, tool_context=context)
    compare_activity = _assert_activity(
        comparison,
        operation="compare_candidates",
        stage="candidate_comparison",
    )
    assert "candidate_comparison" in compare_activity["completed_stages"]
    assert "soft_preference_evidence" in compare_activity["completed_stages"]
    assert compare_activity["facts"]["requested_count"] == 1
    assert compare_activity["facts"]["bounded_requested_count"] == 1
    assert compare_activity["facts"]["compared_count"] == 1
    assert compare_activity["facts"]["verification_error_count"] == 0


def test_compare_activity_marks_partial_when_selected_items_cannot_be_compared(monkeypatch):
    provider = MockListingProvider()
    monkeypatch.setattr(agent_module, "get_provider", lambda: provider)
    context = SimpleNamespace(state={})
    search_listings(
        city="Mountain View",
        max_rent=4000,
        min_bedrooms=2,
        tool_context=context,
    )

    result = compare_candidates("#1,#999", verify_missing=False, tool_context=context)

    activity = _assert_activity(
        result,
        operation="compare_candidates",
        stage="candidate_comparison",
        status="partial",
    )
    assert activity["facts"]["requested_count"] == 2
    assert activity["facts"]["bounded_requested_count"] == 2
    assert activity["facts"]["compared_count"] == 1
    assert activity["facts"]["missing_count"] == 1


def test_partial_multi_source_search_is_reported_as_partial_activity(monkeypatch):
    class PartialProvider(MockListingProvider):
        def health(self):
            return {
                "ok": True,
                "provider": "realtyapi-multi",
                "search_complete": False,
                "failed_sources": ["zillow"],
            }

    provider = PartialProvider()
    monkeypatch.setattr(agent_module, "get_provider", lambda: provider)

    result = search_listings(city="Mountain View", max_rent=4000, min_bedrooms=2)

    activity = _assert_activity(
        result,
        operation="search_listings",
        stage="listing_search",
        status="partial",
    )
    assert activity["facts"]["search_complete"] is False
    assert activity["facts"]["failed_source_count"] == 1


def test_compare_activity_preserves_original_request_count_when_bounded(monkeypatch):
    provider = MockListingProvider()
    monkeypatch.setattr(agent_module, "get_provider", lambda: provider)
    context = SimpleNamespace(state={})
    search = search_listings(
        city="Mountain View",
        max_rent=5000,
        tool_context=context,
    )
    refs = [item["listing"]["id"] for item in search["top_5"]]
    refs.extend(["extra-1", "extra-2"])

    result = compare_candidates(",".join(refs), verify_missing=False, tool_context=context)

    activity = _assert_activity(
        result,
        operation="compare_candidates",
        stage="candidate_comparison",
        status="partial",
    )
    assert result["too_many_requested"] is True
    assert activity["facts"]["requested_count"] == len(refs)
    assert activity["facts"]["bounded_requested_count"] == 4
    assert activity["facts"]["compared_count"] == 4
