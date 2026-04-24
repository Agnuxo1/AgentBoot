"""AgentBoot chat CLI (M1).

Minimal interactive REPL against the local Qwen3.5 model. No fake
features: only what is implemented and works.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from agentboot.llm.local import LocalLLM

DEFAULT_MODEL = Path(__file__).resolve().parents[2] / "models" / "Qwen3.5-0.8B-UD-Q4_K_XL.gguf"

SYSTEM_PROMPT = (
    "You are AgentBoot, an assistant that helps users identify computer "
    "hardware and install operating systems on bare-metal machines. "
    "Be concise and technical. If you do not know something, say so."
)


def run_chat(model_path: Path, system: str, stream: bool) -> int:
    print(f"[AgentBoot] Loading model: {model_path.name}", file=sys.stderr)
    llm = LocalLLM(model_path=model_path)
    print("[AgentBoot] Ready. Type your message, empty line to send, Ctrl+C to quit.\n", file=sys.stderr)

    history: list[dict] = [{"role": "system", "content": system}]

    while True:
        try:
            user = input("you> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        if not user:
            continue

        history.append({"role": "user", "content": user})

        print("bot> ", end="", flush=True)
        if stream:
            reply_parts: list[str] = []
            for delta in llm.chat_stream(history):
                print(delta, end="", flush=True)
                reply_parts.append(delta)
            reply = "".join(reply_parts)
            print()
        else:
            reply = llm.chat(history)
            print(reply)

        history.append({"role": "assistant", "content": reply})


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="agentboot", description="AgentBoot chat CLI (M1)")
    parser.add_argument("--model", type=Path, default=DEFAULT_MODEL, help="Path to GGUF model file")
    parser.add_argument("--system", type=str, default=SYSTEM_PROMPT, help="System prompt")
    parser.add_argument("--no-stream", action="store_true", help="Disable token streaming")
    args = parser.parse_args(argv)

    if not args.model.is_file():
        print(f"error: model file not found: {args.model}", file=sys.stderr)
        return 2

    return run_chat(args.model, args.system, stream=not args.no_stream)


if __name__ == "__main__":
    raise SystemExit(main())
