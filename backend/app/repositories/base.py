from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol


class RepositoryError(RuntimeError):
    """Base error for persistence operations."""


class RepositoryUnavailableError(RepositoryError):
    """The configured persistence system could not complete an operation."""


class ConversationNotFoundError(RepositoryError):
    """The requested conversation metadata does not exist."""


class ConversationOwnershipError(RepositoryError):
    """The conversation belongs to a different authenticated user."""


class ShortlistItemNotFoundError(RepositoryError):
    """The requested shortlist item does not exist."""


@dataclass(frozen=True, slots=True)
class RateLimitUsage:
    allowed: bool
    limit: int
    remaining: int
    reset_at: datetime


@dataclass(frozen=True, slots=True)
class ConversationMetadata:
    conversation_id: str
    user_id: str
    created_at: datetime
    updated_at: datetime
    turn_count: int = 0
    last_listings: tuple[dict[str, Any], ...] = ()
    last_commute_status: str | None = None
    last_route_listing_id: str | None = None
    last_comparison: dict[str, Any] | None = None


@dataclass(frozen=True, slots=True)
class ShortlistItem:
    listing_id: str
    source_conversation_id: str
    listing_snapshot: dict[str, Any]
    note: str | None
    saved_at: datetime
    updated_at: datetime


class ConversationRepository(Protocol):
    async def claim(
        self, conversation_id: str, user_id: str
    ) -> ConversationMetadata: ...

    async def get_for_user(
        self, conversation_id: str, user_id: str
    ) -> ConversationMetadata: ...

    async def record_response(
        self,
        conversation_id: str,
        user_id: str,
        *,
        listings: list[dict[str, Any]] | None,
        comparison: dict[str, Any] | None = None,
        commute_status: str | None,
        route_listing_id: str | None,
    ) -> ConversationMetadata: ...


class ShortlistRepository(Protocol):
    async def list_for_user(self, user_id: str) -> list[ShortlistItem]: ...

    async def save(
        self,
        user_id: str,
        *,
        listing_id: str,
        source_conversation_id: str,
        listing_snapshot: dict[str, Any],
    ) -> ShortlistItem: ...

    async def update_note(
        self, user_id: str, listing_id: str, note: str | None
    ) -> ShortlistItem: ...

    async def remove(self, user_id: str, listing_id: str) -> None: ...


class RateLimitRepository(Protocol):
    async def consume(
        self,
        subject_id: str,
        *,
        limit: int,
        window_seconds: int,
        now: datetime,
    ) -> RateLimitUsage: ...
