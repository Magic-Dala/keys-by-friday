from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import AsyncIterator


@dataclass(slots=True)
class _TurnLock:
    lock: asyncio.Lock
    users: int = 0


class ConversationTurnCoordinator:
    """Run only one complete Agent turn per user conversation at a time."""

    def __init__(self) -> None:
        self._guard = asyncio.Lock()
        self._locks: dict[tuple[str, str], _TurnLock] = {}

    @asynccontextmanager
    async def hold(
        self, user_id: str, conversation_id: str
    ) -> AsyncIterator[None]:
        key = (user_id, conversation_id)
        async with self._guard:
            entry = self._locks.get(key)
            if entry is None:
                entry = _TurnLock(lock=asyncio.Lock())
                self._locks[key] = entry
            entry.users += 1

        try:
            async with entry.lock:
                yield
        finally:
            async with self._guard:
                entry.users -= 1
                if entry.users == 0:
                    self._locks.pop(key, None)
