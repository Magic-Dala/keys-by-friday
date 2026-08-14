from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from typing import Literal, cast

from dotenv import load_dotenv

AgentMode = Literal["adk", "stub"]


@dataclass(frozen=True, slots=True)
class Settings:
    agent_mode: AgentMode
    frontend_origin: str


def _agent_mode(value: str) -> AgentMode:
    normalized = value.strip().lower()
    if normalized not in {"adk", "stub"}:
        raise ValueError("AGENT_MODE must be 'adk' or 'stub'.")
    return cast(AgentMode, normalized)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    load_dotenv()
    return Settings(
        agent_mode=_agent_mode(os.getenv("AGENT_MODE", "adk")),
        frontend_origin=os.getenv(
            "FRONTEND_ORIGIN", "http://localhost:3000"
        ).strip()
        or "http://localhost:3000",
    )
