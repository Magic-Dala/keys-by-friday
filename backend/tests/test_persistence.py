from __future__ import annotations

import asyncio

import pytest
from fastapi.testclient import TestClient

from backend.app.auth import AuthenticatedUser, get_current_user
from backend.app.config import Settings, _persistence_mode
from backend.app.main import create_app
from backend.app.models.search import ListingResponse, SearchResponse
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
        comparison_metadata = await conversations.record_response(
            "conversation-1",
            "user-a",
            listings=None,
            comparison={
                "schemaVersion": "kbf.canonical-comparison.v1",
                "listingIds": ["listing/with:provider-id"],
                "results": [],
            },
            commute_status=None,
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
        return metadata, comparison_metadata, saved, listed, empty

    metadata, comparison_metadata, saved, listed, empty = asyncio.run(scenario())

    assert metadata.turn_count == 1
    assert metadata.last_commute_status == "available"
    assert comparison_metadata.last_listings[0]["id"] == "listing/with:provider-id"
    assert comparison_metadata.last_comparison is not None
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


def test_comparison_updates_selected_snapshots_without_dropping_results() -> None:
    conversations = MemoryConversationRepository()
    service = AgentService(mode="stub", conversation_repository=conversations)
    original_one = ListingResponse(
        id="one",
        title="Heatherstone",
        price=3180,
        bedrooms=2,
        sourcePostings=[
            {
                "id": "one",
                "source": "realtyapi-apartments",
                "url": "https://example.com/one",
            }
        ],
    ).model_dump(mode="json")
    original_two = ListingResponse(
        id="two", title="Kentfield", price=3000, bedrooms=2
    ).model_dump(mode="json")
    verified_canonical = {
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
    response = SearchResponse(
        conversationId="conversation-1",
        message="Heatherstone allows cats and dogs.",
        listings=[
            ListingResponse(
                id="one",
                title="Heatherstone",
                price=3180,
                bedrooms=2,
                canonicalListing=verified_canonical,
            )
        ],
        comparison={
            "schemaVersion": "kbf.canonical-comparison.v1",
            "listingIds": ["one"],
            "results": [
                {
                    "listingId": "one",
                    "hardConstraintStatus": "pass",
                    "satisfiesCurrentRequirements": True,
                    "softPreferenceEvidence": [],
                    "tradeoffs": [],
                    "comparisonUnknowns": ["property.bathrooms"],
                    "decisionUnknowns": ["property.bathrooms"],
                    "decisionReady": False,
                    "score": None,
                    "rank": 1,
                }
            ],
        },
        searchPerformed=False,
        mode="adk",
    )

    async def scenario():
        await conversations.claim("conversation-1", "user-a")
        await conversations.record_response(
            "conversation-1",
            "user-a",
            listings=[original_one, original_two],
            commute_status=None,
            route_listing_id=None,
        )
        await service._record_conversation_response(response, user_id="user-a")
        metadata = await conversations.get_for_user(
            "conversation-1", "user-a"
        )
        return metadata

    metadata = asyncio.run(scenario())

    assert [item["id"] for item in metadata.last_listings] == ["one", "two"]
    assert metadata.last_listings[0]["canonicalListing"]["policies"][
        "petsAllowed"
    ] is True
    assert metadata.last_listings[0]["sourcePostings"][0]["id"] == "one"
    assert response.listings[0].sourcePostings[0].id == "one"


def test_detail_only_response_updates_persisted_listings() -> None:
    conversations = MemoryConversationRepository()
    service = AgentService(mode="stub", conversation_repository=conversations)
    response = SearchResponse(
        conversationId="conversation-1",
        message="Here are the verified details.",
        listings=[
            ListingResponse(
                id="detail-listing",
                title="Detailed Home",
                price=3250,
                bedrooms=2,
            )
        ],
        searchPerformed=False,
        mode="adk",
    )

    async def scenario():
        await conversations.claim("conversation-1", "user-a")
        await conversations.record_response(
            "conversation-1",
            "user-a",
            listings=[maps_listing()],
            commute_status=None,
            route_listing_id=None,
        )
        await service._record_conversation_response(response, user_id="user-a")
        return await conversations.get_for_user("conversation-1", "user-a")

    metadata = asyncio.run(scenario())

    assert [item["id"] for item in metadata.last_listings] == [
        "detail-listing"
    ]
    assert metadata.last_listings[0]["price"] == 3250


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
    updated = client.patch(
        "/api/shortlist/listing%2Fwith%3Aprovider-id",
        json={"note": "  Tour on Saturday  "},
    )
    listed = client.get("/api/shortlist")
    removed = client.delete(
        "/api/shortlist/listing%2Fwith%3Aprovider-id"
    )
    empty = client.get("/api/shortlist")

    assert saved.status_code == 201
    assert updated.status_code == 200
    assert updated.json()["note"] == "Tour on Saturday"
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
    assert "PATCH" in response.headers["Access-Control-Allow-Methods"]


def test_shortlist_note_completes_update_part_of_crud() -> None:
    conversations = MemoryConversationRepository()
    shortlist = MemoryShortlistRepository()
    service = ShortlistService(conversations, shortlist)

    async def scenario():
        await conversations.claim("conversation-1", "user-a")
        await conversations.record_response(
            "conversation-1",
            "user-a",
            listings=[maps_listing()],
            commute_status=None,
            route_listing_id=None,
        )
        await service.save(
            "user-a",
            conversation_id="conversation-1",
            listing_id="listing/with:provider-id",
        )
        return await service.update_note(
            "user-a", "listing/with:provider-id", "Tour on Saturday"
        )

    updated = asyncio.run(scenario())

    assert updated.note == "Tour on Saturday"


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
