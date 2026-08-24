from __future__ import annotations

import json
from dataclasses import replace
from types import SimpleNamespace

from rental_agent import agent as agent_module
from rental_agent.agent import (
    compare_candidates,
    compare_canonical_listings,
    search_listings,
)
from rental_agent.models import Listing, SearchRequirements


def _listing(
    identifier: str,
    *,
    rent: float = 3500,
    detail_verified: bool = True,
    pets_allowed: bool | None = True,
    parking_available: bool | None = True,
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
        detail_verified=detail_verified,
        query_backed_fields=query_backed_fields,
    )


class _Provider:
    def __init__(self, rows: list[Listing]):
        self.rows = rows
        self.search_calls = 0
        self.detail_calls: list[str] = []

    def search(self, requirements):
        self.search_calls += 1
        return list(self.rows)

    def get_listing(self, listing_id):
        self.detail_calls.append(listing_id)
        return replace(next(row for row in self.rows if row.id == listing_id), detail_verified=True)

    def health(self):
        return {"ok": True, "provider": "m5-test-provider"}


def _requirements() -> SearchRequirements:
    return SearchRequirements(
        city="Mountain View",
        max_rent=4000,
        min_bedrooms=2,
        min_bathrooms=2,
        pets_required=True,
        parking_required=True,
        soft_preferences=("quiet",),
    )


def test_session_search_compare_keeps_existing_path_and_adds_canonical_envelope(monkeypatch):
    provider = _Provider([_listing("one"), _listing("two"), _listing("three")])
    monkeypatch.setattr(agent_module, "get_provider", lambda: provider)
    context = SimpleNamespace(state={})

    search_listings(
        city="Mountain View",
        max_rent=4000,
        min_bedrooms=2,
        min_bathrooms=2,
        pets_required=True,
        parking_required=True,
        tool_context=context,
    )
    result = compare_candidates("#1,#3", verify_missing=False, tool_context=context)

    assert provider.search_calls == 1
    assert provider.detail_calls == []
    assert result["schemaVersion"] == "kbf.canonical-comparison.v1"
    assert result["listingIds"] == ["one", "two"]
    assert [item["listing_id"] for item in result["candidates"]] == ["one", "two"]
    assert [item["listingId"] for item in result["results"]] == ["one", "two"]


def test_session_and_restored_canonical_paths_share_same_comparison_semantics():
    rows = [_listing("one"), _listing("three")]
    req = _requirements()
    context = SimpleNamespace(
        state={
            agent_module._REQUIREMENTS_STATE_KEY: agent_module._requirements_to_dict(req),
            agent_module._CANDIDATES_STATE_KEY: [
                {"listing": row.to_dict(), "current_search_rank": index}
                for index, row in enumerate(rows, start=1)
            ],
            agent_module._VERIFIED_STATE_KEY: {},
        }
    )

    session = compare_candidates("#1,#2", verify_missing=False, tool_context=context)
    restored_payloads = [json.loads(json.dumps(row.to_backend_dict())) for row in rows]
    restored = compare_canonical_listings(
        restored_payloads,
        json.loads(json.dumps(agent_module._requirements_to_dict(req))),
    )

    assert session["schemaVersion"] == restored["schemaVersion"]
    assert session["listingIds"] == restored["listingIds"]
    for session_result, restored_result in zip(session["results"], restored["results"]):
        assert {
            key: value
            for key, value in session_result.items()
            if key not in {"score", "rank"}
        } == {
            key: value
            for key, value in restored_result.items()
            if key not in {"score", "rank"}
        }
    assert [item["rank"] for item in session["results"]] == [1, 2]
    assert [item["rank"] for item in restored["results"]] == [None, None]


def test_session_comparison_preserves_search_rank_and_score_when_selection_order_differs():
    strong = _listing("strong")
    weak = _listing("weak")
    req = _requirements()
    context = SimpleNamespace(
        state={
            agent_module._REQUIREMENTS_STATE_KEY: agent_module._requirements_to_dict(req),
            agent_module._CANDIDATES_STATE_KEY: [
                {
                    "listing": strong.to_dict(),
                    "score": 92.5,
                    "current_search_rank": 1,
                },
                {
                    "listing": weak.to_dict(),
                    "score": 71.0,
                    "current_search_rank": 2,
                },
            ],
            agent_module._VERIFIED_STATE_KEY: {},
        }
    )

    result = compare_candidates("weak,strong", verify_missing=False, tool_context=context)

    assert result["listingIds"] == ["weak", "strong"]
    assert [item["rank"] for item in result["results"]] == [2, 1]
    assert [item["score"] for item in result["results"]] == [71.0, 92.5]


def test_firestore_json_round_trip_preserves_evidence_only_and_verification_semantics():
    row = replace(
        _listing("evidence", detail_verified=False),
        bathrooms=None,
        bathrooms_min_evidence=2,
        query_backed_fields=(
            "bathrooms_min_evidence",
            "pets_allowed",
            "parking_available",
        ),
    )
    canonical = json.loads(json.dumps(row.to_backend_dict()))
    restored_listing = agent_module._listing_from_canonical_v1(canonical)
    comparison = compare_canonical_listings([canonical], _requirements())
    result = comparison["results"][0]

    assert restored_listing.to_backend_dict()["evidence"]["detailVerified"] is False
    assert set(restored_listing.to_backend_dict()["evidence"]["queryBackedFields"]) == {
        "property.bathroomsMinEvidence",
        "policies.petsAllowed",
        "policies.parkingAvailable",
    }
    assert result["hardConstraintStatus"] == "evidence_only"
    assert result["satisfiesCurrentRequirements"] is None
    assert result["decisionReady"] is False
    assert set(result["comparisonUnknowns"]) >= {
        "property.bathroomsMinEvidence",
        "policies.petsAllowed",
        "policies.parkingAvailable",
    }


def test_restored_authoritative_hard_failure_cannot_be_recommended_as_match():
    canonical = json.loads(json.dumps(_listing("over-budget", rent=4500).to_backend_dict()))

    result = compare_canonical_listings([canonical], _requirements())["results"][0]

    assert result["hardConstraintStatus"] == "fail"
    assert result["satisfiesCurrentRequirements"] is False
    assert result["decisionReady"] is False


def test_no_current_requirements_degrades_hard_judgment_to_unknown_without_guessing():
    canonical = json.loads(json.dumps(_listing("one").to_backend_dict()))

    result = compare_canonical_listings([canonical], None)["results"][0]

    assert result["hardConstraintStatus"] == "unknown"
    assert result["satisfiesCurrentRequirements"] is None
    assert result["softPreferenceEvidence"] == []
    assert result["decisionReady"] is False


def test_canonical_comparison_order_and_results_are_deterministic():
    canonical = [
        json.loads(json.dumps(_listing("two").to_backend_dict())),
        json.loads(json.dumps(_listing("one").to_backend_dict())),
    ]
    req = _requirements()

    first = compare_canonical_listings(canonical, req)
    second = compare_canonical_listings(canonical, req)

    assert first == second
    assert first["schemaVersion"] == "kbf.canonical-comparison.v1"
    assert first["listingIds"] == ["two", "one"]
    assert [item["listingId"] for item in first["results"]] == ["two", "one"]


def test_session_legacy_and_canonical_status_do_not_diverge_on_ambiguous_rent_range():
    row = replace(
        _listing("range"),
        rent=3800,
        rent_is_exact=False,
        rent_min=3200,
        rent_max=4500,
    )
    req = _requirements()
    context = SimpleNamespace(
        state={
            agent_module._REQUIREMENTS_STATE_KEY: agent_module._requirements_to_dict(req),
            agent_module._CANDIDATES_STATE_KEY: [
                {"listing": row.to_dict(), "current_search_rank": 1}
            ],
            agent_module._VERIFIED_STATE_KEY: {},
        }
    )

    result = compare_candidates("#1", verify_missing=False, tool_context=context)
    legacy = result["candidates"][0]
    canonical = result["results"][0]

    assert legacy["hard_constraint_status"] == "unknown"
    assert legacy["satisfies_current_requirements"] is None
    assert canonical["hardConstraintStatus"] == "unknown"
    assert canonical["satisfiesCurrentRequirements"] is None
    assert legacy["decision_ready"] is False


def test_backend_commute_json_round_trip_preserves_available_duration():
    canonical = json.loads(json.dumps(_listing("commute").to_backend_dict()))
    req = replace(
        _requirements(),
        commute_destination="Google Mountain View",
        max_commute_minutes=30,
        commute_travel_mode="DRIVE",
    )
    backend_commute = json.loads(
        json.dumps(
            {
                "destination": "Google Mountain View",
                "destinationPlaceId": "place-google-mv",
                "mode": "DRIVE",
                "durationMinutes": 18,
                "distanceMeters": 12400,
                "status": "available",
                "routingPreference": "TRAFFIC_AWARE",
            }
        )
    )

    result = compare_canonical_listings(
        [canonical], req, commutes={"commute": backend_commute}
    )["results"][0]

    assert result["hardConstraintStatus"] == "pass"
    assert result["satisfiesCurrentRequirements"] is True


def test_restored_commute_must_match_current_destination_and_mode():
    canonical = json.loads(json.dumps(_listing("commute").to_backend_dict()))
    req = replace(
        _requirements(),
        commute_destination="Google Mountain View",
        max_commute_minutes=30,
        commute_travel_mode="DRIVE",
    )
    base_commute = {
        "destination": "Google Mountain View",
        "mode": "DRIVE",
        "durationMinutes": 18,
        "status": "available",
    }

    wrong_destination = compare_canonical_listings(
        [canonical],
        req,
        commutes={"commute": {**base_commute, "destination": "Downtown San Jose"}},
    )["results"][0]
    wrong_mode = compare_canonical_listings(
        [canonical],
        req,
        commutes={"commute": {**base_commute, "mode": "TRANSIT"}},
    )["results"][0]

    assert wrong_destination["hardConstraintStatus"] == "unknown"
    assert wrong_destination["satisfiesCurrentRequirements"] is None
    assert wrong_mode["hardConstraintStatus"] == "unknown"
    assert wrong_mode["satisfiesCurrentRequirements"] is None


def test_max_bathrooms_uses_authoritative_lower_bound_as_hard_failure():
    row = replace(
        _listing("bath-lower-bound"),
        bathrooms=None,
        bathrooms_min_evidence=3,
    )
    canonical = json.loads(json.dumps(row.to_backend_dict()))
    req = replace(_requirements(), max_bathrooms=2)

    result = compare_canonical_listings([canonical], req)["results"][0]

    assert result["hardConstraintStatus"] == "fail"
    assert result["satisfiesCurrentRequirements"] is False


def test_max_bathrooms_query_backed_lower_bound_remains_evidence_only():
    row = replace(
        _listing("bath-query-backed"),
        bathrooms=None,
        bathrooms_min_evidence=3,
        query_backed_fields=("bathrooms_min_evidence",),
    )
    canonical = json.loads(json.dumps(row.to_backend_dict()))
    req = replace(_requirements(), max_bathrooms=2)

    result = compare_canonical_listings([canonical], req)["results"][0]

    assert result["hardConstraintStatus"] == "evidence_only"
    assert result["satisfiesCurrentRequirements"] is None
