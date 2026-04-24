"""AgentBoot chat CLI (M2).

Conversational REPL with integrated hardware detection and OS recommendation.
No fake features: only what is implemented and works.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Optional

from agentboot.llm.local import LocalLLM

DEFAULT_MODEL = Path(__file__).resolve().parents[2] / "models" / "Qwen3.5-0.8B-UD-Q4_K_XL.gguf"

SYSTEM_PROMPT = (
    "You are AgentBoot, an expert AI sysadmin assistant. "
    "Your speciality is identifying computer hardware and helping users install "
    "the right operating system on bare-metal machines. "
    "When the user wants to know about their hardware or choose an OS, "
    "the CLI will run real detection tools and inject the results into your context. "
    "Be concise, technical, and accurate. If you do not know something, say so."
)

WELCOME_BANNER = r"""
  ___                    _   ____              _
 / _ \                  | | |  _ \            | |
/ /_\ \ __ _  ___ _ __ | |_| |_) | ___   ___ | |_
|  _  |/ _` |/ _ \ '_ \| __|  _ < / _ \ / _ \| __|
| | | | (_| |  __/ | | | |_| |_) | (_) | (_) | |_
\_| |_/\__, |\___|_| |_|\__|____/ \___/ \___/ \__|
        __/ |
       |___/   v0.2.0 — Phase 2: Hardware Detection

Type your question or use these commands:
  /detect          — Detect local hardware and get OS recommendations
  /detect ssh      — Detect remote hardware via SSH
  /recommend       — Show OS recommendations for current hardware profile
  /hardware        — Show current hardware profile summary
  /help            — Show this help
  /quit            — Exit
"""

HELP_TEXT = """
AgentBoot commands:
  /detect                  Detect hardware on this machine
  /detect ssh HOST [PORT] [USER]
                           Detect hardware on a remote machine via SSH
  /recommend               Show top OS recommendations for detected hardware
  /recommend server        Filter: server OS only
  /recommend minimal       Filter: lightweight / minimal OS only
  /recommend hypervisor    Filter: virtualisation OS only
  /recommend nas           Filter: NAS / storage OS only
  /hardware                Print the full hardware profile
  /help                    Show this help
  /quit                    Exit AgentBoot

Or just chat — ask anything about hardware, OS choice, or installation.
"""


# ---------------------------------------------------------------------------
# Hardware detection wrapper (lazy import so CLI starts without psutil)
# ---------------------------------------------------------------------------


def _do_detect_local() -> tuple[str, object]:
    """Run local detection. Returns (summary_text, HardwareProfile)."""
    from agentboot.hardware_detector import HardwareDetector

    print("[AgentBoot] Running hardware detection...", file=sys.stderr)
    detector = HardwareDetector()
    profile = detector.detect_local()
    return profile.summary(), profile


def _do_detect_ssh(host: str, port: int = 22, user: str = "root") -> tuple[str, object]:
    """Run SSH detection. Returns (summary_text, HardwareProfile)."""
    from agentboot.hardware_detector import HardwareDetector

    print(f"[AgentBoot] Connecting to {user}@{host}:{port}...", file=sys.stderr)
    detector = HardwareDetector()
    try:
        profile = detector.detect_remote_ssh(host=host, port=port, user=user)
    except Exception as exc:
        return f"SSH detection failed: {exc}", None
    return profile.summary(), profile


def _do_recommend(profile, tags: Optional[list[str]] = None) -> str:
    """Generate OS recommendations for *profile*."""
    from agentboot.os_compatibility import recommend_os, format_top_recommendations

    recs = recommend_os(profile, max_results=10, tags_filter=tags)
    return format_top_recommendations(recs, n=3)


# ---------------------------------------------------------------------------
# Command parsing
# ---------------------------------------------------------------------------


def _parse_command(text: str):
    """Return (command, args_list) or None if not a slash command."""
    stripped = text.strip()
    if not stripped.startswith("/"):
        return None
    parts = stripped[1:].split()
    return parts[0].lower() if parts else "", parts[1:]


def _handle_command(
    cmd: str,
    args: list[str],
    history: list[dict],
    current_profile,
    llm: LocalLLM,
    stream: bool,
) -> tuple[object, bool]:
    """Handle a slash command. Returns (updated_profile, should_continue)."""

    if cmd in ("quit", "exit", "q"):
        print("\n[AgentBoot] Goodbye!")
        return current_profile, False

    if cmd == "help":
        print(HELP_TEXT)
        return current_profile, True

    if cmd == "hardware":
        if current_profile is None:
            print("[AgentBoot] No hardware profile yet. Run /detect first.")
        else:
            print(current_profile.summary())
        return current_profile, True

    if cmd == "detect":
        if args and args[0].lower() == "ssh":
            host = args[1] if len(args) > 1 else input("  SSH host: ").strip()
            port_str = args[2] if len(args) > 2 else "22"
            user = args[3] if len(args) > 3 else "root"
            try:
                port = int(port_str)
            except ValueError:
                port = 22
            summary, profile = _do_detect_ssh(host, port, user)
        else:
            summary, profile = _do_detect_local()

        print("\n" + "=" * 60)
        print("DETECTED HARDWARE")
        print("=" * 60)
        print(summary)
        print("=" * 60)

        if profile is not None:
            # Inject hardware context into conversation
            hw_context = (
                "Here is the hardware profile of the target machine:\n\n"
                + summary
            )
            history.append({"role": "user", "content": hw_context})

            # Auto-recommend
            rec_text = _do_recommend(profile)
            print(rec_text)

            recs_context = (
                "Based on the hardware above, here are the OS recommendations:\n\n"
                + rec_text
            )
            history.append({"role": "assistant", "content": recs_context})
            print("\n[AgentBoot] Hardware profile stored. Ask me anything about the results.")

        return profile, True

    if cmd == "recommend":
        if current_profile is None:
            print("[AgentBoot] Run /detect first to get a hardware profile.")
            return current_profile, True

        tag_map = {
            "server": ["server"],
            "minimal": ["minimal", "lightweight"],
            "hypervisor": ["hypervisor", "virtualisation"],
            "nas": ["nas", "storage"],
            "desktop": ["desktop"],
            "container": ["container-host", "kubernetes"],
            "router": ["firewall", "router", "networking"],
        }
        tags = None
        if args:
            keyword = args[0].lower()
            tags = tag_map.get(keyword)
            if tags is None:
                print(f"[AgentBoot] Unknown filter '{keyword}'. Valid: {', '.join(tag_map)}")
                return current_profile, True

        rec_text = _do_recommend(current_profile, tags)
        print(rec_text)
        return current_profile, True

    print(f"[AgentBoot] Unknown command '/{cmd}'. Type /help for commands.")
    return current_profile, True


# ---------------------------------------------------------------------------
# Main chat loop
# ---------------------------------------------------------------------------


def run_chat(model_path: Path, system: str, stream: bool) -> int:
    print(f"[AgentBoot] Loading model: {model_path.name}", file=sys.stderr)
    llm = LocalLLM(model_path=model_path)
    print(WELCOME_BANNER)

    history: list[dict] = [{"role": "system", "content": system}]
    current_profile = None

    # --- Greet user and propose detection ---
    print("[AgentBoot] Would you like me to detect your hardware now? (type /detect or just ask)\n")

    while True:
        try:
            user_input = input("you> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n[AgentBoot] Goodbye!")
            return 0

        if not user_input:
            continue

        # --- Slash commands ---
        parsed = _parse_command(user_input)
        if parsed is not None:
            cmd, args = parsed
            current_profile, should_continue = _handle_command(
                cmd, args, history, current_profile, llm, stream
            )
            if not should_continue:
                return 0
            continue

        # --- Natural-language shortcut: detect intent ---
        low = user_input.lower()
        if any(kw in low for kw in ("detect", "scan", "identify", "what hardware", "my hardware")):
            summary, profile = _do_detect_local()
            if profile is not None:
                current_profile = profile
                hw_msg = (
                    "I detected the hardware. Here is the summary:\n\n"
                    + summary
                    + "\n\nHere are my OS recommendations:\n"
                    + _do_recommend(profile)
                )
                print("\n" + hw_msg + "\n")
                history.append({"role": "user", "content": user_input})
                history.append({"role": "assistant", "content": hw_msg})
            else:
                print(f"[AgentBoot] Detection failed: {summary}")
            continue

        # --- Regular LLM chat ---
        history.append({"role": "user", "content": user_input})

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
    parser = argparse.ArgumentParser(
        prog="agentboot",
        description="AgentBoot — AI agent for bare-metal OS installation (M2)",
    )
    parser.add_argument("--model", type=Path, default=DEFAULT_MODEL, help="Path to GGUF model file")
    parser.add_argument("--system", type=str, default=SYSTEM_PROMPT, help="System prompt override")
    parser.add_argument("--no-stream", action="store_true", help="Disable token streaming")
    args = parser.parse_args(argv)

    if not args.model.is_file():
        print(f"error: model file not found: {args.model}", file=sys.stderr)
        return 2

    return run_chat(args.model, args.system, stream=not args.no_stream)


if __name__ == "__main__":
    raise SystemExit(main())
