from fastapi.testclient import TestClient

from backend.app.main import app
from backend.app.services.agent_service import (
    AgentService,
    AgentServiceError,
    _normalize_tool_listings,
    get_agent_service,
)


def test_health() -> None:
    assert TestClient(app).get("/health").json() == {"status": "ok"}


def test_chat_contract_with_stub() -> None:
    app.dependency_overrides[get_agent_service] = lambda: AgentService(mode="stub")
    try:
        response = TestClient(app).post("/api/chat", json={"message": "2B2B in Mountain View"})
        assert response.status_code == 200
        payload = response.json()
        assert payload["conversationId"]
        assert payload["mode"] == "stub"
        assert payload["listings"] == []
    finally:
        app.dependency_overrides.clear()


def test_chat_rejects_blank_message() -> None:
    response = TestClient(app).post("/api/chat", json={"message": "   "})
    assert response.status_code == 422


def test_chat_normalizes_request_whitespace() -> None:
    app.dependency_overrides[get_agent_service] = lambda: AgentService(mode="stub")
    try:
        response = TestClient(app).post(
            "/api/chat", json={"message": "  2B2B in Mountain View  "}
        )
        assert response.status_code == 200
        assert response.json()["message"].endswith("2B2B in Mountain View")
    finally:
        app.dependency_overrides.clear()


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
    assert listing.score == 9.5
    assert listing.reason == "within budget; matches 2B2B"


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
        async def send_message(self, message: str, conversation_id: str | None = None):
            raise AgentServiceError("provider details must stay private")

    app.dependency_overrides[get_agent_service] = lambda: FailingAgentService()
    try:
        response = TestClient(app).post("/api/chat", json={"message": "Find a rental"})
        assert response.status_code == 502
        assert response.json() == {"detail": "Rental agent is temporarily unavailable."}
    finally:
        app.dependency_overrides.clear()
