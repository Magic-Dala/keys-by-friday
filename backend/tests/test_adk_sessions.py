from __future__ import annotations

import asyncio

from google.adk.agents import BaseAgent
from google.adk.agents.invocation_context import InvocationContext
from google.adk.events import Event, EventActions
from google.genai import types

from backend.app.adk_runtime import create_adk_runner, create_adk_session_service
from backend.app.models.search import SearchResponse
from backend.app.repositories.memory import MemoryConversationRepository
from backend.app.services.agent_service import AgentService


class _RestartTestAgent(BaseAgent):
    """Deterministic Agent used to test ADK storage without calling Gemini."""

    async def _run_async_impl(self, ctx: InvocationContext):
        requirements = dict(ctx.session.state.get("requirements", {}))
        text = "".join(
            part.text or ""
            for part in (ctx.user_content.parts if ctx.user_content else [])
        )
        if "Mountain View" in text:
            requirements.update(city="Mountain View", max_rent=4000)
        if "parking" in text.casefold():
            requirements["parking_required"] = True

        answer = (
            f"city={requirements.get('city')}; "
            f"max_rent={requirements.get('max_rent')}; "
            f"parking={requirements.get('parking_required', False)}"
        )
        yield Event(
            author=self.name,
            content=types.Content(
                role="model", parts=[types.Part(text=answer)]
            ),
            actions=EventActions(
                state_delta={"requirements": requirements}
            ),
        )


def _database_runner(database_url: str):
    return create_adk_runner(
        mode="database",
        database_url=database_url,
        agent=_RestartTestAgent(name="restart_test_agent"),
    )


def test_memory_session_service_is_the_local_default() -> None:
    service = create_adk_session_service("memory")

    assert type(service).__name__ == "InMemorySessionService"


def test_database_session_survives_backend_service_restart(tmp_path) -> None:
    database_url = f"sqlite+aiosqlite:///{tmp_path / 'adk-sessions.db'}"
    conversations = MemoryConversationRepository()

    async def scenario():
        first_runner = _database_runner(database_url)
        first_backend = AgentService(
            mode="adk",
            conversation_repository=conversations,
            session_mode="database",
            session_database_url=database_url,
            runner=first_runner,
        )
        first = await first_backend.send_message(
            "Search Mountain View under $4,000.",
            "restart-conversation",
            user_id="user-a",
        )
        await first_runner.session_service.close()

        # A new runner and AgentService represent a restarted backend process.
        second_runner = _database_runner(database_url)
        second_backend = AgentService(
            mode="adk",
            conversation_repository=conversations,
            session_mode="database",
            session_database_url=database_url,
            runner=second_runner,
        )
        second = await second_backend.send_message(
            "I also need parking.",
            "restart-conversation",
            user_id="user-a",
        )
        restored_session = await second_runner.session_service.get_session(
            app_name=second_runner.app_name,
            user_id="user-a",
            session_id="restart-conversation",
        )
        await second_runner.session_service.close()
        return first, second, restored_session

    first, second, restored_session = asyncio.run(scenario())

    assert "city=Mountain View" in first.message
    assert "max_rent=4000" in second.message
    assert "parking=True" in second.message
    assert restored_session is not None
    assert restored_session.state["requirements"] == {
        "city": "Mountain View",
        "max_rent": 4000,
        "parking_required": True,
    }


def test_simultaneous_turns_for_same_conversation_are_serialized() -> None:
    conversations = MemoryConversationRepository()
    service = AgentService(mode="adk", conversation_repository=conversations)
    first_started = asyncio.Event()
    release_first = asyncio.Event()
    active = 0
    maximum_active = 0
    execution_order: list[str] = []

    async def controlled_agent(
        message: str, conversation_id: str, user_id: str
    ) -> SearchResponse:
        nonlocal active, maximum_active
        active += 1
        maximum_active = max(maximum_active, active)
        execution_order.append(message)
        if message == "first":
            first_started.set()
            await release_first.wait()
        active -= 1
        return SearchResponse(
            conversationId=conversation_id,
            message=message,
            listings=[],
            mode="adk",
        )

    service._send_adk_message = controlled_agent  # type: ignore[method-assign]

    async def scenario():
        first = asyncio.create_task(
            service.send_message(
                "first", "shared-conversation", user_id="user-a"
            )
        )
        await first_started.wait()
        second = asyncio.create_task(
            service.send_message(
                "second", "shared-conversation", user_id="user-a"
            )
        )
        await asyncio.sleep(0)
        release_first.set()
        await asyncio.gather(first, second)
        return await conversations.get_for_user(
            "shared-conversation", "user-a"
        )

    metadata = asyncio.run(scenario())

    assert maximum_active == 1
    assert execution_order == ["first", "second"]
    assert metadata.turn_count == 2
