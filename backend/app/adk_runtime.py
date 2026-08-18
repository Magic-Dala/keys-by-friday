from __future__ import annotations

from typing import Any

from backend.app.config import AdkSessionMode


ADK_APP_NAME = "keys_by_friday_web"


class AdkRuntimeConfigurationError(RuntimeError):
    """The selected ADK session service could not be initialized safely."""


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
