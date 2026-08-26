import asyncio

from fastapi.testclient import TestClient
import pytest

from backend.app.auth import AuthenticatedUser, get_current_user
from backend.app.config import Settings
from backend.app.main import create_app
from backend.app.models.search import SearchResponse
from backend.app.services.agent_service import (
    AgentService,
    AgentServiceError,
    _comparison_from_tool_payload,
    _commute_evaluation_from_tool_payload,
    _canonical_comparison_from_tool_payload,
    _missing_requirements_from_tool_payload,
    _normalize_comparison_listings,
    _normalize_response_listings,
    _normalize_tool_listings,
    _requirements_from_tool_payload,
    _route_from_tool_payload,
    _search_performed_from_tool_payload,
    get_agent_service,
)


def contract_test_app():
    """Create an API app whose behavior never depends on the developer's .env."""

    application = create_app(
        Settings(
            agent_mode="stub",
            auth_mode="firebase",
            app_environment="test",
            firebase_project_id="test-project",
        )
    )
    service = AgentService(mode="stub", timeout_seconds=120)
    application.dependency_overrides[get_current_user] = lambda: AuthenticatedUser(
        uid="contract-test-user", sign_in_provider="test"
    )
    application.dependency_overrides[get_agent_service] = lambda: service
    return application


def test_health() -> None:
    assert TestClient(contract_test_app()).get("/health").json() == {"status": "ok"}


def test_chat_contract_with_stub() -> None:
    response = TestClient(contract_test_app()).post(
        "/api/chat", json={"message": "2B2B in Mountain View"}
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["conversationId"]
    assert payload["mode"] == "stub"
    assert payload["listings"] == []


def test_chat_rejects_blank_message() -> None:
    response = TestClient(contract_test_app()).post(
        "/api/chat", json={"message": "   "}
    )
    assert response.status_code == 422


def test_chat_normalizes_request_whitespace() -> None:
    response = TestClient(contract_test_app()).post(
        "/api/chat", json={"message": "  2B2B in Mountain View  "}
    )
    assert response.status_code == 200
    assert response.json()["message"].endswith("2B2B in Mountain View")


def test_normalize_adk_tool_results_for_web_contract() -> None:
    search_payload = {
        "top_5": [
            {
                "listing": {
                    "id": "listing-1",
                    "address": "877 Heatherstone Way",
                    "rent": 3180,
                    "bedrooms": 2,
                    "bathrooms": 2,
                    "latitude": 37.4,
                    "longitude": -122.1,
                    "source_url": "https://example.com/listing-1",
                },
                "score": 9.5,
                "reasons": ["within budget", "matches 2B2B"],
            }
        ]
    }
    detail_payloads = [
        {
            "listing": {
                "id": "listing-1",
                "property_name": "Heatherstone Apartments",
                "address": "877 Heatherstone Way",
                "rent": 3180,
                "bedrooms": 2,
                "bathrooms": 2,
                "latitude": 37.401,
                "longitude": -122.101,
                "source_url": "https://example.com/listing-1",
                "detail_verified": True,
            },
            "verification": {"passes_current_hard_filters": True},
        }
    ]

    listings = _normalize_tool_listings(search_payload, detail_payloads)

    assert len(listings) == 1
    listing = listings[0]
    assert listing.id == "listing-1"
    assert listing.title == "Heatherstone Apartments"
    assert listing.price == 3180
    assert listing.url == "https://example.com/listing-1"
    assert listing.latitude == 37.401
    assert listing.longitude == -122.101
    assert listing.score == 9.5
    assert listing.reason == "within budget; matches 2B2B"


def test_canonical_listing_is_returned_additively_with_unknowns_intact() -> None:
    canonical = {
        "schemaVersion": "kbf.canonical-listing.v1",
        "identity": {
            "id": "listing-1",
            "sourceListingId": "source-1",
            "propertyName": "Heatherstone",
        },
        "location": {
            "address": "877 Heatherstone Way",
            "city": "Mountain View",
            "state": "CA",
            "zipCode": None,
            "countryCode": "US",
            "latitude": 37.4,
            "longitude": -122.1,
        },
        "pricing": {"rent": 3180, "rentMin": None, "rentMax": None},
        "property": {
            "bedrooms": 2,
            "bedroomsMin": None,
            "bedroomsMax": None,
            "bathrooms": None,
            "bathroomsMinEvidence": 2,
            "propertyType": "Apartment",
            "futureAdditiveField": "kept",
        },
        "availability": {},
        "policies": {"petsAllowed": None, "parkingAvailable": True},
        "features": {},
        "media": {},
        "contact": {},
        "source": {"url": "https://example.com/listing-1"},
        "evidence": {"detailVerified": False},
        "completeness": {
            "unknownFields": ["property.bathrooms", "policies.petsAllowed"],
            "decisionReady": False,
        },
    }
    listings = _normalize_tool_listings(
        {
            "top_5": [
                {
                    "listing": {"id": "listing-1"},
                    "backend_listing": canonical,
                }
            ]
        },
        [],
    )

    payload = listings[0].model_dump(mode="json")

    assert payload["id"] == "listing-1"
    assert payload["canonicalListing"]["property"]["bathrooms"] is None
    assert payload["canonicalListing"]["policies"]["petsAllowed"] is None
    assert (
        payload["canonicalListing"]["property"]["futureAdditiveField"]
        == "kept"
    )


def test_comparison_normalization_uses_structured_tool_data_only() -> None:
    tool_payload = {
        "requested": ["one", "two"],
        "candidates": [
            {
                "listing_id": "one",
                "hard_constraint_status": "pass",
                "satisfies_current_requirements": True,
                "soft_preference_evidence": [
                    {"preference": "quiet", "status": "supported"}
                ],
                "tradeoffs": ["higher rent"],
                "comparison_unknowns": ["policies.petPolicy"],
                "decision_unknowns": ["policies.petPolicy"],
                "decision_ready": False,
                "score": 91.5,
                "current_search_rank": 1,
            },
            {
                "listing_id": "two",
                "hard_constraint_status": "not_evaluated",
                "satisfies_current_requirements": None,
                "comparison_unknowns": [],
                "decision_unknowns": [],
                "decision_ready": True,
                "current_search_rank": 2,
            },
        ],
    }

    first = _canonical_comparison_from_tool_payload(tool_payload)
    second = _canonical_comparison_from_tool_payload(tool_payload)

    assert first is not None
    assert first == second
    assert first.schemaVersion == "kbf.canonical-comparison.v1"
    assert first.listingIds == ["one", "two"]
    assert first.results[0].tradeoffs == ["higher rent"]
    assert first.results[1].hardConstraintStatus == "unknown"


def test_comparison_returns_selected_verified_canonical_listings() -> None:
    canonical = {
        "schemaVersion": "kbf.canonical-listing.v1",
        "identity": {
            "id": "one",
            "sourceListingId": "source-one",
            "propertyName": "Heatherstone",
        },
        "location": {
            "address": "877 Heatherstone Way",
            "city": "Mountain View",
            "state": "CA",
            "zipCode": "94040",
            "countryCode": "US",
            "latitude": 37.4,
            "longitude": -122.1,
        },
        "pricing": {"rent": 3180, "rentMin": None, "rentMax": None},
        "property": {
            "bedrooms": 2,
            "bedroomsMin": None,
            "bedroomsMax": None,
            "bathrooms": None,
            "bathroomsMinEvidence": None,
            "propertyType": "Apartment",
        },
        "availability": {},
        "policies": {
            "petsAllowed": True,
            "petPolicy": "Cats and dogs allowed",
            "parkingAvailable": True,
        },
        "features": {},
        "media": {},
        "contact": {},
        "source": {"url": "https://example.com/one"},
        "evidence": {"detailVerified": True},
        "completeness": {
            "unknownFields": ["property.bathrooms"],
            "decisionReady": False,
        },
    }

    listings = _normalize_comparison_listings(
        {
            "candidates": [
                {
                    "listing_id": "one",
                    "current_search_rank": 1,
                    "canonical_listing": canonical,
                }
            ]
        }
    )

    assert len(listings) == 1
    assert listings[0].id == "one"
    assert listings[0].rank == 1
    assert listings[0].bathrooms is None
    assert listings[0].canonicalListing is not None
    assert listings[0].canonicalListing.policies["petsAllowed"] is True


def test_normalize_agent_requirement_state_for_frontend() -> None:
    payload = {
        "effective_requirements": {
            "city": "Mountain View",
            "state": "CA",
            "max_rent": 4000,
            "min_bedrooms": 2,
            "pets_required": True,
            "parking_required": True,
            "commute_destination": None,
            "max_commute_minutes": 30,
            "commute_travel_mode": None,
            "soft_preferences": ["quiet", "modern"],
        },
        "missing_requirements": ["commute_destination", "commute_travel_mode"],
    }

    requirements = _requirements_from_tool_payload(payload)

    assert requirements is not None
    assert requirements.city == "Mountain View"
    assert requirements.state == "CA"
    assert requirements.maxRent == 4000
    assert requirements.minBedrooms == 2
    assert requirements.petsRequired is True
    assert requirements.parkingRequired is True
    assert requirements.maxCommuteMinutes == 30
    assert requirements.softPreferences == ["quiet", "modern"]
    assert _missing_requirements_from_tool_payload(payload) == [
        "commute_destination",
        "commute_travel_mode",
    ]


def test_search_performed_requires_an_actual_provider_search() -> None:
    assert _search_performed_from_tool_payload(None) is False
    assert _search_performed_from_tool_payload({"status": "requires_input"}) is False
    assert (
        _search_performed_from_tool_payload(
            {"provider_search_performed": False, "provider": "not_called"}
        )
        is False
    )
    assert (
        _search_performed_from_tool_payload(
            {"provider_search_performed": True, "provider": "mock"}
        )
        is True
    )


def test_normalize_commute_and_selected_route_contract() -> None:
    search_payload = {
        "top_5": [
            {
                "listing": {
                    "id": "listing-1",
                    "address": "877 Heatherstone Way",
                    "latitude": 37.4,
                    "longitude": -122.1,
                },
                "commute": {
                    "destination": "Google Mountain View",
                    "destination_place_id": None,
                    "mode": "DRIVE",
                    "duration_minutes": 18,
                    "distance_meters": 12400,
                    "status": "available",
                    "routing_preference": "TRAFFIC_AWARE",
                },
            }
        ]
    }
    listing = _normalize_tool_listings(search_payload, [])[0]
    assert listing.commute is not None
    assert listing.commute.durationMinutes == 18
    assert listing.commute.distanceMeters == 12400
    assert listing.commute.routingPreference == "TRAFFIC_AWARE"

    evaluation = _commute_evaluation_from_tool_payload(
        {
            "status": "partial",
            "evaluated_count": 3,
            "available_count": 2,
            "unavailable_count": 1,
            "unknown_count": 0,
            "within_limit_count": 1,
            "over_limit_count": 1,
        }
    )
    assert evaluation is not None
    assert evaluation.status == "partial"
    assert evaluation.evaluatedCount == 3
    assert evaluation.withinLimitCount == 1
    assert evaluation.overLimitCount == 1
    unavailable = _commute_evaluation_from_tool_payload(
        {
            "status": "unavailable",
            "evaluated_count": 2,
            "available_count": 0,
            "unavailable_count": 2,
            "unknown_count": 0,
            "within_limit_count": 0,
            "over_limit_count": 0,
        }
    )
    assert unavailable is not None
    assert unavailable.status == "unavailable"
    assert unavailable.evaluatedCount == 2

    route = _route_from_tool_payload(
        {
            "listing_id": "listing-1",
            "destination": "Google Mountain View",
            "destination_place_id": None,
            "mode": "DRIVE",
            "duration_minutes": 18,
            "distance_meters": 12400,
            "encoded_polyline": "abc123",
            "status": "available",
        }
    )
    assert route is not None
    assert route.listingId == "listing-1"
    assert route.encodedPolyline == "abc123"


def test_normalize_canonical_comparison_contract() -> None:
    comparison = _comparison_from_tool_payload(
        {
            "schemaVersion": "kbf.canonical-comparison.v1",
            "listingIds": ["listing-1", "listing-2"],
            "results": [
                {
                    "listingId": "listing-1",
                    "hardConstraintStatus": "fail",
                    "satisfiesCurrentRequirements": False,
                    "softPreferenceEvidence": [],
                    "tradeoffs": ["parking unavailable"],
                    "comparisonUnknowns": [],
                    "decisionUnknowns": [],
                    "decisionReady": True,
                    "score": None,
                    "rank": 1,
                },
                {
                    "listingId": "listing-2",
                    "hardConstraintStatus": "pass",
                    "satisfiesCurrentRequirements": True,
                    "softPreferenceEvidence": [],
                    "tradeoffs": [],
                    "comparisonUnknowns": ["policies.petsAllowed"],
                    "decisionUnknowns": ["policies.petsAllowed"],
                    "decisionReady": False,
                    "score": None,
                    "rank": 2,
                },
            ],
            "candidates": [{"internal": "ignored by API contract"}],
        }
    )

    assert comparison is not None
    assert comparison.schemaVersion == "kbf.canonical-comparison.v1"
    assert comparison.listingIds == ["listing-1", "listing-2"]
    assert comparison.results[0].hardConstraintStatus == "fail"
    assert comparison.results[1].comparisonUnknowns == ["policies.petsAllowed"]
    assert _comparison_from_tool_payload({"schemaVersion": "wrong"}) is None


def test_normalize_preserves_grouped_source_postings_for_web_contract() -> None:
    search_payload = {
        "property_groups": [
            {
                "rank": 1,
                "representative": {
                    "listing": {
                        "id": "apartments-1",
                        "address": "100 Castro St",
                        "rent": 3800,
                        "bedrooms": 2,
                        "bathrooms": 2,
                        "source": "realtyapi-apartments",
                        "source_url": "https://apartments.example/1",
                    },
                    "score": 9.4,
                    "reasons": ["within budget"],
                },
                "postings": [
                    {
                        "source_label": "Apartments.com",
                        "listing": {
                            "id": "apartments-1",
                            "source": "realtyapi-apartments",
                            "source_url": "https://apartments.example/1",
                            "rent": 3800,
                            "bedrooms": 2,
                            "bathrooms": 2,
                        },
                    },
                    {
                        "source_label": "Zillow",
                        "listing": {
                            "id": "zillow:2",
                            "source": "realtyapi-zillow",
                            "source_url": "https://zillow.example/2",
                            "rent": 4000,
                            "bedrooms": 3,
                            "bathrooms": 2.5,
                        },
                    },
                ],
            }
        ],
        # The grouped path must win over the legacy representative-only alias.
        "top_5": [],
    }

    listings = _normalize_tool_listings(search_payload, [])

    assert len(listings) == 1
    listing = listings[0]
    assert listing.id == "apartments-1"
    assert listing.rank == 1
    assert [(posting.label, posting.price, posting.bedrooms, posting.bathrooms) for posting in listing.sourcePostings] == [
        ("Apartments.com", 3800, 2, 2),
        ("Zillow", 4000, 3, 2.5),
    ]
    assert [posting.url for posting in listing.sourcePostings] == [
        "https://apartments.example/1",
        "https://zillow.example/2",
    ]


def test_normalize_excludes_detail_verified_hard_filter_failure() -> None:
    search_payload = {
        "top_5": [
            {"listing": {"id": "rejected", "address": "A", "rent": 3000}},
            {"listing": {"id": "kept", "address": "B", "rent": 3200}},
        ]
    }
    detail_payloads = [
        {
            "listing": {"id": "rejected", "address": "A", "rent": 3000},
            "verification": {"passes_current_hard_filters": False},
        }
    ]

    listings = _normalize_tool_listings(search_payload, detail_payloads)
    assert [listing.id for listing in listings] == ["kept"]


def test_detail_only_turn_returns_the_detail_listing() -> None:
    listings = _normalize_response_listings(
        search_payload=None,
        detail_payloads=[
            {
                "listing": {
                    "id": "listing-1",
                    "property_name": "Heatherstone Apartments",
                    "address": "877 Heatherstone Way",
                    "rent": 3180,
                    "bedrooms": 2,
                    "detail_verified": True,
                },
                "verification": {"passes_current_hard_filters": True},
            }
        ],
        comparison_payload=None,
    )

    assert len(listings) == 1
    assert listings[0].id == "listing-1"
    assert listings[0].title == "Heatherstone Apartments"
    assert listings[0].price == 3180


def test_chat_maps_agent_failure_to_stable_gateway_error() -> None:
    class FailingAgentService:
        async def send_message(
            self,
            message: str,
            conversation_id: str | None = None,
            *,
            user_id: str,
        ):
            raise AgentServiceError("provider details must stay private")

    application = contract_test_app()
    application.dependency_overrides[get_agent_service] = lambda: FailingAgentService()
    try:
        response = TestClient(application).post(
            "/api/chat", json={"message": "Find a rental"}
        )
        assert response.status_code == 502
        assert response.json() == {"detail": "Rental agent is temporarily unavailable."}
    finally:
        application.dependency_overrides.clear()


def test_selected_route_http_contract() -> None:
    class FakeRouteService:
        async def get_selected_route(
            self,
            listing_id: str,
            conversation_id: str,
            *,
            destination: str = "",
            mode: str = "",
            user_id: str,
        ):
            assert listing_id == "listing-1"
            assert conversation_id == "conversation-1"
            assert destination == "Google Mountain View"
            assert mode == "DRIVE"
            assert user_id == "contract-test-user"
            return _route_from_tool_payload(
                {
                    "listing_id": listing_id,
                    "destination": destination,
                    "mode": mode,
                    "duration_minutes": 18,
                    "distance_meters": 12400,
                    "encoded_polyline": "abc123",
                    "status": "available",
                    "routing_preference": "TRAFFIC_AWARE",
                }
            )

    application = contract_test_app()
    application.dependency_overrides[get_agent_service] = lambda: FakeRouteService()
    try:
        response = TestClient(application).post(
            "/api/route",
            json={
                "listingId": "listing-1",
                "conversationId": "conversation-1",
                "destination": "Google Mountain View",
                "mode": "DRIVE",
            },
        )
        assert response.status_code == 200
        assert response.json() == {
            "listingId": "listing-1",
            "destination": "Google Mountain View",
            "destinationPlaceId": None,
            "mode": "DRIVE",
            "durationMinutes": 18,
            "distanceMeters": 12400,
            "status": "available",
            "routingPreference": "TRAFFIC_AWARE",
            "encodedPolyline": "abc123",
        }
    finally:
        application.dependency_overrides.clear()


def test_comparison_http_contract_returns_facts_and_gemini_explanation() -> None:
    class FakeComparisonService:
        async def compare_listings(
            self,
            listing_ids: list[str],
            conversation_id: str,
            *,
            user_id: str,
        ):
            assert listing_ids == ["one", "two"]
            assert conversation_id == "conversation-1"
            assert user_id == "contract-test-user"
            return {
                "conversationId": conversation_id,
                "message": "One is cheaper; two has stronger parking evidence.",
                "listings": [],
                "comparison": {
                    "schemaVersion": "kbf.canonical-comparison.v1",
                    "listingIds": listing_ids,
                    "results": [
                        {
                            "listingId": listing_id,
                            "hardConstraintStatus": "pass",
                            "satisfiesCurrentRequirements": True,
                            "softPreferenceEvidence": [],
                            "tradeoffs": [],
                            "comparisonUnknowns": [],
                            "decisionUnknowns": [],
                            "decisionReady": True,
                            "score": None,
                            "rank": rank,
                        }
                        for rank, listing_id in enumerate(listing_ids, 1)
                    ],
                },
                "searchPerformed": False,
                "mode": "adk",
            }

    application = contract_test_app()
    application.dependency_overrides[get_agent_service] = (
        lambda: FakeComparisonService()
    )
    try:
        response = TestClient(application).post(
            "/api/compare",
            json={
                "listingIds": ["one", "two"],
                "conversationId": "conversation-1",
            },
        )
        assert response.status_code == 200
        assert response.json()["comparison"]["listingIds"] == ["one", "two"]
        assert response.json()["message"].startswith("One is cheaper")

        invalid = TestClient(application).post(
            "/api/compare",
            json={
                "listingIds": ["one", "one"],
                "conversationId": "conversation-1",
            },
        )
        assert invalid.status_code == 422
    finally:
        application.dependency_overrides.clear()


def test_comparison_prompt_keeps_listing_ids_out_of_user_facing_copy() -> None:
    captured: dict[str, str] = {}
    service = AgentService(mode="stub")

    async def fake_send_message(
        message: str,
        conversation_id: str | None = None,
        *,
        user_id: str,
    ) -> SearchResponse:
        captured["message"] = message
        assert conversation_id == "conversation-1"
        assert user_id == "user-1"
        return SearchResponse(
            conversationId="conversation-1",
            message="Compare 151 S Bernardo Ave and 988 E El Camino Real.",
            comparison={
                "schemaVersion": "kbf.canonical-comparison.v1",
                "listingIds": ["74pt6lx", "v0c38pe"],
                "results": [],
            },
            mode="stub",
        )

    service.send_message = fake_send_message  # type: ignore[method-assign]
    response = asyncio.run(
        service.compare_listings(
            ["74pt6lx", "v0c38pe"],
            "conversation-1",
            user_id="user-1",
        )
    )

    assert "refer to homes by address or property name" in captured["message"]
    assert "do not display internal listing IDs" in captured["message"]
    assert "same order as the JSON array" in captured["message"]
    assert "Use plain renter-friendly language" in captured["message"]
    assert "structured compare_candidates response as the only fact source" in captured[
        "message"
    ]
    assert "For query-backed values" in captured["message"]
    assert "mentioned only in a listing description" in captured["message"]
    assert (
        "word confirmed only when the structured tool result"
        in captured["message"]
    )
    assert response.comparison is not None
    assert response.comparison.listingIds == ["74pt6lx", "v0c38pe"]
    assert response.message.endswith(
        "## Decision\nDecision pending. Structured comparison facts are unavailable."
    )


def test_comparison_synthesizes_final_decision_from_structured_facts() -> None:
    service = AgentService(mode="stub")

    async def fake_send_message(
        message: str,
        conversation_id: str | None = None,
        *,
        user_id: str,
    ) -> SearchResponse:
        return SearchResponse(
            conversationId=conversation_id or "conversation-1",
            message="Gemini comparison without the required final section.",
            comparison={
                "schemaVersion": "kbf.canonical-comparison.v1",
                "listingIds": ["weak", "strong"],
                "results": [
                    {
                        "listingId": "weak",
                        "hardConstraintStatus": "pass",
                        "decisionReady": True,
                        "rank": 2,
                        "score": 71.0,
                    },
                    {
                        "listingId": "strong",
                        "hardConstraintStatus": "pass",
                        "decisionReady": True,
                        "rank": 1,
                        "score": 92.5,
                    },
                ],
            },
            mode="stub",
        )

    service.send_message = fake_send_message  # type: ignore[method-assign]
    response = asyncio.run(
        service.compare_listings(
            ["weak", "strong"],
            "conversation-1",
            user_id="user-1",
        )
    )

    assert response.message.endswith(
        "## Decision\nOption 2 is the strongest decision-ready choice based on the confirmed comparison evidence."
    )


@pytest.mark.parametrize(
    "returned_ids",
    [
        ["one"],
        ["two", "one"],
    ],
    ids=["missing-listing", "reordered-listings"],
)
def test_comparison_rejects_a_changed_listing_selection(
    returned_ids: list[str],
) -> None:
    service = AgentService(mode="stub")

    async def fake_send_message(
        message: str,
        conversation_id: str | None = None,
        *,
        user_id: str,
    ) -> SearchResponse:
        return SearchResponse(
            conversationId=conversation_id or "conversation-1",
            message="Comparison explanation.",
            comparison={
                "schemaVersion": "kbf.canonical-comparison.v1",
                "listingIds": returned_ids,
                "results": [],
            },
            mode="stub",
        )

    service.send_message = fake_send_message  # type: ignore[method-assign]

    with pytest.raises(
        AgentServiceError,
        match="different listing selection",
    ):
        asyncio.run(
            service.compare_listings(
                ["one", "two"],
                "conversation-1",
                user_id="user-1",
            )
        )
