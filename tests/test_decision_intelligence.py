from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace

from rental_agent import agent as agent_module
from rental_agent.agent import compare_candidates, search_listings
from rental_agent.commute import CommuteResult
from rental_agent.models import Listing


def _listing(
    identifier: str,
    *,
    rent: float = 3500,
    pets_allowed: bool | None = True,
    parking_available: bool | None = True,
    description: str | None = None,
    year_built: int | None = None,
    detail_verified: bool = False,
    query_backed_fields: tuple[str, ...] = (),
) -> Listing:
    return Listing(
        id=identifier,
        address=f"{identifier} Test St, Mountain View, CA 94041",
        city="Mountain View",
        state="CA",
        zip_code="94041",
        rent=rent,
        bedrooms=2,
        bathrooms=2,
        square_footage=1000,
        status="Active",
        pets_allowed=pets_allowed,
        parking_available=parking_available,
        source="test-source",
        source_url=f"https://example.test/{identifier}",
        description=description,
        year_built=year_built,
        detail_verified=detail_verified,
        query_backed_fields=query_backed_fields,
    )


class DecisionProvider:
    def __init__(self, search_rows: list[Listing], details: dict[str, Listing] | None = None):
        self.search_rows = search_rows
        self.details = details or {row.id: replace(row, detail_verified=True) for row in search_rows}
        self.search_calls = 0
        self.detail_calls: list[str] = []

    def search(self, requirements):
        self.search_calls += 1
        return list(self.search_rows)

    def get_listing(self, listing_id):
        self.detail_calls.append(listing_id)
        return self.details[listing_id]

    def health(self):
        return {"ok": True, "provider": "decision-provider"}


def _searched_context(monkeypatch, provider: DecisionProvider, *, soft_preferences: str = "modern, quiet"):
    monkeypatch.setattr(agent_module, "get_provider", lambda: provider)
    context = SimpleNamespace(state={})
    search_listings(
        city="Mountain View",
        max_rent=4000,
        min_bedrooms=2,
        min_bathrooms=2,
        pets_required=True,
        parking_required=True,
        soft_preferences=soft_preferences,
        tool_context=context,
    )
    assert provider.search_calls == 1
    return context


def test_compare_reads_only_session_candidates_and_never_broad_searches(monkeypatch):
    provider = DecisionProvider([_listing("one"), _listing("two")])
    context = _searched_context(monkeypatch, provider)

    result = compare_candidates("one,two", verify_missing=False, tool_context=context)

    assert provider.search_calls == 1
    assert provider.detail_calls == []
    assert [item["listing_id"] for item in result["candidates"]] == ["one", "two"]


def test_compare_missing_and_duplicate_ids_are_explicit_and_deterministic(monkeypatch):
    provider = DecisionProvider([_listing("one"), _listing("two")])
    context = _searched_context(monkeypatch, provider)

    result = compare_candidates("missing,one,one", verify_missing=False, tool_context=context)

    assert result["requested"] == ["missing", "one"]
    assert result["missing_listing_ids"] == ["missing"]
    assert [item["listing_id"] for item in result["candidates"]] == ["one"]
    assert provider.detail_calls == []


def test_compare_enforces_small_selection_limit_without_verifying_rest(monkeypatch):
    rows = [_listing(f"item-{index}") for index in range(1, 7)]
    provider = DecisionProvider(rows)
    context = _searched_context(monkeypatch, provider)

    result = compare_candidates(
        ",".join(row.id for row in rows), verify_missing=True, tool_context=context
    )

    assert result["selection_limit"] == 4
    assert result["too_many_requested"] is True
    assert result["requested"] == [f"item-{index}" for index in range(1, 5)]
    assert provider.detail_calls == [f"item-{index}" for index in range(1, 5)]


def test_compare_reuses_verified_details_and_only_verifies_selected_missing(monkeypatch):
    provider = DecisionProvider([_listing("one"), _listing("two"), _listing("three")])
    context = _searched_context(monkeypatch, provider)
    cached = agent_module.get_listing_details("one", tool_context=context)
    assert cached["verification"]["detail_verified"] is True
    provider.detail_calls.clear()

    result = compare_candidates("one,three", verify_missing=True, tool_context=context)

    assert provider.detail_calls == ["three"]
    by_id = {item["listing_id"]: item for item in result["candidates"]}
    assert by_id["one"]["verification_attempted"] is False
    assert by_id["one"]["detail_verified"] is True
    assert by_id["three"]["verification_attempted"] is True
    assert by_id["three"]["detail_verified"] is True


def test_detail_verification_can_turn_candidate_into_hard_constraint_failure(monkeypatch):
    rows = [_listing("one", rent=3500)]
    details = {"one": replace(rows[0], rent=4500, detail_verified=True)}
    provider = DecisionProvider(rows, details)
    context = _searched_context(monkeypatch, provider)

    result = compare_candidates("one", verify_missing=True, tool_context=context)
    candidate = result["candidates"][0]

    assert candidate["hard_constraint_status"] == "fail"
    assert candidate["satisfies_current_requirements"] is False
    assert candidate["decision_ready"] is False


def test_soft_preference_evidence_is_conservative(monkeypatch):
    row = _listing(
        "one",
        description="Renovated kitchen with stainless appliances near Caltrain.",
        year_built=2018,
    )
    provider = DecisionProvider([row])
    context = _searched_context(monkeypatch, provider, soft_preferences="modern, quiet, newer, near transit, rooftop garden")

    result = compare_candidates("one", verify_missing=False, tool_context=context)
    evidence = {
        item["preference"]: item for item in result["candidates"][0]["soft_preference_evidence"]
    }

    assert evidence["modern"]["status"] == "supported"
    assert any(item["match"] == "renovated" for item in evidence["modern"]["evidence"])
    assert evidence["quiet"] == {"preference": "quiet", "status": "unknown", "evidence": []}
    assert evidence["newer"]["status"] == "evidence_only"
    assert evidence["newer"]["evidence"] == [{"field": "year_built", "value": 2018}]
    assert evidence["near transit"]["status"] == "supported"
    assert any(item["match"] == "caltrain" for item in evidence["near transit"]["evidence"])
    assert evidence["rooftop garden"] == {
        "preference": "rooftop garden",
        "status": "unknown",
        "evidence": [],
    }


def test_query_backed_pet_parking_and_minimum_bath_evidence_are_not_exact_facts(monkeypatch):
    row = replace(
        _listing("one", pets_allowed=True, parking_available=True),
        bathrooms=None,
        bathrooms_min_evidence=2,
        query_backed_fields=(
            "bathrooms_min_evidence",
            "pets_allowed",
            "parking_available",
        ),
    )
    provider = DecisionProvider([row])
    context = _searched_context(monkeypatch, provider)

    result = compare_candidates("one", verify_missing=False, tool_context=context)
    candidate = result["candidates"][0]

    assert candidate["bathrooms"] == {"exact": None, "minimum_evidence": 2}
    assert candidate["pet_policy"]["allowed"] is None
    assert candidate["pet_policy"]["query_backed_evidence"] is True
    assert candidate["pet_policy"]["confirmed"] is False
    assert candidate["parking_policy"]["available"] is None
    assert candidate["parking_policy"]["query_backed_evidence"] is True
    assert candidate["parking_policy"]["confirmed"] is False
    assert "policies.petsAllowed" in candidate["decision_unknowns"]
    assert "policies.parkingAvailable" in candidate["decision_unknowns"]
    assert "property.bathroomsMinEvidence" in candidate["decision_unknowns"]
    assert candidate["hard_constraint_status"] == "evidence_only"
    assert candidate["satisfies_current_requirements"] is None
    assert candidate["decision_ready"] is False


def test_same_state_and_input_yields_same_structured_comparison(monkeypatch):
    provider = DecisionProvider([_listing("one"), _listing("two")])
    context = _searched_context(monkeypatch, provider)
    state_before = dict(context.state)

    first = compare_candidates("#1,#2", verify_missing=False, tool_context=context)
    second = compare_candidates("#1,#2", verify_missing=False, tool_context=context)

    assert first == second
    assert context.state[agent_module._REQUIREMENTS_STATE_KEY] == state_before[agent_module._REQUIREMENTS_STATE_KEY]
    assert context.state[agent_module._CANDIDATES_STATE_KEY] == state_before[agent_module._CANDIDATES_STATE_KEY]
    assert provider.search_calls == 1


def test_compare_preserves_commute_and_missing_facts(monkeypatch):
    provider = DecisionProvider([_listing("one", pets_allowed=None, parking_available=None)])
    monkeypatch.setattr(agent_module, "get_provider", lambda: provider)
    context = SimpleNamespace(state={})
    candidate = provider.search_rows[0]
    context.state[agent_module._REQUIREMENTS_STATE_KEY] = agent_module._requirements_to_dict(
        agent_module.SearchRequirements(city="Mountain View", soft_preferences=("quiet",))
    )
    context.state[agent_module._CANDIDATES_STATE_KEY] = [
        {
            "listing": candidate.to_dict(),
            "backend_listing": candidate.to_backend_dict(),
            "score": 50,
            "reasons": [],
            "tradeoffs": [],
            "current_search_rank": 1,
            "commute": CommuteResult(
                destination="Googleplex",
                mode="DRIVE",
                duration_minutes=22,
                distance_meters=9000,
                status="available",
            ).to_dict(),
        }
    ]
    context.state[agent_module._VERIFIED_STATE_KEY] = {}

    result = compare_candidates("one", verify_missing=False, tool_context=context)
    comparison = result["candidates"][0]

    assert comparison["commute"]["duration_minutes"] == 22
    assert comparison["pet_policy"]["allowed"] is None
    assert comparison["parking_policy"]["available"] is None
    assert "policies.petsAllowed" in comparison["comparison_unknowns"]
    assert "policies.parkingAvailable" in comparison["comparison_unknowns"]
