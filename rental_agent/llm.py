from __future__ import annotations

import logging

from collections.abc import AsyncGenerator

from google.adk.models import BaseLlm, Gemini
from google.adk.models.llm_request import LlmRequest
from google.adk.models.llm_response import LlmResponse

logger = logging.getLogger(__name__)

AGENT_ROUTINE_MODEL_ORDER: tuple[str, ...] = (
    "gemini-3.5-flash-lite",
    "gemini-3.7-flash",
)
AGENT_REASONING_MODEL = "gemini-3.7-flash"

_FALLBACK_HTTP_CODES = {404, 408, 429, 500, 502, 503, 504}


def _is_user_input_request(llm_request: LlmRequest) -> bool:
    """Identify the pre-tool pass where the agent interprets the user's request."""
    if not llm_request.contents:
        return False

    latest = llm_request.contents[-1]
    if getattr(latest, "role", None) != "user":
        return False

    parts = getattr(latest, "parts", None) or ()
    return not any(getattr(part, "function_response", None) is not None for part in parts)


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
    """Route user-input planning to Gemini 3.7 Flash, then use the fallback chain.

    A fallback happens only if the model call fails before emitting any response
    and the failure is quota/rate-limit/model-unavailable/server-side. Tool and
    listing-provider errors are outside this boundary and are never masked.
    """

    fallback_models: tuple[str, ...] = ()
    search_model: str | None = None

    def _candidates_for(self, llm_request: LlmRequest) -> tuple[str, ...]:
        candidates = (self.model, *self.fallback_models)
        if self.search_model and _is_user_input_request(llm_request):
            candidates = (self.search_model, *candidates)
        return tuple(dict.fromkeys(candidates))

    async def generate_content_async(
        self, llm_request: LlmRequest, stream: bool = False
    ) -> AsyncGenerator[LlmResponse, None]:
        candidates = self._candidates_for(llm_request)

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
    """Build the Agent-owned Gemini routing policy."""
    return OrderedGeminiFallback(
        model=AGENT_ROUTINE_MODEL_ORDER[0],
        fallback_models=AGENT_ROUTINE_MODEL_ORDER[1:],
        search_model=AGENT_REASONING_MODEL,
    )
