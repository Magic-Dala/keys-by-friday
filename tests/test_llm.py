import asyncio

import pytest

import rental_agent.llm as llm_module
from rental_agent.llm import DEFAULT_MODEL_ORDER, OrderedGeminiFallback, configured_model_order


class _FakeRequest:
    def __init__(self, model: str | None = None):
        self.model = model

    def model_copy(self, deep: bool = False):
        return _FakeRequest(self.model)


class _ModelError(RuntimeError):
    def __init__(self, code: int):
        super().__init__(f"model error {code}")
        self.code = code


def test_default_model_order_prefers_high_throughput_lite(monkeypatch):
    monkeypatch.delenv("GEMINI_MODELS", raising=False)
    assert configured_model_order() == DEFAULT_MODEL_ORDER
    assert DEFAULT_MODEL_ORDER[:2] == (
        "gemini-3.5-flash-lite",
        "gemini-3.1-flash-lite",
    )


def test_env_model_order_is_preserved_and_deduplicated(monkeypatch):
    monkeypatch.setenv("GEMINI_MODELS", "model-a, model-b, model-a")
    assert configured_model_order() == ("model-a", "model-b")


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
