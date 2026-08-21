from __future__ import annotations

import asyncio
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from backend.app.repositories.firestore import (
    FirestoreConversationRepository,
    FirestoreRateLimitRepository,
    FirestoreShortlistRepository,
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

    def order_by(self, field: str, *, direction: str) -> _FakeQuery:
        self._client.queries += 1
        return _FakeQuery(self._client, self.path, field, direction)


class _FakeQuery:
    def __init__(
        self,
        client: _FakeFirestoreClient,
        collection_path: tuple[str, ...],
        field: str,
        direction: str,
    ) -> None:
        self._client = client
        self._collection_path = collection_path
        self._field = field
        self._direction = direction
        self._limit: int | None = None

    def limit(self, count: int) -> _FakeQuery:
        self._limit = count
        return self

    def stream(self) -> list[_FakeSnapshot]:
        documents = [
            deepcopy(data)
            for path, data in self._client.documents.items()
            if path[:-1] == self._collection_path
        ]
        documents.sort(
            key=lambda data: data[self._field],
            reverse=self._direction == "DESCENDING",
        )
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
