"""LLM router — picks the best available backend at runtime.

The router is created from a :class:`RouterConfig` describing the
desired backends in *priority order*. On every call it iterates the
priority list and uses the first backend that is available and
succeeds. A failure in one backend silently falls through to the
next (with a logged warning); only when every backend fails does
the router raise :class:`LLMError`.

Examples
--------

    from agentboot.llm.router import RouterConfig, LLMRouter

    cfg = RouterConfig(backends=["claude", "local"])
    router = LLMRouter.from_config(cfg)
    reply = router.chat([{"role": "user", "content": "hi"}])
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator, Optional

from agentboot.llm.base import ChatMessage, LLMBackend, LLMError, LLMUnavailable

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------


@dataclass
class RouterConfig:
    """Config for the LLM router.

    Attributes
    ----------
    backends:
        Priority-ordered list of backend names.
        Supported: ``"claude"``, ``"gemini"``, ``"local"``.
    local_model_path:
        Path to the GGUF file for the ``"local"`` backend. If *None*,
        the default model under ``models/`` is used.
    local_kwargs:
        Extra kwargs forwarded to :class:`LocalLLM` (e.g. ``n_ctx``).
    remote_kwargs:
        Extra kwargs forwarded to cloud backends (e.g. ``model``).
    """

    backends: list[str] = field(default_factory=lambda: ["claude", "gemini", "local"])
    local_model_path: Optional[Path] = None
    local_kwargs: dict = field(default_factory=dict)
    remote_kwargs: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------


class LLMRouter:
    """Route chat calls across a priority list of backends with fallback."""

    def __init__(self, backends: list[LLMBackend]) -> None:
        if not backends:
            raise ValueError("At least one backend is required")
        self.backends = backends

    # ------------------------------------------------------------------
    # Construction helpers
    # ------------------------------------------------------------------

    @classmethod
    def from_config(cls, cfg: RouterConfig) -> "LLMRouter":
        built: list[LLMBackend] = []
        for name in cfg.backends:
            try:
                built.append(cls._build_one(name, cfg))
            except LLMUnavailable as exc:
                logger.info("Backend %s unavailable: %s", name, exc)
                continue
        if not built:
            raise LLMError(
                "No LLM backend is available. Set ANTHROPIC_API_KEY, "
                "GEMINI_API_KEY, or place a GGUF model under models/."
            )
        return cls(built)

    @staticmethod
    def _build_one(name: str, cfg: RouterConfig) -> LLMBackend:
        n = name.lower()
        if n == "claude":
            from agentboot.llm.remote import ClaudeLLM
            return ClaudeLLM(**cfg.remote_kwargs)
        if n == "gemini":
            from agentboot.llm.remote import GeminiLLM
            return GeminiLLM(**cfg.remote_kwargs)
        if n == "local":
            from agentboot.llm.local import LocalLLM

            path = cfg.local_model_path
            if path is None:
                # Search the default models directory
                repo_models = Path(__file__).resolve().parents[3] / "models"
                if repo_models.is_dir():
                    ggufs = sorted(repo_models.glob("*.gguf"))
                    if ggufs:
                        path = ggufs[0]
            if path is None or not Path(path).is_file():
                raise LLMUnavailable(f"Local GGUF not found (looked under {path!r})")
            return LocalLLM(model_path=path, **cfg.local_kwargs)
        raise ValueError(f"Unknown backend: {name}")

    # ------------------------------------------------------------------
    # Chat API
    # ------------------------------------------------------------------

    def chat(
        self,
        messages: list[ChatMessage],
        max_tokens: int = 512,
        temperature: float = 0.7,
        top_p: float = 0.9,
    ) -> str:
        last_error: Optional[Exception] = None
        for backend in self.backends:
            try:
                logger.debug("Trying backend %s", backend.name)
                return backend.chat(messages, max_tokens=max_tokens,
                                    temperature=temperature, top_p=top_p)
            except LLMError as exc:
                logger.warning("Backend %s failed: %s", backend.name, exc)
                last_error = exc
        assert last_error is not None
        raise LLMError(f"All backends failed. Last error: {last_error}")

    def chat_stream(
        self,
        messages: list[ChatMessage],
        max_tokens: int = 512,
        temperature: float = 0.7,
        top_p: float = 0.9,
    ) -> Iterator[str]:
        last_error: Optional[Exception] = None
        for backend in self.backends:
            try:
                logger.debug("Trying backend %s (stream)", backend.name)
                yield from backend.chat_stream(
                    messages,
                    max_tokens=max_tokens,
                    temperature=temperature,
                    top_p=top_p,
                )
                return
            except LLMError as exc:
                logger.warning("Backend %s failed: %s", backend.name, exc)
                last_error = exc
        assert last_error is not None
        raise LLMError(f"All backends failed. Last error: {last_error}")

    @property
    def active_backend_names(self) -> list[str]:
        return [b.name for b in self.backends]
