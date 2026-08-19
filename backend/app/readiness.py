from __future__ import annotations

import os

from backend.app.config import Settings


def _is_true(value: str | None) -> bool:
    return (value or "").strip().casefold() in {"1", "true", "yes", "on"}


def readiness_report(
    settings: Settings,
    *,
    adk_session_connected: bool | None = None,
) -> tuple[bool, dict[str, str]]:
    """Check configuration and supplied ADK database connectivity evidence."""

    checks = {"api": "ok"}
    is_production = settings.app_environment == "production"

    if settings.auth_mode == "disabled":
        auth_ready = not is_production
        checks["auth"] = "disabled" if auth_ready else "not_configured"
    else:
        auth_ready = bool(settings.firebase_project_id)
        checks["auth"] = "configured" if auth_ready else "not_configured"

    if settings.persistence_mode == "memory":
        persistence_ready = not is_production
        checks["persistence"] = (
            "memory" if persistence_ready else "memory_not_allowed"
        )
    else:
        persistence_ready = bool(settings.firestore_project_id)
        checks["persistence"] = (
            "configured" if persistence_ready else "not_configured"
        )

    if settings.adk_session_mode == "memory":
        session_ready = not is_production
        checks["adk_session"] = (
            "memory" if session_ready else "memory_not_allowed"
        )
    elif not settings.adk_session_database_url:
        session_ready = False
        checks["adk_session"] = "not_configured"
    elif is_production and settings.adk_session_database_url.casefold().startswith(
        "sqlite"
    ):
        session_ready = False
        checks["adk_session"] = "sqlite_not_allowed"
    elif adk_session_connected is True:
        session_ready = True
        checks["adk_session"] = "connected"
    else:
        session_ready = False
        checks["adk_session"] = "unavailable"

    if settings.agent_mode == "stub" and not is_production:
        checks["agent"] = "stub"
        checks["provider"] = "not_required"
        return auth_ready and persistence_ready and session_ready, checks

    if settings.agent_mode == "stub":
        agent_ready = False
        checks["agent"] = "stub_not_allowed"
    else:
        using_vertex_ai = _is_true(os.getenv("GOOGLE_GENAI_USE_VERTEXAI"))
        if using_vertex_ai:
            agent_ready = bool(
                os.getenv("GOOGLE_CLOUD_PROJECT", "").strip()
                and os.getenv("GOOGLE_CLOUD_LOCATION", "").strip()
            )
        else:
            agent_ready = bool(
                os.getenv("GOOGLE_API_KEY", "").strip()
                or os.getenv("GEMINI_API_KEY", "").strip()
            )
        checks["agent"] = "configured" if agent_ready else "not_configured"

    provider = os.getenv("LISTING_PROVIDER", "mock").strip().casefold()
    if provider == "mock":
        provider_ready = not is_production
        checks["provider"] = "mock" if provider_ready else "mock_not_allowed"
    elif provider == "realtyapi":
        provider_ready = bool(os.getenv("REALTYAPI_API_KEY", "").strip())
        checks["provider"] = (
            "configured" if provider_ready else "not_configured"
        )
    else:
        provider_ready = False
        checks["provider"] = "unsupported"

    return (
        auth_ready
        and persistence_ready
        and session_ready
        and agent_ready
        and provider_ready,
        checks,
    )
