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
    RepositoryUnavailableError,
)
from backend.app.repositories.dependencies import create_rate_limit_repository


class RateLimitStorageUnavailableError(RuntimeError):
    """The distributed counter could not be checked safely."""


class AgentRequestRateLimitService:
    def __init__(
        self,
        repository: RateLimitRepository | None = None,
        *,
        repository_factory: Callable[[], RateLimitRepository] | None = None,
        anonymous_limit: int,
        anonymous_window_seconds: int,
        authenticated_limit: int,
        authenticated_window_seconds: int,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        values = (
            anonymous_limit,
            anonymous_window_seconds,
            authenticated_limit,
            authenticated_window_seconds,
        )
        if any(value <= 0 for value in values):
            raise ValueError("Rate-limit values must be greater than zero.")
        if repository is None and repository_factory is None:
            raise ValueError(
                "A rate-limit repository or repository factory is required."
            )
        self._repository = repository
        self._repository_factory = repository_factory
        self.anonymous_limit = anonymous_limit
        self.anonymous_window_seconds = anonymous_window_seconds
        self.authenticated_limit = authenticated_limit
        self.authenticated_window_seconds = authenticated_window_seconds
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    def _policy(self, user: AuthenticatedUser) -> tuple[str, int, int] | None:
        provider = (user.sign_in_provider or "").casefold()
        # AUTH_MODE=disabled exists only for local development/tests. Production
        # authentication already fails closed before reaching this service.
        if provider == "disabled":
            return None
        if provider == "anonymous":
            return (
                "anonymous",
                self.anonymous_limit,
                self.anonymous_window_seconds,
            )
        return (
            "authenticated",
            self.authenticated_limit,
            self.authenticated_window_seconds,
        )

    async def consume(self, user: AuthenticatedUser) -> RateLimitUsage | None:
        policy = self._policy(user)
        if policy is None:
            return None
        bucket, limit, window_seconds = policy
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
                f"{bucket}:{user.uid}",
                limit=limit,
                window_seconds=window_seconds,
                now=self._clock(),
            )
        except RepositoryError as exc:
            raise RateLimitStorageUnavailableError(
                "Agent rate-limit storage is unavailable."
            ) from exc


def _settings_for_request(request: Request) -> Settings:
    settings = getattr(request.app.state, "settings", None)
    return settings if isinstance(settings, Settings) else get_settings()


def _repository_factory(settings: Settings) -> RateLimitRepository:
    if (
        settings.app_environment == "production"
        and settings.persistence_mode != "firestore"
    ):
        raise RepositoryUnavailableError(
            "Production Agent rate limits require distributed Firestore storage."
        )
    return create_rate_limit_repository(settings)


async def get_agent_request_rate_limit_service(
    request: Request,
) -> AgentRequestRateLimitService:
    existing = getattr(request.app.state, "agent_rate_limit_service", None)
    if isinstance(existing, AgentRequestRateLimitService):
        return existing

    settings = _settings_for_request(request)
    service = AgentRequestRateLimitService(
        repository_factory=lambda: _repository_factory(settings),
        anonymous_limit=settings.anonymous_search_rate_limit,
        anonymous_window_seconds=settings.anonymous_search_rate_window_seconds,
        authenticated_limit=settings.authenticated_search_rate_limit,
        authenticated_window_seconds=settings.authenticated_search_rate_window_seconds,
    )
    request.app.state.agent_rate_limit_service = service
    return service
