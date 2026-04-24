"""Cloud LLM backends: Anthropic Claude and Google Gemini.

Uses the provider's own Python SDKs when installed (they are optional
extras — see pyproject.toml). If the SDK is missing or the API key is
not set, the corresponding class raises :class:`LLMUnavailable` at
construction time, so the router can fall back to another backend.
"""

from __future__ import annotations

import os
from typing import Iterator

from agentboot.llm.base import ChatMessage, LLMError, LLMUnavailable


# ---------------------------------------------------------------------------
# Anthropic Claude
# ---------------------------------------------------------------------------


class ClaudeLLM:
    """Claude backend via the official ``anthropic`` SDK.

    Default model is ``claude-sonnet-4-6`` — a good quality/latency
    trade-off. Override with ``model=`` or ``ANTHROPIC_MODEL`` env var.
    """

    name = "claude"

    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        max_retries: int = 2,
        timeout: float = 60.0,
    ) -> None:
        key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        if not key:
            raise LLMUnavailable("ANTHROPIC_API_KEY is not set")

        try:
            import anthropic  # type: ignore
        except ImportError as exc:
            raise LLMUnavailable(
                "anthropic SDK not installed — pip install 'agentboot[cloud]'"
            ) from exc

        self._anthropic = anthropic
        self._client = anthropic.Anthropic(api_key=key, max_retries=max_retries, timeout=timeout)
        self.model = model or os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-6")

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _split_system(messages: list[ChatMessage]) -> tuple[str | None, list[ChatMessage]]:
        """Claude's API takes `system` as a top-level param, not a role."""
        system_parts: list[str] = []
        rest: list[ChatMessage] = []
        for m in messages:
            if m["role"] == "system":
                system_parts.append(m["content"])
            else:
                rest.append(m)
        system = "\n\n".join(system_parts) if system_parts else None
        return system, rest

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def chat(
        self,
        messages: list[ChatMessage],
        max_tokens: int = 512,
        temperature: float = 0.7,
        top_p: float = 0.9,
    ) -> str:
        system, convo = self._split_system(messages)
        try:
            resp = self._client.messages.create(
                model=self.model,
                max_tokens=max_tokens,
                temperature=temperature,
                top_p=top_p,
                system=system,
                messages=convo,
            )
        except self._anthropic.APIError as exc:
            raise LLMError(f"Claude API error: {exc}") from exc

        # Response content is a list of blocks — we take the text ones.
        parts = [b.text for b in resp.content if getattr(b, "type", "") == "text"]
        return "".join(parts)

    def chat_stream(
        self,
        messages: list[ChatMessage],
        max_tokens: int = 512,
        temperature: float = 0.7,
        top_p: float = 0.9,
    ) -> Iterator[str]:
        system, convo = self._split_system(messages)
        try:
            with self._client.messages.stream(
                model=self.model,
                max_tokens=max_tokens,
                temperature=temperature,
                top_p=top_p,
                system=system,
                messages=convo,
            ) as stream:
                for text in stream.text_stream:
                    yield text
        except self._anthropic.APIError as exc:
            raise LLMError(f"Claude API error: {exc}") from exc


# ---------------------------------------------------------------------------
# Google Gemini
# ---------------------------------------------------------------------------


class GeminiLLM:
    """Gemini backend via ``google-generativeai``.

    Default model is ``gemini-1.5-flash`` (fast and cheap). Override with
    ``model=`` or ``GEMINI_MODEL``.
    """

    name = "gemini"

    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
    ) -> None:
        key = api_key or os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
        if not key:
            raise LLMUnavailable("GEMINI_API_KEY / GOOGLE_API_KEY is not set")

        try:
            import google.generativeai as genai  # type: ignore
        except ImportError as exc:
            raise LLMUnavailable(
                "google-generativeai not installed — pip install 'agentboot[cloud]'"
            ) from exc

        genai.configure(api_key=key)
        self._genai = genai
        self.model_name = model or os.environ.get("GEMINI_MODEL", "gemini-1.5-flash")

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _convert(messages: list[ChatMessage]) -> tuple[str | None, list[dict]]:
        """Gemini takes a separate system_instruction and maps
        'assistant' -> 'model'."""
        system_parts: list[str] = []
        converted: list[dict] = []
        for m in messages:
            role = m["role"]
            if role == "system":
                system_parts.append(m["content"])
                continue
            gem_role = "model" if role == "assistant" else "user"
            converted.append({"role": gem_role, "parts": [m["content"]]})
        system = "\n\n".join(system_parts) if system_parts else None
        return system, converted

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def _build_model(self, system: str | None, max_tokens: int, temperature: float, top_p: float):
        return self._genai.GenerativeModel(
            model_name=self.model_name,
            system_instruction=system,
            generation_config={
                "max_output_tokens": max_tokens,
                "temperature": temperature,
                "top_p": top_p,
            },
        )

    def chat(
        self,
        messages: list[ChatMessage],
        max_tokens: int = 512,
        temperature: float = 0.7,
        top_p: float = 0.9,
    ) -> str:
        system, convo = self._convert(messages)
        model = self._build_model(system, max_tokens, temperature, top_p)
        try:
            resp = model.generate_content(convo)
        except Exception as exc:  # google-generativeai raises various shapes
            raise LLMError(f"Gemini API error: {exc}") from exc
        return resp.text or ""

    def chat_stream(
        self,
        messages: list[ChatMessage],
        max_tokens: int = 512,
        temperature: float = 0.7,
        top_p: float = 0.9,
    ) -> Iterator[str]:
        system, convo = self._convert(messages)
        model = self._build_model(system, max_tokens, temperature, top_p)
        try:
            for chunk in model.generate_content(convo, stream=True):
                if chunk.text:
                    yield chunk.text
        except Exception as exc:
            raise LLMError(f"Gemini API error: {exc}") from exc
