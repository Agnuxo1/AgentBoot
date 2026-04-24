"""M1 smoke test: load Qwen3.5 0.8B and produce one real completion.

Run:
    .venv/Scripts/python.exe scripts/smoke_test.py
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from agentboot.llm.local import LocalLLM  # noqa: E402

MODEL_PATH = ROOT / "models" / "Qwen3.5-0.8B-UD-Q4_K_XL.gguf"


def main() -> int:
    if not MODEL_PATH.is_file():
        print(f"FAIL: model not found at {MODEL_PATH}")
        return 1

    t0 = time.time()
    llm = LocalLLM(model_path=MODEL_PATH, n_ctx=2048, verbose=False)
    t_load = time.time() - t0
    print(f"[ok] model loaded in {t_load:.2f}s")

    messages = [
        {"role": "system", "content": "You are a concise technical assistant."},
        {"role": "user", "content": "In one sentence, what is UEFI?"},
    ]

    t0 = time.time()
    reply = llm.chat(messages, max_tokens=128, temperature=0.2)
    t_gen = time.time() - t0
    print(f"[ok] generated in {t_gen:.2f}s")
    print(f"[reply] {reply}")

    if not reply.strip():
        print("FAIL: empty reply")
        return 2

    print("\nSMOKE TEST PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
