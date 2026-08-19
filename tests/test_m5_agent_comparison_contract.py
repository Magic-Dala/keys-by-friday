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


def test_session_and_restored_canonical_paths_share_same_comparison_results():
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

    assert {key: session[key] for key in ("schemaVersion", "listingIds", "results")} == restored


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
