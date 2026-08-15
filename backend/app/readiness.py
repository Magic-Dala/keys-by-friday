from __future__ import annotations

import os

from backend.app.config import Settings


def _is_true(value: str | None) -> bool:
    return (value or "").strip().casefold() in {"1", "true", "yes", "on"}


def readiness_report(settings: Settings) -> tuple[bool, dict[str, str]]:
    """Check configuration without calling Gemini or consuming provider quota."""

    checks = {"api": "ok"}
    if settings.agent_mode == "stub":
        checks["agent"] = "stub"
        checks["provider"] = "not_required"
        return True, checks

    using_vertex_ai = _is_true(os.getenv("GOOGLE_GENAI_USE_VERTEXAI"))
    if using_vertex_ai:
        has_model_auth = bool(
            os.getenv("GOOGLE_CLOUD_PROJECT", "").strip()
            and os.getenv("GOOGLE_CLOUD_LOCATION", "").strip()
        )
    else:
        has_model_auth = bool(
            os.getenv("GOOGLE_API_KEY", "").strip()
            or os.getenv("GEMINI_API_KEY", "").strip()
        )
    checks["agent"] = "configured" if has_model_auth else "not_configured"

    provider = os.getenv("LISTING_PROVIDER", "mock").strip().casefold()
    if provider == "mock":
        provider_ready = True
    elif provider == "realtyapi":
        provider_ready = bool(os.getenv("REALTYAPI_API_KEY", "").strip())
    else:
        provider_ready = False
    checks["provider"] = "configured" if provider_ready else "not_configured"

    return has_model_auth and provider_ready, checks
