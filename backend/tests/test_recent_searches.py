from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

import backend.app.repositories.memory as memory_repository
from backend.app.auth import AuthenticatedUser, get_current_user
from backend.app.config import Settings
from backend.app.main import create_app
from backend.app.repositories.base import RepositoryUnavailableError
from backend.app.repositories.memory import MemoryConversationRepository
from backend.app.services.conversation_service import (
    ConversationService,
    get_conversation_service,
)


def _listing(listing_id: str) -> dict[str, object]:
    return {
        "id": listing_id,
        "title": f"Listing {listing_id}",
        "price": 3200,
        "bedrooms": 2,
        "commute": {
            "destination": "Google Mountain View",
            "mode": "DRIVE",
            "durationMinutes": 18,
            "status": "available",
        },
    }


async def _record_successful_search(
    repository: MemoryConversationRepository,
    conversation_id: str,
    user_id: str,
) -> None:
    await repository.claim(conversation_id, user_id)
    await repository.record_response(
        conversation_id,
        user_id,
        listings=[_listing(f"listing-{conversation_id}")],
        commute_status="available",
        route_listing_id=None,
    )


def test_memory_lists_only_successful_user_conversations_newest_first(
    monkeypatch,
) -> None:
    start = datetime(2026, 8, 20, 18, 0, tzinfo=timezone.utc)
    clock = iter(start + timedelta(minutes=index) for index in range(7))
    monkeypatch.setattr(memory_repository, "_now", lambda: next(clock))
    repository = MemoryConversationRepository()

    async def scenario():
        await repository.claim("zero-turn", "user-a")
        await _record_successful_search(repository, "old", "user-a")
        await _record_successful_search(repository, "other-user", "user-b")
        await _record_successful_search(repository, "new", "user-a")
        return (
            await repository.list_for_user("user-a", limit=20),
            await repository.list_for_user("user-b", limit=20),
        )

    user_a, user_b = asyncio.run(scenario())

    assert [item.conversation_id for item in user_a] == ["new", "old"]
    assert [item.conversation_id for item in user_b] == ["other-user"]
    assert user_a[0].turn_count == 1
    assert user_a[0].last_listings[0]["id"] == "listing-new"
    assert user_a[0].last_commute_status == "available"


def test_memory_recent_searches_respect_requested_and_default_limits(
    monkeypatch,
) -> None:
    start = datetime(2026, 8, 20, 18, 0, tzinfo=timezone.utc)
    clock = iter(start + timedelta(minutes=index) for index in range(42))
    monkeypatch.setattr(memory_repository, "_now", lambda: next(clock))
    repository = MemoryConversationRepository()

    async def scenario():
        for index in range(21):
            await _record_successful_search(
                repository, f"conversation-{index}", "user-a"
            )
        return (
            await repository.list_for_user("user-a"),
            await repository.list_for_user("user-a", limit=2),
        )

    default_items, limited_items = asyncio.run(scenario())

    assert len(default_items) == 20
    assert len(limited_items) == 2
    assert limited_items[0].conversation_id == "conversation-20"


def test_conversation_service_returns_typed_lightweight_recent_searches() -> None:
    repository = MemoryConversationRepository()
    service = ConversationService(repository)

    async def scenario():
        await _record_successful_search(repository, "conversation-1", "user-a")
        return await service.list_for_user("user-a", limit=20)

    response = asyncio.run(scenario())
    item = response.items[0]

    assert item.conversationId == "conversation-1"
    assert item.turnCount == 1
    assert item.listings[0].id == "listing-conversation-1"
    assert item.lastCommuteStatus == "available"
    assert "uid" not in item.model_dump()
    assert "ownerHash" not in item.model_dump()
    assert "events" not in item.model_dump()
    assert "transcript" not in item.model_dump()


def _recent_searches_app(service: ConversationService, user_id: str = "user-a"):
    application = create_app(
        Settings(
            agent_mode="stub",
            auth_mode="firebase",
            app_environment="test",
            firebase_project_id="test-project",
            persistence_mode="memory",
        )
    )
    application.dependency_overrides[get_current_user] = lambda: AuthenticatedUser(
        uid=user_id, sign_in_provider="test"
    )
    application.dependency_overrides[get_conversation_service] = lambda: service
    return application


def test_recent_searches_endpoint_uses_verified_user_and_returns_bounded_metadata() -> None:
    repository = MemoryConversationRepository()
    service = ConversationService(repository)

    async def seed():
        await _record_successful_search(repository, "user-a-1", "user-a")
        await _record_successful_search(repository, "user-a-2", "user-a")
        await _record_successful_search(repository, "user-b-1", "user-b")

    asyncio.run(seed())
    client = TestClient(_recent_searches_app(service))

    response = client.get(
        "/api/conversations?limit=1&user_id=user-b&uid=user-b"
    )

    assert response.status_code == 200
    payload = response.json()
    assert len(payload["items"]) == 1
    assert payload["items"][0]["conversationId"] in {"user-a-1", "user-a-2"}
    assert set(payload["items"][0]) == {
        "conversationId",
        "createdAt",
        "updatedAt",
        "turnCount",
        "listings",
        "lastCommuteStatus",
    }


def test_recent_searches_endpoint_default_and_requested_limits() -> None:
    repository = MemoryConversationRepository()
    service = ConversationService(repository)

    async def seed():
        for index in range(21):
            await _record_successful_search(
                repository, f"conversation-{index}", "user-a"
            )

    asyncio.run(seed())
    client = TestClient(_recent_searches_app(service))

    default_response = client.get("/api/conversations")
    limited_response = client.get("/api/conversations?limit=2")

    assert default_response.status_code == 200
    assert len(default_response.json()["items"]) == 20
    assert limited_response.status_code == 200
    assert len(limited_response.json()["items"]) == 2


def test_recent_searches_endpoint_rejects_limits_outside_api_range() -> None:
    client = TestClient(
        _recent_searches_app(ConversationService(MemoryConversationRepository()))
    )

    assert client.get("/api/conversations?limit=0").status_code == 422
    assert client.get("/api/conversations?limit=51").status_code == 422


def test_recent_searches_endpoint_requires_authentication() -> None:
    application = create_app(
        Settings(
            agent_mode="stub",
            auth_mode="firebase",
            app_environment="test",
            firebase_project_id="test-project",
            persistence_mode="memory",
        )
    )

    response = TestClient(application).get("/api/conversations")

    assert response.status_code == 401


def test_recent_searches_endpoint_maps_repository_unavailable_to_503() -> None:
    class UnavailableConversationRepository:
        async def list_for_user(self, user_id: str, limit: int = 20):
            raise RepositoryUnavailableError("private persistence detail")

    service = ConversationService(UnavailableConversationRepository())
    client = TestClient(_recent_searches_app(service))

    response = client.get("/api/conversations")

    assert response.status_code == 503
    assert response.json() == {
        "detail": "Conversation storage is temporarily unavailable."
    }
