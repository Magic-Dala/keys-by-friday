from __future__ import annotations

import asyncio

import pytest
from fastapi.testclient import TestClient

from backend.app.auth import AuthenticatedUser, get_current_user
from backend.app.config import Settings, _persistence_mode
from backend.app.main import create_app
from backend.app.models.search import ListingResponse
from backend.app.repositories.base import (
    ConversationOwnershipError,
    RepositoryUnavailableError,
)
from backend.app.repositories.firestore import _document_id
from backend.app.repositories.memory import (
    MemoryConversationRepository,
    MemoryShortlistRepository,
)
from backend.app.services.agent_service import AgentService, get_agent_service
from backend.app.services.shortlist_service import (
    ShortlistService,
    get_shortlist_service,
)


def maps_listing() -> dict:
    return ListingResponse(
        id="listing/with:provider-id",
        title="Heatherstone Apartments",
        address="877 Heatherstone Way",
        price=3180,
        bedrooms=2,
        bathrooms=2,
        latitude=37.401,
        longitude=-122.101,
        commute={
            "destination": "Google Mountain View",
            "mode": "DRIVE",
            "durationMinutes": 18,
            "distanceMeters": 12400,
            "status": "available",
            "routingPreference": "TRAFFIC_AWARE",
        },
    ).model_dump(mode="json")


def test_memory_repositories_persist_metadata_maps_and_shortlist() -> None:
    conversations = MemoryConversationRepository()
    shortlist = MemoryShortlistRepository()
    service = ShortlistService(conversations, shortlist)

    async def scenario():
        await conversations.claim("conversation-1", "user-a")
        metadata = await conversations.record_response(
            "conversation-1",
            "user-a",
            listings=[maps_listing()],
            commute_status="available",
            route_listing_id=None,
        )
        saved = await service.save(
            "user-a",
            conversation_id="conversation-1",
            listing_id="listing/with:provider-id",
        )
        listed = await service.list_for_user("user-a")
        await service.remove("user-a", "listing/with:provider-id")
        empty = await service.list_for_user("user-a")
        return metadata, saved, listed, empty

    metadata, saved, listed, empty = asyncio.run(scenario())

    assert metadata.turn_count == 1
    assert metadata.last_commute_status == "available"
    assert saved.listing.latitude == 37.401
    assert saved.listing.commute is not None
    assert saved.listing.commute.durationMinutes == 18
    assert [item.listing.id for item in listed.items] == [
        "listing/with:provider-id"
    ]
    assert empty.items == []


def test_conversation_repository_prevents_cross_user_access() -> None:
    conversations = MemoryConversationRepository()

    async def scenario():
        await conversations.claim("conversation-1", "user-a")
        await conversations.claim("conversation-1", "user-b")

    with pytest.raises(ConversationOwnershipError):
        asyncio.run(scenario())


def test_shortlists_are_isolated_by_verified_user() -> None:
    conversations = MemoryConversationRepository()
    shortlist = MemoryShortlistRepository()
    service = ShortlistService(conversations, shortlist)

    async def scenario():
        await conversations.claim("conversation-a", "user-a")
        await conversations.record_response(
            "conversation-a",
            "user-a",
            listings=[maps_listing()],
            commute_status="available",
            route_listing_id=None,
        )
        await service.save(
            "user-a",
            conversation_id="conversation-a",
            listing_id="listing/with:provider-id",
        )
        return (
            await service.list_for_user("user-a"),
            await service.list_for_user("user-b"),
        )

    user_a, user_b = asyncio.run(scenario())

    assert len(user_a.items) == 1
    assert user_b.items == []


def test_stub_agent_records_conversation_metadata() -> None:
    conversations = MemoryConversationRepository()
    service = AgentService(
        mode="stub", conversation_repository=conversations
    )

    async def scenario():
        response = await service.send_message(
            "Find a rental", user_id="user-a"
        )
        metadata = await conversations.get_for_user(
            response.conversationId, "user-a"
        )
        return response, metadata

    response, metadata = asyncio.run(scenario())

    assert response.mode == "stub"
    assert metadata.turn_count == 1
    assert metadata.last_listings == ()


def test_shortlist_http_contract_uses_fastapi_not_direct_firestore() -> None:
    conversations = MemoryConversationRepository()
    shortlist = MemoryShortlistRepository()
    agent = AgentService(mode="stub", conversation_repository=conversations)
    shortlist_service = ShortlistService(conversations, shortlist)
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
        uid="user-a", sign_in_provider="test"
    )
    application.dependency_overrides[get_agent_service] = lambda: agent
    application.dependency_overrides[get_shortlist_service] = (
        lambda: shortlist_service
    )

    async def seed():
        await conversations.claim("conversation-1", "user-a")
        await conversations.record_response(
            "conversation-1",
            "user-a",
            listings=[maps_listing()],
            commute_status="available",
            route_listing_id=None,
        )

    asyncio.run(seed())
    client = TestClient(application)

    saved = client.post(
        "/api/shortlist",
        json={
            "listingId": "listing/with:provider-id",
            "conversationId": "conversation-1",
        },
    )
    listed = client.get("/api/shortlist")
    removed = client.delete(
        "/api/shortlist/listing%2Fwith%3Aprovider-id"
    )
    empty = client.get("/api/shortlist")

    assert saved.status_code == 201
    assert saved.json()["listing"]["commute"]["durationMinutes"] == 18
    assert [item["listing"]["id"] for item in listed.json()["items"]] == [
        "listing/with:provider-id"
    ]
    assert removed.status_code == 204
    assert empty.json() == {"items": []}


def test_firestore_document_ids_are_safe_and_deterministic() -> None:
    first = _document_id("listing", "provider/path:123")
    second = _document_id("listing", "provider/path:123")

    assert first == second
    assert len(first) == 64
    assert "/" not in first
    assert first != _document_id("conversation", "provider/path:123")


def test_persistence_mode_configuration_is_validated() -> None:
    assert _persistence_mode(" Firestore ") == "firestore"
    assert _persistence_mode(" MEMORY ") == "memory"
    with pytest.raises(ValueError, match="PERSISTENCE_MODE"):
        _persistence_mode("sqlite")


def test_cors_allows_browser_shortlist_delete() -> None:
    client = TestClient(create_app(Settings(agent_mode="stub")))

    response = client.options(
        "/api/shortlist/listing-1",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "DELETE",
            "Access-Control-Request-Headers": "authorization,content-type",
        },
    )

    assert response.status_code == 200
    assert "DELETE" in response.headers["Access-Control-Allow-Methods"]


def test_repository_initialization_failure_has_stable_503_response() -> None:
    application = create_app(Settings(agent_mode="stub"))

    @application.get("/test-only/repository-failure")
    async def repository_failure() -> None:
        raise RepositoryUnavailableError("private credential detail")

    response = TestClient(application).get(
        "/test-only/repository-failure"
    )

    assert response.status_code == 503
    assert response.json() == {
        "detail": "Persistence is temporarily unavailable."
    }
