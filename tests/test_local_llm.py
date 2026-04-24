"""Real integration tests for LocalLLM.

These tests require the Qwen3.5-0.8B GGUF model at
models/Qwen3.5-0.8B-UD-Q4_K_XL.gguf. Tests that depend on the model
are skipped automatically when the file is absent so CI without the
weights still passes the non-model checks.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agentboot.llm.local import LocalLLM

ROOT = Path(__file__).resolve().parents[1]
MODEL_PATH = ROOT / "models" / "Qwen3.5-0.8B-UD-Q4_K_XL.gguf"

needs_model = pytest.mark.skipif(
    not MODEL_PATH.is_file(),
    reason=f"model file not present at {MODEL_PATH}",
)


def test_missing_model_raises_file_not_found(tmp_path):
    missing = tmp_path / "does-not-exist.gguf"
    with pytest.raises(FileNotFoundError):
        LocalLLM(model_path=missing)


@needs_model
def test_chat_returns_non_empty_string():
    llm = LocalLLM(model_path=MODEL_PATH, n_ctx=1024)
    reply = llm.chat(
        messages=[
            {"role": "system", "content": "You are a concise technical assistant."},
            {"role": "user", "content": "Reply with exactly the word: PONG"},
        ],
        max_tokens=16,
        temperature=0.0,
    )
    assert isinstance(reply, str)
    assert reply.strip(), "reply should not be empty"


@needs_model
def test_chat_stream_yields_tokens():
    llm = LocalLLM(model_path=MODEL_PATH, n_ctx=1024)
    tokens = list(
        llm.chat_stream(
            messages=[
                {"role": "system", "content": "You are concise."},
                {"role": "user", "content": "Count: 1, 2, 3."},
            ],
            max_tokens=32,
            temperature=0.0,
        )
    )
    assert len(tokens) > 0
    assert all(isinstance(t, str) for t in tokens)
    assert any(t.strip() for t in tokens)
