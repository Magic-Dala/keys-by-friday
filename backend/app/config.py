from __future__ import annotations

import math
import os
from dataclasses import dataclass
from functools import lru_cache
from typing import Literal, cast

from dotenv import load_dotenv

AgentMode = Literal["adk", "stub"]
AppEnvironment = Literal["local", "test", "production"]

_LOG_LEVELS = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}


@dataclass(frozen=True, slots=True)
class Settings:
    agent_mode: AgentMode = "adk"
    frontend_origin: str = "http://localhost:3000"
    app_environment: AppEnvironment = "local"
    agent_timeout_seconds: float = 120.0
    log_level: str = "INFO"
    google_cloud_project: str | None = None


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
        google_cloud_project=os.getenv("GOOGLE_CLOUD_PROJECT", "").strip() or None,
    )
