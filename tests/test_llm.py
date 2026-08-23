import asyncio

import pytest

import rental_agent.llm as llm_module
from rental_agent.llm import (
    AGENT_ROUTINE_MODEL_ORDER,
    AGENT_REASONING_MODEL,
    OrderedGeminiFallback,
    build_ordered_gemini,
)


class _FakePart:
    def __init__(self, *, function_response=None):
        self.function_response = function_response


class _FakeContent:
    def __init__(self, role: str, parts=None):
        self.role = role
        self.parts = parts or [_FakePart()]


class _FakeRequest:
    def __init__(self, model: str | None = None, contents=None):
        self.model = model
        self.contents = contents or []

    def model_copy(self, deep: bool = False):
        return _FakeRequest(self.model, list(self.contents))


class _ModelError(RuntimeError):
    def __init__(self, code: int):
        super().__init__(f"model error {code}")
        self.code = code


def test_agent_model_policy_is_internal_and_ignores_env(monkeypatch):
    monkeypatch.setenv("GEMINI_SEARCH_MODEL", "user-selected-search-model")
    monkeypatch.setenv("GEMINI_MODELS", "user-selected-model-a,user-selected-model-b")

    model = build_ordered_gemini()

    assert AGENT_REASONING_MODEL == "gemini-3.7-flash"
    assert AGENT_ROUTINE_MODEL_ORDER == (
        "gemini-3.5-flash-lite",
        "gemini-3.5-flash",
    )
    assert model.search_model == AGENT_REASONING_MODEL
    assert model.model == AGENT_ROUTINE_MODEL_ORDER[0]
    assert model.fallback_models == AGENT_ROUTINE_MODEL_ORDER[1:]


def test_user_input_planning_uses_search_model(monkeypatch):
    calls: list[str] = []

    class FakeGemini:
        def __init__(self, model: str):
            self.model = model

        async def generate_content_async(self, request, stream=False):
            calls.append(self.model)
            yield "ok"

    monkeypatch.setattr(llm_module, "Gemini", FakeGemini)
    fallback = OrderedGeminiFallback(
        model="regular",
        fallback_models=("backup",),
        search_model="gemini-3.7-flash",
    )
    request = _FakeRequest(contents=[_FakeContent("user")])

    async def run():
        return [item async for item in fallback.generate_content_async(request)]

    assert asyncio.run(run()) == ["ok"]
    assert calls == ["gemini-3.7-flash"]


def test_post_tool_response_uses_regular_model_chain(monkeypatch):
    calls: list[str] = []

    class FakeGemini:
        def __init__(self, model: str):
            self.model = model

        async def generate_content_async(self, request, stream=False):
            calls.append(self.model)
            yield "ok"

    monkeypatch.setattr(llm_module, "Gemini", FakeGemini)
    fallback = OrderedGeminiFallback(
        model="regular",
        fallback_models=("backup",),
        search_model="gemini-3.7-flash",
    )
    request = _FakeRequest(
        contents=[_FakeContent("user", [_FakePart(function_response=object())])]
    )

    async def run():
        return [item async for item in fallback.generate_content_async(request)]

    assert asyncio.run(run()) == ["ok"]
    assert calls == ["regular"]


def test_quota_failure_falls_back_to_next_model(monkeypatch):
    calls: list[str] = []

    class FakeGemini:
        def __init__(self, model: str):
            self.model = model

        async def generate_content_async(self, request, stream=False):
            calls.append(self.model)
            assert request.model == self.model
            if self.model == "first":
                raise _ModelError(429)
            yield "ok"

    monkeypatch.setattr(llm_module, "Gemini", FakeGemini)
    fallback = OrderedGeminiFallback(model="first", fallback_models=("second",))

    async def run():
        return [item async for item in fallback.generate_content_async(_FakeRequest())]

    assert asyncio.run(run()) == ["ok"]
    assert calls == ["first", "second"]


def test_failure_after_emission_does_not_switch_models(monkeypatch):
    calls: list[str] = []

    class FakeGemini:
        def __init__(self, model: str):
            self.model = model

        async def generate_content_async(self, request, stream=False):
            calls.append(self.model)
            if self.model == "first":
                yield "partial"
                raise _ModelError(429)
            yield "unexpected"

    monkeypatch.setattr(llm_module, "Gemini", FakeGemini)
    fallback = OrderedGeminiFallback(model="first", fallback_models=("second",))

    async def run():
        return [item async for item in fallback.generate_content_async(_FakeRequest())]

    with pytest.raises(_ModelError):
        asyncio.run(run())
    assert calls == ["first"]


def test_non_availability_error_does_not_fallback(monkeypatch):
    calls: list[str] = []

    class FakeGemini:
        def __init__(self, model: str):
            self.model = model

        async def generate_content_async(self, request, stream=False):
            calls.append(self.model)
            raise _ModelError(400)
            yield  # pragma: no cover

    monkeypatch.setattr(llm_module, "Gemini", FakeGemini)
    fallback = OrderedGeminiFallback(model="first", fallback_models=("second",))

    async def run():
        return [item async for item in fallback.generate_content_async(_FakeRequest())]

    with pytest.raises(_ModelError):
        asyncio.run(run())
    assert calls == ["first"]
