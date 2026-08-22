from __future__ import annotations

import asyncio
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from backend.app.repositories.firestore import (
    FirestoreConversationRepository,
    FirestoreRateLimitRepository,
    FirestoreShortlistRepository,
    _document_id,
    _owner_hash,
)


@dataclass(slots=True)
class _FakeSnapshot:
    data: dict[str, Any] | None

    @property
    def exists(self) -> bool:
        return self.data is not None

    def to_dict(self) -> dict[str, Any] | None:
        return deepcopy(self.data)


class _FakeDocument:
    def __init__(self, client: _FakeFirestoreClient, path: tuple[str, ...]) -> None:
        self._client = client
        self.path = path

    def collection(self, name: str) -> _FakeCollection:
        return _FakeCollection(self._client, (*self.path, name))

    def get(self, *, transaction: object | None = None) -> _FakeSnapshot:
        if transaction is not None:
            self._client.transaction_reads += 1
        return _FakeSnapshot(deepcopy(self._client.documents.get(self.path)))

    def delete(self) -> None:
        self._client.documents.pop(self.path, None)
        self._client.deletes += 1


class _FakeCollection:
    def __init__(self, client: _FakeFirestoreClient, path: tuple[str, ...]) -> None:
        self._client = client
        self.path = path

    def document(self, document_id: str) -> _FakeDocument:
        return _FakeDocument(self._client, (*self.path, document_id))

    def where(self, field: str, operator: str, value: object) -> _FakeQuery:
        self._client.queries += 1
        return _FakeQuery(self._client, self.path).where(
            field, operator, value
        )

    def order_by(self, field: str, *, direction: str) -> _FakeQuery:
        self._client.queries += 1
        return _FakeQuery(self._client, self.path, field, direction)


class _FakeQuery:
    def __init__(
        self,
        client: _FakeFirestoreClient,
        collection_path: tuple[str, ...],
        field: str | None = None,
        direction: str = "ASCENDING",
    ) -> None:
        self._client = client
        self._collection_path = collection_path
        self._field = field
        self._direction = direction
        self._filters: list[tuple[str, str, object]] = []
        self._limit: int | None = None
        self._start_after: _FakeSnapshot | None = None

    def where(self, field: str, operator: str, value: object) -> _FakeQuery:
        self._filters.append((field, operator, value))
        return self

    def order_by(self, field: str, *, direction: str) -> _FakeQuery:
        self._field = field
        self._direction = direction
        return self

    def limit(self, count: int) -> _FakeQuery:
        self._limit = count
        self._client.query_limits.append(count)
        return self

    def start_after(self, snapshot: _FakeSnapshot) -> _FakeQuery:
        self._start_after = snapshot
        self._client.start_after_calls += 1
        return self

    def stream(self) -> list[_FakeSnapshot]:
        documents = [
            deepcopy(data)
            for path, data in self._client.documents.items()
            if path[:-1] == self._collection_path
        ]
        for field, operator, value in self._filters:
            if operator != "==":
                raise AssertionError(f"Unsupported fake filter: {operator}")
            documents = [
                document for document in documents if document.get(field) == value
            ]
        if self._field is not None:
            documents.sort(
                key=lambda data: data[self._field],
                reverse=self._direction == "DESCENDING",
            )
        if self._start_after is not None:
            marker_id = (self._start_after.to_dict() or {}).get(
                "conversationId"
            )
            marker_index = next(
                (
                    index
                    for index, document in enumerate(documents)
                    if document.get("conversationId") == marker_id
                ),
                len(documents) - 1,
            )
            documents = documents[marker_index + 1 :]
        if self._limit is not None:
            documents = documents[: self._limit]
        return [_FakeSnapshot(document) for document in documents]


class _FakeTransaction:
    def __init__(self, client: _FakeFirestoreClient) -> None:
        self._client = client

    def set(self, document: _FakeDocument, data: dict[str, Any]) -> None:
        self._client.documents[document.path] = deepcopy(data)
        self._client.transaction_writes += 1


class _FakeFirestoreClient:
    """Small shared backing store implementing only the adapter calls we use."""

    def __init__(self) -> None:
        self.documents: dict[tuple[str, ...], dict[str, Any]] = {}
        self.transactions = 0
        self.transaction_reads = 0
        self.transaction_writes = 0
        self.queries = 0
        self.deletes = 0
        self.query_limits: list[int] = []
        self.start_after_calls = 0

    def collection(self, name: str) -> _FakeCollection:
        return _FakeCollection(self, (name,))

    def transaction(self) -> _FakeTransaction:
        self.transactions += 1
        return _FakeTransaction(self)


def test_firestore_adapters_persist_across_repository_instances(
    monkeypatch,
) -> None:
    """Exercise Firestore transaction/query paths without cloud credentials."""

    from firebase_admin import firestore

    # The production decorator adds retry behavior around a Google transaction.
    # This bounded fake runs the same decorated function once so the adapter's
    # transaction reads and writes are still exercised deterministically.
    monkeypatch.setattr(firestore, "transactional", lambda function: function)
    client = _FakeFirestoreClient()
    listing = {
        "id": "provider/listing-1",
        "title": "Heatherstone Apartments",
        "latitude": 37.401,
        "longitude": -122.101,
        "commute": {
            "destination": "Google Mountain View",
            "mode": "DRIVE",
            "durationMinutes": 18,
            "status": "available",
        },
    }

    async def scenario():
        conversations = FirestoreConversationRepository(client)
        claimed = await conversations.claim("conversation-1", "user-a")
        recorded = await conversations.record_response(
            "conversation-1",
            "user-a",
            listings=[listing],
            commute_status="available",
            route_listing_id="provider/listing-1",
            comparison={
                "schemaVersion": "kbf.canonical-comparison.v1",
                "listingIds": ["provider/listing-1"],
                "results": [],
            },
        )

        # New adapter objects share only the fake Firestore client. Their ability
        # to read the records proves the data is not held on repository objects.
        recreated_conversations = FirestoreConversationRepository(client)
        loaded = await recreated_conversations.get_for_user(
            "conversation-1", "user-a"
        )

        shortlist = FirestoreShortlistRepository(client)
        saved = await shortlist.save(
            "user-a",
            listing_id="provider/listing-1",
            source_conversation_id="conversation-1",
            listing_snapshot=listing,
        )
        updated = await shortlist.update_note(
            "user-a", "provider/listing-1", "Tour Saturday"
        )
        recreated_shortlist = FirestoreShortlistRepository(client)
        listed = await recreated_shortlist.list_for_user("user-a")
        await recreated_shortlist.remove("user-a", "provider/listing-1")
        empty = await FirestoreShortlistRepository(client).list_for_user(
            "user-a"
        )
        return claimed, recorded, loaded, saved, updated, listed, empty

    claimed, recorded, loaded, saved, updated, listed, empty = asyncio.run(scenario())

    assert claimed.turn_count == 0
    assert recorded.turn_count == 1
    assert loaded.last_route_listing_id == "provider/listing-1"
    assert loaded.last_listings[0]["commute"]["durationMinutes"] == 18
    assert loaded.last_comparison is not None
    assert saved.listing_id == "provider/listing-1"
    assert updated.note == "Tour Saturday"
    assert [item.listing_id for item in listed] == ["provider/listing-1"]
    assert empty == []
    assert client.transactions == 4
    assert client.transaction_reads == 4
    assert client.transaction_writes == 4
    assert client.queries == 2
    assert client.deletes == 1


def test_firestore_rate_limit_is_shared_across_repository_instances(
    monkeypatch,
) -> None:
    from firebase_admin import firestore

    monkeypatch.setattr(firestore, "transactional", lambda function: function)
    client = _FakeFirestoreClient()
    now = datetime(2026, 8, 20, tzinfo=timezone.utc)

    async def scenario():
        first_repository = FirestoreRateLimitRepository(client)
        first = await first_repository.consume(
            "firebase-anonymous-uid",
            limit=2,
            window_seconds=3600,
            now=now,
        )
        second_repository = FirestoreRateLimitRepository(client)
        second = await second_repository.consume(
            "firebase-anonymous-uid",
            limit=2,
            window_seconds=3600,
            now=now,
        )
        blocked = await first_repository.consume(
            "firebase-anonymous-uid",
            limit=2,
            window_seconds=3600,
            now=now,
        )
        return first, second, blocked

    first, second, blocked = asyncio.run(scenario())

    assert first.allowed is True
    assert first.remaining == 1
    assert second.allowed is True
    assert second.remaining == 0
    assert blocked.allowed is False
    assert blocked.remaining == 0
    assert client.transactions == 3
    assert client.transaction_reads == 3
    assert client.transaction_writes == 2
    [(path, document)] = list(client.documents.items())
    assert path[0] == "rateLimits"
    assert "firebase-anonymous-uid" not in "/".join(path)
    assert document["requestCount"] == 2


def _seed_conversation_document(
    client: _FakeFirestoreClient,
    conversation_id: str,
    user_id: str,
    updated_at: datetime,
    turn_count: int,
) -> None:
    client.documents[
        ("conversations", _document_id("conversation", conversation_id))
    ] = {
        "conversationId": conversation_id,
        "ownerHash": _owner_hash(user_id),
        "createdAt": updated_at - timedelta(minutes=1),
        "updatedAt": updated_at,
        "turnCount": turn_count,
        "lastListings": [_listing(conversation_id)],
        "lastCommuteStatus": "available",
        "lastRouteListingId": None,
    }


def _listing(listing_id: str) -> dict[str, object]:
    return {
        "id": f"listing-{listing_id}",
        "title": "Heatherstone Apartments",
        "price": 3180,
    }


def test_firestore_conversation_list_is_user_scoped_ordered_bounded_and_successful_only() -> None:
    client = _FakeFirestoreClient()
    start = datetime(2026, 8, 20, 18, 0, tzinfo=timezone.utc)
    _seed_conversation_document(client, "old", "user-a", start, 1)
    _seed_conversation_document(
        client, "new", "user-a", start + timedelta(minutes=1), 1
    )
    _seed_conversation_document(
        client, "zero-turn", "user-a", start + timedelta(minutes=2), 0
    )
    _seed_conversation_document(
        client, "other-user", "user-b", start + timedelta(minutes=3), 1
    )

    async def scenario():
        repository = FirestoreConversationRepository(client)
        return await repository.list_for_user("user-a", limit=2)

    items = asyncio.run(scenario())

    assert [item.conversation_id for item in items] == ["new", "old"]
    assert all(item.user_id == "user-a" for item in items)
    assert all(item.turn_count > 0 for item in items)


def test_firestore_conversation_list_pages_past_zero_turn_records() -> None:
    client = _FakeFirestoreClient()
    start = datetime(2026, 8, 20, 18, 0, tzinfo=timezone.utc)
    _seed_conversation_document(
        client, "old-success", "user-a", start, 1
    )
    _seed_conversation_document(
        client, "new-success", "user-a", start + timedelta(minutes=1), 1
    )
    for index in range(20):
        _seed_conversation_document(
            client,
            f"new-zero-turn-{index}",
            "user-a",
            start + timedelta(minutes=index + 2),
            0,
        )

    async def scenario():
        repository = FirestoreConversationRepository(client)
        return await repository.list_for_user("user-a", limit=2)

    items = asyncio.run(scenario())

    assert [item.conversation_id for item in items] == [
        "new-success",
        "old-success",
    ]
    assert client.query_limits == [20, 20]
    assert client.start_after_calls == 1


def test_firestore_conversation_list_uses_batch_pages_for_small_limits() -> None:
    client = _FakeFirestoreClient()
    start = datetime(2026, 8, 20, 18, 0, tzinfo=timezone.utc)
    for index in range(21):
        _seed_conversation_document(
            client,
            f"new-zero-turn-{index}",
            "user-a",
            start + timedelta(minutes=index + 1),
            0,
        )
    _seed_conversation_document(client, "old-success", "user-a", start, 1)

    async def scenario():
        repository = FirestoreConversationRepository(client)
        return await repository.list_for_user("user-a", limit=1)

    items = asyncio.run(scenario())

    assert [item.conversation_id for item in items] == ["old-success"]
    assert client.query_limits == [20, 20]
    assert client.start_after_calls == 1
