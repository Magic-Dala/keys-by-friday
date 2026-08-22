from __future__ import annotations

from functools import lru_cache

from backend.app.models.search import (
    ListingResponse,
    RecentSearchResponse,
    RecentSearchesResponse,
)
from backend.app.repositories.base import (
    DEFAULT_CONVERSATION_LIST_LIMIT,
    ConversationMetadata,
    ConversationRepository,
    RepositoryError,
)
from backend.app.repositories.dependencies import get_conversation_repository


class RecentSearchesPersistenceUnavailableError(RuntimeError):
    """The configured conversation repository could not list recent searches."""


def _response(conversation: ConversationMetadata) -> RecentSearchResponse:
    return RecentSearchResponse(
        conversationId=conversation.conversation_id,
        createdAt=conversation.created_at,
        updatedAt=conversation.updated_at,
        turnCount=conversation.turn_count,
        listings=[
            ListingResponse.model_validate(listing)
            for listing in conversation.last_listings
        ],
        lastCommuteStatus=conversation.last_commute_status,
    )


class ConversationService:
    def __init__(self, conversation_repository: ConversationRepository) -> None:
        self._conversations = conversation_repository

    async def list_for_user(
        self,
        user_id: str,
        limit: int = DEFAULT_CONVERSATION_LIST_LIMIT,
    ) -> RecentSearchesResponse:
        try:
            conversations = await self._conversations.list_for_user(
                user_id, limit=limit
            )
            return RecentSearchesResponse(
                items=[_response(conversation) for conversation in conversations]
            )
        except (RepositoryError, ValueError) as exc:
            raise RecentSearchesPersistenceUnavailableError(
                "Recent searches could not be loaded."
            ) from exc


@lru_cache(maxsize=1)
def get_conversation_service() -> ConversationService:
    return ConversationService(get_conversation_repository())
