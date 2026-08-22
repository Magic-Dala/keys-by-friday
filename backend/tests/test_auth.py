from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from backend.app import auth
from backend.app.config import Settings, _auth_mode
from backend.app.main import create_app
from backend.app.services.agent_service import AgentService, get_agent_service


def firebase_test_client() -> TestClient:
    application = create_app(
        Settings(
            agent_mode="stub",
            auth_mode="firebase",
            firebase_project_id="test-project",
        )
    )
    service = AgentService(mode="stub")
    application.dependency_overrides[get_agent_service] = lambda: service
    return TestClient(application)


def test_firebase_mode_requires_an_authorization_header() -> None:
    response = firebase_test_client().post(
        "/api/chat", json={"message": "Find a rental"}
    )

    assert response.status_code == 401
    assert response.json() == {"detail": "A valid sign-in token is required."}
    assert response.headers["WWW-Authenticate"] == "Bearer"


def test_verified_firebase_token_can_chat(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_verify(token: str, project_id: str):
        assert token == "valid-user-a-token"
        assert project_id == "test-project"
        return {
            "uid": "user-a",
            "firebase": {"sign_in_provider": "anonymous"},
        }

    monkeypatch.setattr(auth, "verify_firebase_id_token", fake_verify)

    response = firebase_test_client().post(
        "/api/chat",
        headers={"Authorization": "Bearer valid-user-a-token"},
        json={"message": "Find a rental"},
    )

    assert response.status_code == 200
    assert response.json()["conversationId"]


def test_invalid_firebase_token_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_verify(token: str, project_id: str):
        raise auth.InvalidAuthenticationToken("test invalid token")

    monkeypatch.setattr(auth, "verify_firebase_id_token", fake_verify)

    response = firebase_test_client().post(
        "/api/chat",
        headers={"Authorization": "Bearer forged-token"},
        json={"message": "Find a rental"},
    )

    assert response.status_code == 401
    assert response.json() == {"detail": "A valid sign-in token is required."}


def test_second_user_cannot_continue_first_users_conversation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_verify(token: str, project_id: str):
        return {"uid": token, "firebase": {"sign_in_provider": "anonymous"}}

    monkeypatch.setattr(auth, "verify_firebase_id_token", fake_verify)
    client = firebase_test_client()

    first = client.post(
        "/api/chat",
        headers={"Authorization": "Bearer user-a"},
        json={"message": "Find a rental"},
    )
    conversation_id = first.json()["conversationId"]

    same_user = client.post(
        "/api/chat",
        headers={"Authorization": "Bearer user-a"},
        json={
            "message": "I also need parking",
            "conversationId": conversation_id,
        },
    )
    different_user = client.post(
        "/api/chat",
        headers={"Authorization": "Bearer user-b"},
        json={
            "message": "Show me that conversation",
            "conversationId": conversation_id,
        },
    )

    assert first.status_code == 200
    assert same_user.status_code == 200
    assert same_user.json()["conversationId"] == conversation_id
    assert different_user.status_code == 403
    assert different_user.json() == {
        "detail": "This conversation belongs to a different user."
    }


def test_second_user_cannot_request_first_users_selected_route(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_verify(token: str, project_id: str):
        return {"uid": token, "firebase": {"sign_in_provider": "anonymous"}}

    monkeypatch.setattr(auth, "verify_firebase_id_token", fake_verify)
    client = firebase_test_client()

    first = client.post(
        "/api/chat",
        headers={"Authorization": "Bearer user-a"},
        json={"message": "Find a rental"},
    )
    conversation_id = first.json()["conversationId"]

    different_user = client.post(
        "/api/route",
        headers={"Authorization": "Bearer user-b"},
        json={
            "listingId": "listing-1",
            "conversationId": conversation_id,
        },
    )

    assert different_user.status_code == 403
    assert different_user.json() == {
        "detail": "This conversation belongs to a different user."
    }


def test_cors_allows_the_browser_to_send_authorization() -> None:
    client = TestClient(create_app(Settings(agent_mode="stub")))

    response = client.options(
        "/api/chat",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "authorization,content-type",
        },
    )

    assert response.status_code == 200
    assert "authorization" in response.headers[
        "Access-Control-Allow-Headers"
    ].casefold()


def test_firebase_auth_requires_a_project_id() -> None:
    client = TestClient(
        create_app(
            Settings(
                agent_mode="stub",
                auth_mode="firebase",
                firebase_project_id=None,
            )
        )
    )

    readiness = client.get("/ready")
    chat = client.post(
        "/api/chat",
        headers={"Authorization": "Bearer any-token"},
        json={"message": "Find a rental"},
    )

    assert readiness.status_code == 503
    assert readiness.json()["checks"]["auth"] == "not_configured"
    assert chat.status_code == 503


def test_production_cannot_silently_disable_authentication() -> None:
    client = TestClient(
        create_app(
            Settings(
                agent_mode="stub",
                auth_mode="disabled",
                app_environment="production",
            )
        )
    )

    readiness = client.get("/ready")
    chat = client.post("/api/chat", json={"message": "Find a rental"})

    assert readiness.status_code == 503
    assert readiness.json()["checks"]["auth"] == "not_configured"
    assert chat.status_code == 503


def test_auth_mode_configuration_is_validated() -> None:
    assert _auth_mode(" Firebase ") == "firebase"
    assert _auth_mode(" DISABLED ") == "disabled"
    with pytest.raises(ValueError, match="AUTH_MODE"):
        _auth_mode("maybe")
