"""Local LLM backend using llama.cpp + Qwen3.5 0.8B GGUF."""

from __future__ import annotations

from pathlib import Path
from typing import Iterator

from llama_cpp import Llama


class LocalLLM:
    """Thin wrapper over llama.cpp for a chat-tuned GGUF model.

    The GGUF is expected to embed its own chat template (Qwen3.5 GGUFs
    from Unsloth do). We use `create_chat_completion` so llama.cpp
    applies the template correctly.
    """

    def __init__(
        self,
        model_path: str | Path,
        n_ctx: int = 4096,
        n_threads: int | None = None,
        n_gpu_layers: int = 0,
        verbose: bool = False,
    ) -> None:
        path = Path(model_path)
        if not path.is_file():
            raise FileNotFoundError(f"GGUF model not found: {path}")

        self.model_path = path
        self.llm = Llama(
            model_path=str(path),
            n_ctx=n_ctx,
            n_threads=n_threads,
            n_gpu_layers=n_gpu_layers,
            verbose=verbose,
        )

    def chat(
        self,
        messages: list[dict],
        max_tokens: int = 512,
        temperature: float = 0.7,
        top_p: float = 0.9,
    ) -> str:
        """Single-shot chat completion. Returns the assistant text."""
        result = self.llm.create_chat_completion(
            messages=messages,
            max_tokens=max_tokens,
            temperature=temperature,
            top_p=top_p,
            stream=False,
        )
        return result["choices"][0]["message"]["content"]

    def chat_stream(
        self,
        messages: list[dict],
        max_tokens: int = 512,
        temperature: float = 0.7,
        top_p: float = 0.9,
    ) -> Iterator[str]:
        """Streaming chat completion. Yields token deltas."""
        stream = self.llm.create_chat_completion(
            messages=messages,
            max_tokens=max_tokens,
            temperature=temperature,
            top_p=top_p,
            stream=True,
        )
        for chunk in stream:
            delta = chunk["choices"][0].get("delta", {})
            if "content" in delta and delta["content"]:
                yield delta["content"]
