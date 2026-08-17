from __future__ import annotations

from contextvars import ContextVar
from datetime import datetime, timezone
import json
import logging
import re
import time
from typing import Any
from uuid import uuid4

from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse


_REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9._-]{1,128}$")
_request_id: ContextVar[str | None] = ContextVar("request_id", default=None)


class RequestContextFilter(logging.Filter):
    """Attach the current HTTP request ID to application log records."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = _request_id.get()
        return True


class JsonFormatter(logging.Formatter):
    """Write one JSON object per line so Cloud Logging can parse each log."""

    _EXTRA_FIELDS = (
        "request_id",
        "method",
        "path",
        "status_code",
        "duration_ms",
        "conversation_id",
        "mode",
        "listing_count",
        "tool",
        "models",
        "provider",
        "provider_status",
        "provider_latency_ms",
        "provider_search_performed",
        "sources",
        "source_statuses",
        "failed_sources",
        "data_source",
        "cache_status",
        "logging.googleapis.com/trace",
    )

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "severity": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for field in self._EXTRA_FIELDS:
            value = getattr(record, field, None)
            if value is not None:
                payload[field] = value
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


def configure_logging(log_level: str) -> None:
    """Configure only this application's logger; leave Uvicorn's logger alone."""

    app_logger = logging.getLogger("keys_by_friday")
    app_logger.handlers.clear()
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    handler.addFilter(RequestContextFilter())
    app_logger.addHandler(handler)
    app_logger.setLevel(log_level)
    app_logger.propagate = False


def _safe_request_id(value: str | None) -> str:
    if value and _REQUEST_ID_PATTERN.fullmatch(value):
        return value
    return str(uuid4())


def _cloud_trace(request: Request, google_cloud_project: str | None) -> str | None:
    trace_header = request.headers.get("X-Cloud-Trace-Context")
    if not trace_header or not google_cloud_project:
        return None
    trace_id = trace_header.split("/", 1)[0].strip()
    if not trace_id:
        return None
    return f"projects/{google_cloud_project}/traces/{trace_id}"


def install_request_logging(
    app: FastAPI, *, google_cloud_project: str | None = None
) -> None:
    logger = logging.getLogger("keys_by_friday.http")

    @app.middleware("http")
    async def log_request(request: Request, call_next) -> Response:
        request_id = _safe_request_id(request.headers.get("X-Request-ID"))
        context_token = _request_id.set(request_id)
        started = time.perf_counter()
        response: Response | None = None

        log_fields: dict[str, object] = {
            "method": request.method,
            "path": request.url.path,
        }
        cloud_trace = _cloud_trace(request, google_cloud_project)
        if cloud_trace:
            log_fields["logging.googleapis.com/trace"] = cloud_trace

        try:
            response = await call_next(request)
            return response
        except Exception:
            log_fields["status_code"] = 500
            log_fields["duration_ms"] = round(
                (time.perf_counter() - started) * 1000, 2
            )
            logger.exception("request failed", extra=log_fields)
            response = JSONResponse(
                status_code=500,
                content={"detail": "Internal server error."},
            )
            return response
        finally:
            if response is not None:
                response.headers["X-Request-ID"] = request_id
                log_fields["status_code"] = response.status_code
                log_fields["duration_ms"] = round(
                    (time.perf_counter() - started) * 1000, 2
                )
                logger.info("request completed", extra=log_fields)
            _request_id.reset(context_token)
