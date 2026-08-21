from __future__ import annotations

import math
import os
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Literal, cast

from dotenv import load_dotenv

AgentMode = Literal["adk", "stub"]
AppEnvironment = Literal["local", "test", "production"]
AuthMode = Literal["disabled", "firebase"]
PersistenceMode = Literal["memory", "firestore"]
AdkSessionMode = Literal["memory", "database"]

_LOG_LEVELS = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}


@dataclass(frozen=True, slots=True)
class Settings:
    agent_mode: AgentMode = "adk"
    frontend_origin: str = "http://localhost:3000"
    app_environment: AppEnvironment = "local"
    agent_timeout_seconds: float = 120.0
    log_level: str = "INFO"
    google_cloud_project: str | None = None
    auth_mode: AuthMode = "disabled"
    firebase_project_id: str | None = None
    persistence_mode: PersistenceMode = "memory"
    firestore_project_id: str | None = None
    firestore_database_id: str = "(default)"
    adk_session_mode: AdkSessionMode = "memory"
    adk_session_database_url: str | None = field(default=None, repr=False)
    anonymous_search_rate_limit: int = 10
    anonymous_search_rate_window_seconds: int = 3600


def _agent_mode(value: str) -> AgentMode:
    normalized = value.strip().lower()
    if normalized not in {"adk", "stub"}:
        raise ValueError("AGENT_MODE must be 'adk' or 'stub'.")
    return cast(AgentMode, normalized)


def _app_environment(value: str) -> AppEnvironment:
    normalized = value.strip().lower()
    if normalized not in {"local", "test", "production"}:
        raise ValueError("APP_ENV must be 'local', 'test', or 'production'.")
    return cast(AppEnvironment, normalized)


def _auth_mode(value: str) -> AuthMode:
    normalized = value.strip().lower()
    if normalized not in {"disabled", "firebase"}:
        raise ValueError("AUTH_MODE must be 'disabled' or 'firebase'.")
    return cast(AuthMode, normalized)


def _persistence_mode(value: str) -> PersistenceMode:
    normalized = value.strip().lower()
    if normalized not in {"memory", "firestore"}:
        raise ValueError("PERSISTENCE_MODE must be 'memory' or 'firestore'.")
    return cast(PersistenceMode, normalized)


def _adk_session_mode(value: str) -> AdkSessionMode:
    normalized = value.strip().lower()
    if normalized not in {"memory", "database"}:
        raise ValueError("ADK_SESSION_MODE must be 'memory' or 'database'.")
    return cast(AdkSessionMode, normalized)


def _positive_seconds(value: str) -> float:
    try:
        seconds = float(value)
    except ValueError as exc:
        raise ValueError("AGENT_TIMEOUT_SECONDS must be a number.") from exc
    if not math.isfinite(seconds) or seconds <= 0:
        raise ValueError(
            "AGENT_TIMEOUT_SECONDS must be a finite number greater than zero."
        )
    return seconds


def _positive_integer(value: str, variable_name: str) -> int:
    try:
        number = int(value)
    except ValueError as exc:
        raise ValueError(f"{variable_name} must be a whole number.") from exc
    if number <= 0:
        raise ValueError(f"{variable_name} must be greater than zero.")
    return number


def _log_level(value: str) -> str:
    normalized = value.strip().upper()
    if normalized not in _LOG_LEVELS:
        raise ValueError(
            "LOG_LEVEL must be DEBUG, INFO, WARNING, ERROR, or CRITICAL."
        )
    return normalized


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    load_dotenv()
    google_cloud_project = os.getenv("GOOGLE_CLOUD_PROJECT", "").strip() or None
    firebase_project_id = (
        os.getenv("FIREBASE_PROJECT_ID", "").strip()
        or google_cloud_project
    )
    return Settings(
        agent_mode=_agent_mode(os.getenv("AGENT_MODE", "adk")),
        frontend_origin=os.getenv(
            "FRONTEND_ORIGIN", "http://localhost:3000"
        ).strip()
        or "http://localhost:3000",
        app_environment=_app_environment(os.getenv("APP_ENV", "local")),
        agent_timeout_seconds=_positive_seconds(
            os.getenv("AGENT_TIMEOUT_SECONDS", "120")
        ),
        log_level=_log_level(os.getenv("LOG_LEVEL", "INFO")),
        google_cloud_project=google_cloud_project,
        auth_mode=_auth_mode(os.getenv("AUTH_MODE", "disabled")),
        firebase_project_id=firebase_project_id,
        persistence_mode=_persistence_mode(
            os.getenv("PERSISTENCE_MODE", "memory")
        ),
        firestore_project_id=(
            os.getenv("FIRESTORE_PROJECT_ID", "").strip()
            or firebase_project_id
        ),
        firestore_database_id=(
            os.getenv("FIRESTORE_DATABASE_ID", "(default)").strip()
            or "(default)"
        ),
        adk_session_mode=_adk_session_mode(
            os.getenv("ADK_SESSION_MODE", "memory")
        ),
        adk_session_database_url=(
            os.getenv("ADK_SESSION_DATABASE_URL", "").strip() or None
        ),
        anonymous_search_rate_limit=_positive_integer(
            os.getenv("ANONYMOUS_SEARCH_RATE_LIMIT", "10"),
            "ANONYMOUS_SEARCH_RATE_LIMIT",
        ),
        anonymous_search_rate_window_seconds=_positive_integer(
            os.getenv("ANONYMOUS_SEARCH_RATE_WINDOW_SECONDS", "3600"),
            "ANONYMOUS_SEARCH_RATE_WINDOW_SECONDS",
        ),
    )
