"""Shared types for LLM backends.

Keeping a small abstract surface here (instead of an ABC with many
methods) is deliberate: every backend exposes the same two operations
— single-shot chat and streaming chat — and nothing more.
"""

from __future__ import annotations

from typing import Iterator, Protocol, TypedDict


class ChatMessage(TypedDict):
    role: str          # "system" | "user" | "assistant"
    content: str


class LLMBackend(Protocol):
    name: str

    def chat(
        self,
        messages: list[ChatMessage],
        max_tokens: int = 512,
        temperature: float = 0.7,
        top_p: float = 0.9,
    ) -> str: ...

    def chat_stream(
        self,
        messages: list[ChatMessage],
        max_tokens: int = 512,
        temperature: float = 0.7,
        top_p: float = 0.9,
    ) -> Iterator[str]: ...


class LLMError(RuntimeError):
    """Raised by backends when a generation call fails unrecoverably."""


class LLMUnavailable(LLMError):
    """Raised when a backend cannot be used (e.g. missing API key, offline)."""
