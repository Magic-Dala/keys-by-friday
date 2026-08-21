from __future__ import annotations

import asyncio
from copy import deepcopy
from datetime import datetime, timezone

from backend.app.repositories.base import (
    DEFAULT_CONVERSATION_LIST_LIMIT,
    ConversationMetadata,
    ConversationNotFoundError,
    ConversationOwnershipError,
    ShortlistItem,
    bounded_conversation_limit,
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _copy_conversation(record: ConversationMetadata) -> ConversationMetadata:
    return ConversationMetadata(
        conversation_id=record.conversation_id,
        user_id=record.user_id,
        created_at=record.created_at,
        updated_at=record.updated_at,
        turn_count=record.turn_count,
        last_listings=tuple(deepcopy(record.last_listings)),
        last_commute_status=record.last_commute_status,
        last_route_listing_id=record.last_route_listing_id,
    )


class MemoryConversationRepository:
    """Small local/fake repository with the same contract as Firestore."""

    def __init__(self) -> None:
        self._records: dict[str, ConversationMetadata] = {}
        self._lock = asyncio.Lock()

    async def list_for_user(
        self,
        user_id: str,
        limit: int = DEFAULT_CONVERSATION_LIST_LIMIT,
    ) -> list[ConversationMetadata]:
        async with self._lock:
            records = [
                record
                for record in self._records.values()
                if record.user_id == user_id and record.turn_count > 0
            ]
            records.sort(key=lambda record: record.updated_at, reverse=True)
            return [
                _copy_conversation(record)
                for record in records[:bounded_conversation_limit(limit)]
            ]

    async def claim(
        self, conversation_id: str, user_id: str
    ) -> ConversationMetadata:
        async with self._lock:
            record = self._records.get(conversation_id)
            if record is not None and record.user_id != user_id:
                raise ConversationOwnershipError(
                    "Conversation is owned by a different user."
                )
            if record is None:
                now = _now()
                record = ConversationMetadata(
                    conversation_id=conversation_id,
                    user_id=user_id,
                    created_at=now,
                    updated_at=now,
                )
                self._records[conversation_id] = record
            return _copy_conversation(record)

    async def get_for_user(
        self, conversation_id: str, user_id: str
    ) -> ConversationMetadata:
        async with self._lock:
            record = self._records.get(conversation_id)
            if record is None:
                raise ConversationNotFoundError("Conversation was not found.")
            if record.user_id != user_id:
                raise ConversationOwnershipError(
                    "Conversation is owned by a different user."
                )
            return _copy_conversation(record)

    async def record_response(
        self,
        conversation_id: str,
        user_id: str,
        *,
        listings: list[dict],
        commute_status: str | None,
        route_listing_id: str | None,
    ) -> ConversationMetadata:
        async with self._lock:
            record = self._records.get(conversation_id)
            if record is None:
                raise ConversationNotFoundError("Conversation was not found.")
            if record.user_id != user_id:
                raise ConversationOwnershipError(
                    "Conversation is owned by a different user."
                )
            updated = ConversationMetadata(
                conversation_id=record.conversation_id,
                user_id=record.user_id,
                created_at=record.created_at,
                updated_at=_now(),
                turn_count=record.turn_count + 1,
                last_listings=tuple(deepcopy(listings[:24])),
                last_commute_status=commute_status,
                last_route_listing_id=route_listing_id,
            )
            self._records[conversation_id] = updated
            return _copy_conversation(updated)


class MemoryShortlistRepository:
    """In-memory implementation used locally and by fast automated tests."""

    def __init__(self) -> None:
        self._items: dict[tuple[str, str], ShortlistItem] = {}
        self._lock = asyncio.Lock()

    async def list_for_user(self, user_id: str) -> list[ShortlistItem]:
        async with self._lock:
            items = [
                item
                for (owner, _), item in self._items.items()
                if owner == user_id
            ]
            items.sort(key=lambda item: item.saved_at, reverse=True)
            return [
                ShortlistItem(
                    listing_id=item.listing_id,
                    source_conversation_id=item.source_conversation_id,
                    listing_snapshot=deepcopy(item.listing_snapshot),
                    saved_at=item.saved_at,
                    updated_at=item.updated_at,
                )
                for item in items[:24]
            ]

    async def save(
        self,
        user_id: str,
        *,
        listing_id: str,
        source_conversation_id: str,
        listing_snapshot: dict,
    ) -> ShortlistItem:
        async with self._lock:
            key = (user_id, listing_id)
            existing = self._items.get(key)
            now = _now()
            item = ShortlistItem(
                listing_id=listing_id,
                source_conversation_id=source_conversation_id,
                listing_snapshot=deepcopy(listing_snapshot),
                saved_at=existing.saved_at if existing else now,
                updated_at=now,
            )
            self._items[key] = item
            return ShortlistItem(
                listing_id=item.listing_id,
                source_conversation_id=item.source_conversation_id,
                listing_snapshot=deepcopy(item.listing_snapshot),
                saved_at=item.saved_at,
                updated_at=item.updated_at,
            )

    async def remove(self, user_id: str, listing_id: str) -> None:
        async with self._lock:
            self._items.pop((user_id, listing_id), None)
