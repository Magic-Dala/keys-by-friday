from __future__ import annotations

import logging
import os
from collections.abc import AsyncGenerator

from google.adk.models import BaseLlm, Gemini
from google.adk.models.llm_request import LlmRequest
from google.adk.models.llm_response import LlmResponse

logger = logging.getLogger(__name__)

DEFAULT_MODEL_ORDER: tuple[str, ...] = (
    "gemini-3.5-flash-lite",
    "gemini-3.1-flash-lite",
    "gemini-3.6-flash",
    "gemini-3.5-flash",
    "gemini-2.5-flash",
)

_FALLBACK_HTTP_CODES = {404, 408, 429, 500, 502, 503, 504}


def configured_model_order() -> tuple[str, ...]:
    """Return the ordered Gemini fallback chain from GEMINI_MODELS."""
    raw = os.getenv("GEMINI_MODELS", "")
    values = [item.strip() for item in raw.split(",") if item.strip()]
    if not values:
        return DEFAULT_MODEL_ORDER

    # Preserve caller order while removing accidental duplicates.
    return tuple(dict.fromkeys(values))


def _http_error_code(exc: BaseException) -> int | None:
    """Extract an HTTP-like status code from Google SDK / ADK wrapped errors."""
    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        for attr in ("code", "status_code"):
            value = getattr(current, attr, None)
            if isinstance(value, int):
                return value
        response = getattr(current, "response", None)
        value = getattr(response, "status_code", None)
        if isinstance(value, int):
            return value
        current = current.__cause__ or current.__context__
    return None


def _is_model_fallback_error(exc: BaseException) -> bool:
    """Only fail over for model availability/quota/service failures."""
    return _http_error_code(exc) in _FALLBACK_HTTP_CODES


class OrderedGeminiFallback(BaseLlm):
    """Try Gemini models in order without creating another Agent.

    A fallback happens only if the model call fails before emitting any response
    and the failure is quota/rate-limit/model-unavailable/server-side. Tool and
    listing-provider errors are outside this boundary and are never masked.
    """

    fallback_models: tuple[str, ...] = ()

    async def generate_content_async(
        self, llm_request: LlmRequest, stream: bool = False
    ) -> AsyncGenerator[LlmResponse, None]:
        candidates = (self.model, *self.fallback_models)

        for index, model_name in enumerate(candidates):
            request = llm_request.model_copy(deep=True)
            request.model = model_name
            emitted = False

            try:
                delegate = Gemini(model=model_name)
                async for response in delegate.generate_content_async(request, stream=stream):
                    emitted = True
                    yield response
                return
            except Exception as exc:
                is_last = index == len(candidates) - 1
                if emitted or is_last or not _is_model_fallback_error(exc):
                    raise

                logger.warning(
                    "Gemini model %s unavailable (%s); falling back to %s",
                    model_name,
                    _http_error_code(exc),
                    candidates[index + 1],
                )


def build_ordered_gemini() -> OrderedGeminiFallback:
    models = configured_model_order()
    return OrderedGeminiFallback(model=models[0], fallback_models=models[1:])
