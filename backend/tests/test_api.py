from fastapi.testclient import TestClient

from backend.app.auth import AuthenticatedUser, get_current_user
from backend.app.config import Settings
from backend.app.main import create_app
from backend.app.services.agent_service import (
    AgentService,
    AgentServiceError,
    _commute_evaluation_from_tool_payload,
    _normalize_tool_listings,
    _route_from_tool_payload,
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
