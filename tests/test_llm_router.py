"""Tests for the LLM router.

We don't exercise live cloud APIs here (no secrets in CI). We do
verify the routing logic and error handling with fake backends.
"""

from __future__ import annotations

import pytest

from agentboot.llm.base import LLMError, LLMUnavailable
from agentboot.llm.router import LLMRouter, RouterConfig


# ---------------------------------------------------------------------------
# Test doubles
# ---------------------------------------------------------------------------


class _OK:
    name = "ok"

    def chat(self, messages, max_tokens=512, temperature=0.7, top_p=0.9):
        return "ok-reply"

    def chat_stream(self, messages, max_tokens=512, temperature=0.7, top_p=0.9):
        yield "ok"
        yield "-stream"


class _Broken:
    name = "broken"

    def chat(self, *args, **kwargs):
        raise LLMError("intentional failure")

    def chat_stream(self, *args, **kwargs):
        raise LLMError("intentional failure")
        yield  # pragma: no cover  (generator marker)


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------


def test_router_requires_at_least_one_backend():
    with pytest.raises(ValueError):
        LLMRouter([])


def test_router_from_config_rejects_unknown_backend():
    with pytest.raises(ValueError):
        LLMRouter._build_one("does-not-exist", RouterConfig())


def test_router_from_config_raises_when_no_backend_available(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)

    cfg = RouterConfig(backends=["claude", "gemini"], local_model_path=None)
    with pytest.raises(LLMError):
        LLMRouter.from_config(cfg)


# ---------------------------------------------------------------------------
# Routing logic
# ---------------------------------------------------------------------------


def test_router_uses_first_backend_on_success():
    router = LLMRouter([_OK(), _Broken()])
    assert router.chat([{"role": "user", "content": "hi"}]) == "ok-reply"


def test_router_falls_through_to_next_on_failure():
    router = LLMRouter([_Broken(), _OK()])
    assert router.chat([{"role": "user", "content": "hi"}]) == "ok-reply"


def test_router_raises_when_all_backends_fail():
    router = LLMRouter([_Broken(), _Broken()])
    with pytest.raises(LLMError):
        router.chat([{"role": "user", "content": "hi"}])


def test_router_streaming_passes_through_tokens():
    router = LLMRouter([_OK()])
    out = "".join(router.chat_stream([{"role": "user", "content": "hi"}]))
    assert out == "ok-stream"


def test_router_streaming_falls_through_on_failure():
    router = LLMRouter([_Broken(), _OK()])
    out = "".join(router.chat_stream([{"role": "user", "content": "hi"}]))
    assert out == "ok-stream"


def test_active_backend_names_lists_in_order():
    router = LLMRouter([_OK(), _Broken()])
    assert router.active_backend_names == ["ok", "broken"]


# ---------------------------------------------------------------------------
# Remote backends (construction-only, no API calls)
# ---------------------------------------------------------------------------


def test_claude_raises_unavailable_without_key(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    from agentboot.llm.remote import ClaudeLLM

    with pytest.raises(LLMUnavailable):
        ClaudeLLM()


def test_gemini_raises_unavailable_without_key(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    from agentboot.llm.remote import GeminiLLM

    with pytest.raises(LLMUnavailable):
        GeminiLLM()
