from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from backend.app.auth import AuthenticatedUser, get_current_user
from backend.app.config import Settings, _positive_integer
from backend.app.main import create_app
from backend.app.models.search import SearchResponse
from backend.app.repositories.base import RepositoryUnavailableError
from backend.app.repositories.memory import MemoryRateLimitRepository
from backend.app.services.agent_service import get_agent_service
from backend.app.services.rate_limit_service import (
    AgentRequestRateLimitService,
    get_agent_request_rate_limit_service,
)


class _CountingAgent:
    def __init__(self) -> None:
        self.chat_calls = 0
        self.compare_calls = 0

    async def send_message(
        self,
        message: str,
        conversation_id: str | None = None,
        *,
        user_id: str,
    ) -> SearchResponse:
        self.chat_calls += 1
        return SearchResponse(
            conversationId=conversation_id or "conversation-1",
            message="stub response",
            mode="stub",
        )

    async def compare_listings(
        self,
        listing_ids: list[str],
        conversation_id: str,
        *,
        user_id: str,
    ) -> SearchResponse:
        self.compare_calls += 1
        return SearchResponse(
            conversationId=conversation_id,
            message="stub comparison",
            comparison={
                "schemaVersion": "kbf.canonical-comparison.v1",
                "listingIds": listing_ids,
                "results": [
                    {
                        "listingId": listing_id,
                        "hardConstraintStatus": "unknown",
                        "satisfiesCurrentRequirements": None,
                        "softPreferenceEvidence": [],
                        "tradeoffs": [],
                        "comparisonUnknowns": [],
                        "decisionUnknowns": [],
                        "decisionReady": False,
                        "score": None,
                        "rank": rank,
                    }
                    for rank, listing_id in enumerate(listing_ids, 1)
                ],
            },
            mode="stub",
        )


def _client(
    *,
    provider: str = "anonymous",
    limit: int = 2,
    repository=None,
) -> tuple[TestClient, _CountingAgent]:
    application = create_app(
        Settings(
            agent_mode="stub",
            auth_mode="firebase",
            firebase_project_id="test-project",
            persistence_mode="memory",
            anonymous_search_rate_limit=limit,
            anonymous_search_rate_window_seconds=3600,
            authenticated_search_rate_limit=limit,
            authenticated_search_rate_window_seconds=3600,
        )
    )
    agent = _CountingAgent()
    limiter = AgentRequestRateLimitService(
        repository or MemoryRateLimitRepository(),
        anonymous_limit=limit,
        anonymous_window_seconds=3600,
        authenticated_limit=limit,
        authenticated_window_seconds=3600,
    )
    application.dependency_overrides[get_current_user] = lambda: AuthenticatedUser(
        uid="user-a", sign_in_provider=provider
    )
    application.dependency_overrides[get_agent_service] = lambda: agent
    application.dependency_overrides[
        get_agent_request_rate_limit_service
    ] = lambda: limiter
    return TestClient(application), agent


def test_anonymous_chat_is_limited_before_agent_execution() -> None:
    client, agent = _client(limit=2)

    invalid = client.post("/api/chat", json={"message": "   "})
    first = client.post(
        "/api/chat",
        json={"message": "Find a rental"},
        headers={"Origin": "http://localhost:3000"},
    )
    second = client.post("/api/chat", json={"message": "Add parking"})
    blocked = client.post(
        "/api/chat",
        json={"message": "Add a cat"},
        headers={"Origin": "http://localhost:3000"},
    )

    assert invalid.status_code == 422
    assert first.status_code == 200
    assert first.headers["X-RateLimit-Limit"] == "2"
    assert first.headers["X-RateLimit-Remaining"] == "1"
    assert "X-RateLimit-Remaining" in first.headers["Access-Control-Expose-Headers"]
    assert second.status_code == 200
    assert second.headers["X-RateLimit-Remaining"] == "0"
    assert blocked.status_code == 429
    assert blocked.headers["X-RateLimit-Remaining"] == "0"
    assert int(blocked.headers["Retry-After"]) > 0
    assert "Retry-After" in blocked.headers["Access-Control-Expose-Headers"]
    assert agent.chat_calls == 2


def test_chat_and_compare_share_one_anonymous_cost_bucket() -> None:
    client, agent = _client(limit=1)

    chat = client.post("/api/chat", json={"message": "Find rentals"})
    compare = client.post(
        "/api/compare",
        json={
            "listingIds": ["listing-1", "listing-2"],
            "conversationId": "conversation-1",
        },
    )

    assert chat.status_code == 200
    assert compare.status_code == 429
    assert agent.chat_calls == 1
    assert agent.compare_calls == 0


def test_signed_in_user_has_a_bounded_agent_request_budget() -> None:
    client, agent = _client(provider="google.com", limit=2)

    responses = [
        client.post("/api/chat", json={"message": f"Request {index}"})
        for index in range(3)
    ]

    assert [response.status_code for response in responses] == [200, 200, 429]
    assert responses[0].headers["X-RateLimit-Remaining"] == "1"
    assert responses[1].headers["X-RateLimit-Remaining"] == "0"
    assert agent.chat_calls == 2


def test_anonymous_requests_fail_closed_when_counter_is_unavailable() -> None:
    class FailingRepository:
        async def consume(self, *args, **kwargs):
            raise RepositoryUnavailableError("private Firestore error")

    client, agent = _client(repository=FailingRepository())

    response = client.post("/api/chat", json={"message": "Find rentals"})

    assert response.status_code == 503
    assert response.json() == {
        "detail": "Agent request limits are temporarily unavailable."
    }
    assert agent.chat_calls == 0


def test_rate_limit_repository_initialization_failure_returns_stable_503(
    monkeypatch,
) -> None:
    from backend.app.services import rate_limit_service

    application = create_app(
        Settings(
            agent_mode="stub",
            auth_mode="firebase",
            firebase_project_id="test-project",
            persistence_mode="memory",
        )
    )
    agent = _CountingAgent()
    application.dependency_overrides[get_current_user] = lambda: AuthenticatedUser(
        uid="user-a", sign_in_provider="anonymous"
    )
    application.dependency_overrides[get_agent_service] = lambda: agent

    def fail_to_create_repository(settings):
        raise RepositoryUnavailableError("private setup error")

    monkeypatch.setattr(
        rate_limit_service,
        "create_rate_limit_repository",
        fail_to_create_repository,
    )

    response = TestClient(application).post(
        "/api/chat", json={"message": "Find rentals"}
    )

    assert response.status_code == 503
    assert response.json() == {
        "detail": "Agent request limits are temporarily unavailable."
    }
    assert agent.chat_calls == 0


def test_signed_in_user_fails_closed_when_repository_initialization_fails(
    monkeypatch,
) -> None:
    from backend.app.services import rate_limit_service

    application = create_app(
        Settings(
            agent_mode="stub",
            auth_mode="firebase",
            firebase_project_id="test-project",
            persistence_mode="memory",
        )
    )
    agent = _CountingAgent()
    application.dependency_overrides[get_current_user] = lambda: AuthenticatedUser(
        uid="user-a", sign_in_provider="google.com"
    )
    application.dependency_overrides[get_agent_service] = lambda: agent

    def fail_to_create_repository(settings):
        raise RepositoryUnavailableError("private setup error")

    monkeypatch.setattr(
        rate_limit_service,
        "create_rate_limit_repository",
        fail_to_create_repository,
    )

    response = TestClient(application).post(
        "/api/chat", json={"message": "Find rentals"}
    )

    assert response.status_code == 503
    assert response.json() == {
        "detail": "Agent request limits are temporarily unavailable."
    }
    assert agent.chat_calls == 0


def test_local_disabled_auth_still_bypasses_external_rate_limit_storage() -> None:
    class FailingRepository:
        async def consume(self, *args, **kwargs):
            raise AssertionError("local disabled auth must not touch rate-limit storage")

    client, agent = _client(provider="disabled", limit=1, repository=FailingRepository())
    response = client.post("/api/chat", json={"message": "Local development"})

    assert response.status_code == 200
    assert "X-RateLimit-Limit" not in response.headers
    assert agent.chat_calls == 1


def test_production_memory_rate_limit_configuration_fails_closed() -> None:
    class AgentMustNotRun:
        async def send_message(self, *args, **kwargs):
            raise AssertionError("Agent must not run without distributed rate limits")

        async def compare_listings(self, *args, **kwargs):
            raise AssertionError("Agent must not run without distributed rate limits")

    application = create_app(
        Settings(
            agent_mode="stub",
            app_environment="production",
            auth_mode="firebase",
            firebase_project_id="test-project",
            persistence_mode="memory",
        )
    )
    application.dependency_overrides[get_current_user] = lambda: AuthenticatedUser(
        uid="user-a", sign_in_provider="google.com"
    )
    application.dependency_overrides[get_agent_service] = lambda: AgentMustNotRun()
    client = TestClient(application)

    chat = client.post("/api/chat", json={"message": "Find rentals"})
    compare = client.post(
        "/api/compare",
        json={
            "listingIds": ["listing-1", "listing-2"],
            "conversationId": "conversation-1",
        },
    )

    assert chat.status_code == 503
    assert compare.status_code == 503
    assert chat.json() == {
        "detail": "Agent request limits are temporarily unavailable."
    }
    assert compare.json() == chat.json()



def test_memory_limit_is_atomic_and_resets_after_the_window() -> None:
    repository = MemoryRateLimitRepository()
    start = datetime(2026, 8, 20, tzinfo=timezone.utc)

    async def scenario():
        simultaneous = await asyncio.gather(
            *[
                repository.consume(
                    "user-a", limit=3, window_seconds=60, now=start
                )
                for _ in range(10)
            ]
        )
        after_reset = await repository.consume(
            "user-a",
            limit=3,
            window_seconds=60,
            now=start + timedelta(seconds=61),
        )
        return simultaneous, after_reset

    simultaneous, after_reset = asyncio.run(scenario())

    assert sum(item.allowed for item in simultaneous) == 3
    assert after_reset.allowed is True
    assert after_reset.remaining == 2


def test_rate_limit_configuration_requires_positive_whole_numbers() -> None:
    assert _positive_integer("10", "TEST_LIMIT") == 10
    with pytest.raises(ValueError, match="whole number"):
        _positive_integer("1.5", "TEST_LIMIT")
    with pytest.raises(ValueError, match="greater than zero"):
        _positive_integer("0", "TEST_LIMIT")

    readiness = TestClient(
        create_app(
            Settings(
                agent_mode="stub",
                anonymous_search_rate_limit=0,
            )
        )
    ).get("/ready")
    assert readiness.status_code == 503
    assert readiness.json()["checks"]["anonymous_rate_limit"] == "not_configured"
