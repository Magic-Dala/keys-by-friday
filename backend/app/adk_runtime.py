from __future__ import annotations

import asyncio
from typing import Any

from backend.app.config import AdkSessionMode


ADK_APP_NAME = "keys_by_friday_web"
_READINESS_USER_ID = "__readiness__"
_READINESS_SESSION_ID = "__database_connectivity__"
_READINESS_TIMEOUT_SECONDS = 5.0


class AdkRuntimeConfigurationError(RuntimeError):
    """The selected ADK session service could not be initialized safely."""


class AdkSessionReadinessProbe:
    """Verify that the configured ADK database can serve a session read."""

    def __init__(
        self,
        database_url: str,
        *,
        timeout_seconds: float = _READINESS_TIMEOUT_SECONDS,
        session_service: Any | None = None,
    ) -> None:
        self._timeout_seconds = timeout_seconds
        if session_service is not None:
            self._session_service = session_service
            return

        try:
            self._session_service = create_adk_session_service(
                "database", database_url
            )
        except AdkRuntimeConfigurationError:
            self._session_service = None

    async def check(self) -> bool:
        """Return true only after the official service completes a DB read."""

        if self._session_service is None:
            return False
        try:
            await asyncio.wait_for(
                self._session_service.get_session(
                    app_name=ADK_APP_NAME,
                    user_id=_READINESS_USER_ID,
                    session_id=_READINESS_SESSION_ID,
                ),
                timeout=self._timeout_seconds,
            )
        except Exception:
            # Database errors may contain credentials or connection details.
            # Keep the public readiness result deliberately generic.
            return False
        return True

    async def close(self) -> None:
        """Release the probe's connection pool during application shutdown."""

        if self._session_service is None:
            return
        try:
            await self._session_service.close()
        except Exception:
            # Shutdown cleanup must not expose a database URL or prevent exit.
            pass


def create_adk_session_service(
    mode: AdkSessionMode,
    database_url: str | None = None,
):
    """Create the configured official ADK SessionService implementation."""

    if mode == "memory":
        from google.adk.sessions import InMemorySessionService

        return InMemorySessionService()

    if mode != "database":
        raise AdkRuntimeConfigurationError("Unsupported ADK session mode.")
    if not database_url:
        raise AdkRuntimeConfigurationError(
            "The database ADK session mode requires a database URL."
        )

    try:
        from google.adk.sessions import DatabaseSessionService

        return DatabaseSessionService(db_url=database_url)
    except Exception:
        # Database URLs commonly contain passwords. Do not include the original
        # exception or URL in this stable error because it may reach logs.
        raise AdkRuntimeConfigurationError(
            "The ADK database session service could not be initialized."
        ) from None


def create_adk_runner(
    *,
    mode: AdkSessionMode,
    database_url: str | None = None,
    agent: Any | None = None,
):
    """Create an ADK Runner whose session storage is selected by configuration."""

    from google.adk.runners import Runner

    if agent is None:
        from rental_agent.agent import root_agent

        agent = root_agent

    return Runner(
        agent=agent,
        app_name=ADK_APP_NAME,
        session_service=create_adk_session_service(mode, database_url),
    )
