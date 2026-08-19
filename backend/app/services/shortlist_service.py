from __future__ import annotations

from functools import lru_cache

from backend.app.models.search import (
    ListingResponse,
    ShortlistItemResponse,
    ShortlistResponse,
)
from backend.app.repositories.base import (
    ConversationNotFoundError,
    ConversationOwnershipError,
    ConversationRepository,
    RepositoryError,
    ShortlistItem,
    ShortlistRepository,
)
from backend.app.repositories.dependencies import (
    get_conversation_repository,
    get_shortlist_repository,
)


class ShortlistServiceError(RuntimeError):
    """Stable service boundary for shortlist failures."""


class ShortlistConversationNotFoundError(ShortlistServiceError):
    """The source conversation no longer exists."""


class ShortlistConversationAccessError(ShortlistServiceError):
    """The source conversation belongs to another user."""


class ShortlistListingNotFoundError(ShortlistServiceError):
    """The listing was not present in the conversation's latest result."""


class ShortlistPersistenceUnavailableError(ShortlistServiceError):
    """The configured repository could not complete the request."""


def _response(item: ShortlistItem) -> ShortlistItemResponse:
    return ShortlistItemResponse(
        listing=ListingResponse.model_validate(item.listing_snapshot),
        sourceConversationId=item.source_conversation_id,
        savedAt=item.saved_at,
        updatedAt=item.updated_at,
    )


class ShortlistService:
    def __init__(
        self,
        conversation_repository: ConversationRepository,
        shortlist_repository: ShortlistRepository,
    ) -> None:
        self._conversations = conversation_repository
        self._shortlist = shortlist_repository

    async def list_for_user(self, user_id: str) -> ShortlistResponse:
        try:
            items = await self._shortlist.list_for_user(user_id)
            return ShortlistResponse(items=[_response(item) for item in items])
        except (RepositoryError, ValueError) as exc:
            raise ShortlistPersistenceUnavailableError(
                "Shortlist could not be loaded."
            ) from exc

    async def save(
        self,
        user_id: str,
        *,
        conversation_id: str,
        listing_id: str,
    ) -> ShortlistItemResponse:
        try:
            conversation = await self._conversations.get_for_user(
                conversation_id, user_id
            )
        except ConversationNotFoundError as exc:
            raise ShortlistConversationNotFoundError(
                "Source conversation was not found."
            ) from exc
        except ConversationOwnershipError as exc:
            raise ShortlistConversationAccessError(
                "Source conversation belongs to another user."
            ) from exc
        except RepositoryError as exc:
            raise ShortlistPersistenceUnavailableError(
                "Conversation metadata could not be loaded."
            ) from exc

        snapshot = next(
            (
                listing
                for listing in conversation.last_listings
                if str(listing.get("id", "")) == listing_id
            ),
            None,
        )
        if snapshot is None:
            raise ShortlistListingNotFoundError(
                "Listing was not found in the conversation's latest results."
            )

        try:
            item = await self._shortlist.save(
                user_id,
                listing_id=listing_id,
                source_conversation_id=conversation_id,
                listing_snapshot=snapshot,
            )
            return _response(item)
        except (RepositoryError, ValueError) as exc:
            raise ShortlistPersistenceUnavailableError(
                "Shortlist item could not be saved."
            ) from exc

    async def remove(self, user_id: str, listing_id: str) -> None:
        try:
            await self._shortlist.remove(user_id, listing_id)
        except RepositoryError as exc:
            raise ShortlistPersistenceUnavailableError(
                "Shortlist item could not be removed."
            ) from exc


@lru_cache(maxsize=1)
def get_shortlist_service() -> ShortlistService:
    return ShortlistService(
        get_conversation_repository(),
        get_shortlist_repository(),
    )
