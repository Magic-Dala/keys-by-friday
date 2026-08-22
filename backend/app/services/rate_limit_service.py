from __future__ import annotations

from datetime import datetime, timezone
from typing import Callable

from fastapi import Request

from backend.app.auth import AuthenticatedUser
from backend.app.config import Settings, get_settings
from backend.app.repositories.base import (
    RateLimitRepository,
    RateLimitUsage,
    RepositoryError,
)
from backend.app.repositories.dependencies import create_rate_limit_repository


class RateLimitStorageUnavailableError(RuntimeError):
    """The distributed counter could not be checked safely."""


class AnonymousSearchRateLimitService:
    def __init__(
        self,
        repository: RateLimitRepository | None = None,
        *,
        repository_factory: Callable[[], RateLimitRepository] | None = None,
        limit: int,
        window_seconds: int,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if limit <= 0 or window_seconds <= 0:
            raise ValueError("Rate-limit values must be greater than zero.")
        if repository is None and repository_factory is None:
            raise ValueError(
                "A rate-limit repository or repository factory is required."
            )
        self._repository = repository
        self._repository_factory = repository_factory
        self.limit = limit
        self.window_seconds = window_seconds
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    async def consume_if_anonymous(
        self, user: AuthenticatedUser
    ) -> RateLimitUsage | None:
        if (user.sign_in_provider or "").casefold() != "anonymous":
            return None
        try:
            repository = self._repository
            if repository is None:
                repository_factory = self._repository_factory
                if repository_factory is None:
                    raise RepositoryError(
                        "Rate-limit repository factory is unavailable."
                    )
                repository = repository_factory()
                self._repository = repository
            return await repository.consume(
                user.uid,
                limit=self.limit,
                window_seconds=self.window_seconds,
                now=self._clock(),
            )
        except RepositoryError as exc:
            # Anonymous traffic fails closed so a Firestore outage cannot turn
            # into unlimited Gemini/RealtyAPI spend.
            raise RateLimitStorageUnavailableError(
                "Anonymous rate-limit storage is unavailable."
            ) from exc


def _settings_for_request(request: Request) -> Settings:
    settings = getattr(request.app.state, "settings", None)
    return settings if isinstance(settings, Settings) else get_settings()


async def get_anonymous_search_rate_limit_service(
    request: Request,
) -> AnonymousSearchRateLimitService:
    existing = getattr(request.app.state, "anonymous_rate_limit_service", None)
    if isinstance(existing, AnonymousSearchRateLimitService):
        return existing

    settings = _settings_for_request(request)
    service = AnonymousSearchRateLimitService(
        repository_factory=lambda: create_rate_limit_repository(settings),
        limit=settings.anonymous_search_rate_limit,
        window_seconds=settings.anonymous_search_rate_window_seconds,
    )
    request.app.state.anonymous_rate_limit_service = service
    return service
