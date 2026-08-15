from __future__ import annotations

import asyncio
import json
import logging

import pytest
from fastapi.testclient import TestClient

from backend.app.config import (
    Settings,
    _app_environment,
    _log_level,
    _positive_seconds,
)
from backend.app.main import create_app
from backend.app.observability import JsonFormatter
from backend.app.services.agent_service import AgentService, AgentServiceError


def test_health_stays_small_and_request_id_is_added() -> None:
    client = TestClient(create_app(Settings(agent_mode="stub")))

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert response.headers["X-Request-ID"]


def test_valid_caller_request_id_is_preserved() -> None:
    client = TestClient(create_app(Settings(agent_mode="stub")))

    response = client.get("/health", headers={"X-Request-ID": "mac-test-123"})

    assert response.headers["X-Request-ID"] == "mac-test-123"


def test_invalid_caller_request_id_is_replaced() -> None:
    client = TestClient(create_app(Settings(agent_mode="stub")))

    response = client.get("/health", headers={"X-Request-ID": "not valid!"})

    assert response.headers["X-Request-ID"] != "not valid!"


def test_readiness_is_ready_in_stub_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("REALTYAPI_API_KEY", raising=False)
    client = TestClient(create_app(Settings(agent_mode="stub")))

    response = client.get("/ready")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ready",
        "checks": {
            "api": "ok",
            "agent": "stub",
            "provider": "not_required",
        },
    }


def test_readiness_reports_missing_adk_configuration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GOOGLE_GENAI_USE_VERTEXAI", "FALSE")
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setenv("LISTING_PROVIDER", "realtyapi")
    monkeypatch.delenv("REALTYAPI_API_KEY", raising=False)
    client = TestClient(create_app(Settings(agent_mode="adk")))

    response = client.get("/ready")

    assert response.status_code == 503
    assert response.json()["status"] == "not_ready"
    assert response.json()["checks"]["agent"] == "not_configured"
    assert response.json()["checks"]["provider"] == "not_configured"


def test_readiness_accepts_configured_adk_and_realtyapi(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GOOGLE_GENAI_USE_VERTEXAI", "FALSE")
    monkeypatch.setenv("GOOGLE_API_KEY", "test-google-key")
    monkeypatch.setenv("LISTING_PROVIDER", "realtyapi")
    monkeypatch.setenv("REALTYAPI_API_KEY", "test-realty-key")
    client = TestClient(create_app(Settings(agent_mode="adk")))

    response = client.get("/ready")

    assert response.status_code == 200
    assert response.json()["status"] == "ready"
    assert response.json()["checks"]["agent"] == "configured"
    assert response.json()["checks"]["provider"] == "configured"


def test_agent_timeout_becomes_stable_service_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = AgentService(mode="adk", timeout_seconds=0.001)

    async def slow_agent(message: str, conversation_id: str):
        await asyncio.sleep(0.05)

    monkeypatch.setattr(service, "_send_adk_message", slow_agent)

    with pytest.raises(AgentServiceError, match="timed out"):
        asyncio.run(service.send_message("Find a rental"))


def test_agent_service_rejects_non_positive_timeout() -> None:
    with pytest.raises(ValueError, match="greater than zero"):
        AgentService(mode="stub", timeout_seconds=0)


def test_json_formatter_produces_cloud_logging_friendly_fields() -> None:
    record = logging.LogRecord(
        name="keys_by_friday.test",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="request completed",
        args=(),
        exc_info=None,
    )
    record.request_id = "test-request"
    record.status_code = 200

    payload = json.loads(JsonFormatter().format(record))

    assert payload["severity"] == "INFO"
    assert payload["message"] == "request completed"
    assert payload["request_id"] == "test-request"
    assert payload["status_code"] == 200


@pytest.mark.parametrize("value", ["0", "-1", "not-a-number"])
def test_agent_timeout_configuration_must_be_positive(value: str) -> None:
    with pytest.raises(ValueError, match="AGENT_TIMEOUT_SECONDS"):
        _positive_seconds(value)


def test_environment_and_log_level_configuration_are_validated() -> None:
    assert _app_environment(" Production ") == "production"
    assert _log_level(" warning ") == "WARNING"

    with pytest.raises(ValueError, match="APP_ENV"):
        _app_environment("demo")
    with pytest.raises(ValueError, match="LOG_LEVEL"):
        _log_level("verbose")
