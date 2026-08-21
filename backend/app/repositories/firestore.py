from __future__ import annotations

import asyncio
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import hmac
from typing import Any

from backend.app.repositories.base import (
    DEFAULT_CONVERSATION_LIST_LIMIT,
    MAX_CONVERSATION_SCAN,
    ConversationMetadata,
    ConversationNotFoundError,
    ConversationOwnershipError,
    RepositoryUnavailableError,
    ShortlistItem,
    bounded_conversation_limit,
)


_SCHEMA_VERSION = "kbf.persistence.v1"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _document_id(namespace: str, value: str) -> str:
    """Make arbitrary external IDs safe to use as Firestore document IDs."""

    return hashlib.sha256(f"{namespace}:{value}".encode()).hexdigest()


def _owner_hash(user_id: str) -> str:
    return _document_id("user", user_id)


def _datetime(value: object, fallback: datetime) -> datetime:
    return value if isinstance(value, datetime) else fallback


def _string_or_none(value: object) -> str | None:
    return str(value) if value is not None else None


class FirestoreConversationRepository:
    def __init__(self, client: Any) -> None:
        self._client = client

    def _document(self, conversation_id: str):
        return self._client.collection("conversations").document(
            _document_id("conversation", conversation_id)
        )

    def _list_sync(
        self,
        user_id: str,
        limit: int,
    ) -> list[ConversationMetadata]:
        try:
            requested_limit = bounded_conversation_limit(limit)
            page_size = requested_limit
            query = (
                self._client.collection("conversations")
                .where("ownerHash", "==", _owner_hash(user_id))
                .order_by("updatedAt", direction="DESCENDING")
            )
            conversations: list[ConversationMetadata] = []
            cursor = None
            scanned = 0

            while scanned < MAX_CONVERSATION_SCAN:
                page_limit = min(page_size, MAX_CONVERSATION_SCAN - scanned)
                page_query = query.limit(page_limit)
                if cursor is not None:
                    page_query = page_query.start_after(cursor)
                page = list(page_query.stream())
                if not page:
                    break

                scanned += len(page)
                cursor = page[-1]
                for document in page:
                    conversation = self._from_data(
                        document.to_dict() or {}, user_id=user_id
                    )
                    if conversation.turn_count > 0:
                        conversations.append(conversation)
                        if len(conversations) == requested_limit:
                            return conversations

                if len(page) < page_limit:
                    break

            return conversations
        except ConversationOwnershipError:
            raise
        except Exception as exc:
            raise RepositoryUnavailableError(
                "Firestore could not list conversations."
            ) from exc

    async def list_for_user(
        self,
        user_id: str,
        limit: int = DEFAULT_CONVERSATION_LIST_LIMIT,
    ) -> list[ConversationMetadata]:
        return await asyncio.to_thread(self._list_sync, user_id, limit)

    @staticmethod
    def _from_data(
        data: dict[str, Any], *, user_id: str
    ) -> ConversationMetadata:
        owner_hash = str(data.get("ownerHash", ""))
        if not hmac.compare_digest(owner_hash, _owner_hash(user_id)):
            raise ConversationOwnershipError(
                "Conversation is owned by a different user."
            )
        now = _now()
        listings = data.get("lastListings", [])
        return ConversationMetadata(
            conversation_id=str(data.get("conversationId", "")),
            user_id=user_id,
            created_at=_datetime(data.get("createdAt"), now),
            updated_at=_datetime(data.get("updatedAt"), now),
            turn_count=max(int(data.get("turnCount", 0)), 0),
            last_listings=tuple(
                deepcopy(item)
                for item in listings
                if isinstance(item, dict)
            ),
            last_commute_status=_string_or_none(
                data.get("lastCommuteStatus")
            ),
            last_route_listing_id=_string_or_none(
                data.get("lastRouteListingId")
            ),
        )

    def _claim_sync(
        self, conversation_id: str, user_id: str
    ) -> ConversationMetadata:
        try:
            from firebase_admin import firestore

            document = self._document(conversation_id)
            transaction = self._client.transaction()
            owner_hash = _owner_hash(user_id)

            @firestore.transactional
            def claim(transaction):
                snapshot = document.get(transaction=transaction)
                if snapshot.exists:
                    data = snapshot.to_dict() or {}
                    existing_hash = str(data.get("ownerHash", ""))
                    if not hmac.compare_digest(existing_hash, owner_hash):
                        raise ConversationOwnershipError(
                            "Conversation is owned by a different user."
                        )
                    return data

                now = _now()
                data = {
                    "schemaVersion": _SCHEMA_VERSION,
                    "conversationId": conversation_id,
                    "ownerHash": owner_hash,
                    "createdAt": now,
                    "updatedAt": now,
                    "turnCount": 0,
                    "lastListings": [],
                    "lastCommuteStatus": None,
                    "lastRouteListingId": None,
                }
                transaction.set(document, data)
                return data

            return self._from_data(claim(transaction), user_id=user_id)
        except ConversationOwnershipError:
            raise
        except Exception as exc:
            raise RepositoryUnavailableError(
                "Firestore could not claim the conversation."
            ) from exc

    async def claim(
        self, conversation_id: str, user_id: str
    ) -> ConversationMetadata:
        return await asyncio.to_thread(
            self._claim_sync, conversation_id, user_id
        )

    def _get_sync(
        self, conversation_id: str, user_id: str
    ) -> ConversationMetadata:
        try:
            snapshot = self._document(conversation_id).get()
            if not snapshot.exists:
                raise ConversationNotFoundError("Conversation was not found.")
            return self._from_data(snapshot.to_dict() or {}, user_id=user_id)
        except (ConversationNotFoundError, ConversationOwnershipError):
            raise
        except Exception as exc:
            raise RepositoryUnavailableError(
                "Firestore could not read the conversation."
            ) from exc

    async def get_for_user(
        self, conversation_id: str, user_id: str
    ) -> ConversationMetadata:
        return await asyncio.to_thread(
            self._get_sync, conversation_id, user_id
        )

    def _record_response_sync(
        self,
        conversation_id: str,
        user_id: str,
        *,
        listings: list[dict[str, Any]],
        commute_status: str | None,
        route_listing_id: str | None,
    ) -> ConversationMetadata:
        try:
            from firebase_admin import firestore

            document = self._document(conversation_id)
            transaction = self._client.transaction()
            owner_hash = _owner_hash(user_id)

            @firestore.transactional
            def update(transaction):
                snapshot = document.get(transaction=transaction)
                if not snapshot.exists:
                    raise ConversationNotFoundError(
                        "Conversation was not found."
                    )
                data = snapshot.to_dict() or {}
                existing_hash = str(data.get("ownerHash", ""))
                if not hmac.compare_digest(existing_hash, owner_hash):
                    raise ConversationOwnershipError(
                        "Conversation is owned by a different user."
                    )
                updated = {
                    **data,
                    "schemaVersion": _SCHEMA_VERSION,
                    "updatedAt": _now(),
                    "turnCount": max(int(data.get("turnCount", 0)), 0) + 1,
                    "lastListings": deepcopy(listings[:24]),
                    "lastCommuteStatus": commute_status,
                    "lastRouteListingId": route_listing_id,
                }
                transaction.set(document, updated)
                return updated

            return self._from_data(update(transaction), user_id=user_id)
        except (ConversationNotFoundError, ConversationOwnershipError):
            raise
        except Exception as exc:
            raise RepositoryUnavailableError(
                "Firestore could not update the conversation."
            ) from exc

    async def record_response(
        self,
        conversation_id: str,
        user_id: str,
        *,
        listings: list[dict[str, Any]],
        commute_status: str | None,
        route_listing_id: str | None,
    ) -> ConversationMetadata:
        return await asyncio.to_thread(
            self._record_response_sync,
            conversation_id,
            user_id,
            listings=listings,
            commute_status=commute_status,
            route_listing_id=route_listing_id,
        )


class FirestoreShortlistRepository:
    def __init__(self, client: Any) -> None:
        self._client = client

    def _collection(self, user_id: str):
        return (
            self._client.collection("users")
            .document(_owner_hash(user_id))
            .collection("shortlist")
        )

    def _document(self, user_id: str, listing_id: str):
        return self._collection(user_id).document(
            _document_id("listing", listing_id)
        )

    @staticmethod
    def _from_data(data: dict[str, Any]) -> ShortlistItem:
        now = _now()
        snapshot = data.get("listingSnapshot", {})
        if not isinstance(snapshot, dict):
            snapshot = {}
        return ShortlistItem(
            listing_id=str(data.get("listingId", "")),
            source_conversation_id=str(
                data.get("sourceConversationId", "")
            ),
            listing_snapshot=deepcopy(snapshot),
            saved_at=_datetime(data.get("savedAt"), now),
            updated_at=_datetime(data.get("updatedAt"), now),
        )

    def _list_sync(self, user_id: str) -> list[ShortlistItem]:
        try:
            query = self._collection(user_id).order_by(
                "savedAt", direction="DESCENDING"
            ).limit(24)
            return [
                self._from_data(document.to_dict() or {})
                for document in query.stream()
            ]
        except Exception as exc:
            raise RepositoryUnavailableError(
                "Firestore could not list the shortlist."
            ) from exc

    async def list_for_user(self, user_id: str) -> list[ShortlistItem]:
        return await asyncio.to_thread(self._list_sync, user_id)

    def _save_sync(
        self,
        user_id: str,
        *,
        listing_id: str,
        source_conversation_id: str,
        listing_snapshot: dict[str, Any],
    ) -> ShortlistItem:
        try:
            from firebase_admin import firestore

            document = self._document(user_id, listing_id)
            transaction = self._client.transaction()

            @firestore.transactional
            def save(transaction):
                existing = document.get(transaction=transaction)
                existing_data = existing.to_dict() or {} if existing.exists else {}
                now = _now()
                data = {
                    "schemaVersion": _SCHEMA_VERSION,
                    "listingId": listing_id,
                    "sourceConversationId": source_conversation_id,
                    "listingSnapshot": deepcopy(listing_snapshot),
                    "savedAt": existing_data.get("savedAt", now),
                    "updatedAt": now,
                }
                transaction.set(document, data)
                return data

            return self._from_data(save(transaction))
        except Exception as exc:
            raise RepositoryUnavailableError(
                "Firestore could not save the shortlist item."
            ) from exc

    async def save(
        self,
        user_id: str,
        *,
        listing_id: str,
        source_conversation_id: str,
        listing_snapshot: dict[str, Any],
    ) -> ShortlistItem:
        return await asyncio.to_thread(
            self._save_sync,
            user_id,
            listing_id=listing_id,
            source_conversation_id=source_conversation_id,
            listing_snapshot=listing_snapshot,
        )

    def _remove_sync(self, user_id: str, listing_id: str) -> None:
        try:
            self._document(user_id, listing_id).delete()
        except Exception as exc:
            raise RepositoryUnavailableError(
                "Firestore could not remove the shortlist item."
            ) from exc

    async def remove(self, user_id: str, listing_id: str) -> None:
        await asyncio.to_thread(self._remove_sync, user_id, listing_id)
