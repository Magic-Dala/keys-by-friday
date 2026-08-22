from __future__ import annotations

from functools import lru_cache

from backend.app.config import Settings, get_settings
from backend.app.firebase import FirebaseAdminUnavailable, get_firestore_client
from backend.app.repositories.base import (
    ConversationRepository,
    RateLimitRepository,
    RepositoryUnavailableError,
    ShortlistRepository,
)
from backend.app.repositories.firestore import (
    FirestoreConversationRepository,
    FirestoreRateLimitRepository,
    FirestoreShortlistRepository,
)
from backend.app.repositories.memory import (
    MemoryConversationRepository,
    MemoryRateLimitRepository,
    MemoryShortlistRepository,
)


@lru_cache(maxsize=1)
def get_conversation_repository() -> ConversationRepository:
    settings = get_settings()
    if settings.persistence_mode == "memory":
        return MemoryConversationRepository()
    if not settings.firestore_project_id:
        raise RepositoryUnavailableError(
            "FIRESTORE_PROJECT_ID is required for Firestore persistence."
        )
    try:
        client = get_firestore_client(
            settings.firestore_project_id,
            settings.firestore_database_id,
        )
    except FirebaseAdminUnavailable as exc:
        raise RepositoryUnavailableError(
            "Firestore could not be initialized."
        ) from exc
    return FirestoreConversationRepository(client)


@lru_cache(maxsize=1)
def get_shortlist_repository() -> ShortlistRepository:
    settings = get_settings()
    if settings.persistence_mode == "memory":
        return MemoryShortlistRepository()
    if not settings.firestore_project_id:
        raise RepositoryUnavailableError(
            "FIRESTORE_PROJECT_ID is required for Firestore persistence."
        )
    try:
        client = get_firestore_client(
            settings.firestore_project_id,
            settings.firestore_database_id,
        )
    except FirebaseAdminUnavailable as exc:
        raise RepositoryUnavailableError(
            "Firestore could not be initialized."
        ) from exc
    return FirestoreShortlistRepository(client)


@lru_cache(maxsize=1)
def get_rate_limit_repository() -> RateLimitRepository:
    return create_rate_limit_repository(get_settings())


def create_rate_limit_repository(settings: Settings) -> RateLimitRepository:
    if settings.persistence_mode == "memory":
        if settings.app_environment == "production":
            raise RepositoryUnavailableError(
                "Production rate limits require Firestore persistence."
            )
        return MemoryRateLimitRepository()
    if not settings.firestore_project_id:
        raise RepositoryUnavailableError(
            "FIRESTORE_PROJECT_ID is required for Firestore rate limits."
        )
    try:
        client = get_firestore_client(
            settings.firestore_project_id,
            settings.firestore_database_id,
        )
    except FirebaseAdminUnavailable as exc:
        raise RepositoryUnavailableError(
            "Firestore could not be initialized."
        ) from exc
    return FirestoreRateLimitRepository(client)
