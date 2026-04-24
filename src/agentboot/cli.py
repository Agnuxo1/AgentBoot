"""AgentBoot command-line interface.

Subcommands expose every capability of the package:

    agentboot chat                         Conversational REPL (local LLM)
    agentboot detect [--ssh HOST]          Hardware detection
    agentboot recommend [--filter TAG]     OS recommendation for a detected host
    agentboot list-isos [--arch ARCH]      Show the curated ISO catalogue
    agentboot download OS_ID [--arch ...]  Download + verify an installer ISO
    agentboot list-devices                 Enumerate removable USB devices
    agentboot flash --iso ... --device ... Write an ISO to a USB stick
    agentboot gen-config --os ... --user . Generate autoinstall files
    agentboot session show|reset           Inspect / reset a saved install session
    agentboot install ...                  Full orchestrated install flow

Every subcommand is a thin wrapper over the tested modules in
:mod:`agentboot.{hardware_detector,os_compatibility,iso,flasher,autoinstall,agent}`.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Optional

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
       |___/

Type your question or use /detect, /recommend, /hardware, /help, /quit.
"""

HELP_TEXT = """
Chat REPL commands:
  /detect                  Detect hardware on this machine
  /detect ssh HOST [PORT] [USER]
                           Detect hardware on a remote machine via SSH
  /recommend [TAG]         Show top OS recommendations (optional tag filter)
  /hardware                Print the current hardware profile summary
  /help                    Show this help
  /quit                    Exit AgentBoot
"""

_TAG_MAP = {
    "server": ["server"],
    "minimal": ["minimal", "lightweight"],
    "hypervisor": ["hypervisor", "virtualisation"],
    "nas": ["nas", "storage"],
    "desktop": ["desktop"],
    "container": ["container-host", "kubernetes"],
    "router": ["firewall", "router", "networking"],
}


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _err(msg: str) -> None:
    print(msg, file=sys.stderr)


def _info(msg: str) -> None:
    print(f"[AgentBoot] {msg}", file=sys.stderr)


def _do_detect_local():
    from agentboot.hardware_detector import HardwareDetector
    return HardwareDetector().detect_local()


def _do_detect_ssh(host: str, port: int, user: str):
    from agentboot.hardware_detector import HardwareDetector
    return HardwareDetector().detect_remote_ssh(host=host, port=port, user=user)


def _resolve_tags(name: Optional[str]) -> Optional[list[str]]:
    if not name:
        return None
    tags = _TAG_MAP.get(name.lower())
    if tags is None:
        raise SystemExit(
            f"error: unknown --filter '{name}'. Valid: {', '.join(_TAG_MAP)}"
        )
    return tags


# ---------------------------------------------------------------------------
# Subcommand: detect
# ---------------------------------------------------------------------------


def cmd_detect(args: argparse.Namespace) -> int:
    if args.ssh:
        _info(f"Connecting to {args.user}@{args.ssh}:{args.port}...")
        try:
            profile = _do_detect_ssh(args.ssh, args.port, args.user)
        except Exception as exc:
            _err(f"SSH detection failed: {exc}")
            return 1
    else:
        _info("Running local hardware detection...")
        profile = _do_detect_local()

    if args.json:
        import dataclasses
        payload = dataclasses.asdict(profile) if dataclasses.is_dataclass(profile) else profile
        print(json.dumps(payload, indent=2, default=str))
    else:
        print(profile.summary())
    return 0


# ---------------------------------------------------------------------------
# Subcommand: recommend
# ---------------------------------------------------------------------------


def cmd_recommend(args: argparse.Namespace) -> int:
    from agentboot.os_compatibility import recommend_os, format_top_recommendations

    tags = _resolve_tags(args.filter)
    profile = _do_detect_local()
    recs = recommend_os(profile, max_results=args.max_results, tags_filter=tags)
    if args.json:
        import dataclasses
        out = [dataclasses.asdict(r) if dataclasses.is_dataclass(r) else r for r in recs]
        print(json.dumps(out, indent=2, default=str))
    else:
        print(format_top_recommendations(recs, n=args.top))
    return 0


# ---------------------------------------------------------------------------
# Subcommand: list-isos
# ---------------------------------------------------------------------------


def cmd_list_isos(args: argparse.Namespace) -> int:
    from agentboot.iso import ISO_CATALOG, list_isos_for_arch

    entries = list_isos_for_arch(args.arch) if args.arch else ISO_CATALOG

    if args.json:
        import dataclasses
        print(json.dumps([dataclasses.asdict(e) for e in entries], indent=2))
        return 0

    if not entries:
        print(f"No ISOs catalogued for arch={args.arch}")
        return 0
    fmt = "{:<22} {:<8} {:>6}  {}"
    print(fmt.format("ID", "ARCH", "SIZE", "NAME"))
    print("-" * 80)
    for e in entries:
        print(fmt.format(e.id, e.arch, f"{e.size_gb:.1f}GB", e.name))
    return 0


# ---------------------------------------------------------------------------
# Subcommand: download
# ---------------------------------------------------------------------------


def cmd_download(args: argparse.Namespace) -> int:
    from agentboot.iso import find_iso, download_iso, ChecksumMismatch

    entry = find_iso(args.os_id, args.arch)
    if entry is None:
        _err(f"No ISO in catalogue for os_id={args.os_id!r} arch={args.arch!r}")
        _err("Hint: run `agentboot list-isos` to see available IDs.")
        return 2

    dest_dir = Path(args.dest).resolve()
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / entry.filename

    _info(f"Downloading {entry.name} → {dest}")
    last_pct = [-1]

    def _progress(p):
        if p.total_bytes:
            pct = int(p.fraction * 100) if p.fraction else 0
            if pct != last_pct[0]:
                last_pct[0] = pct
                mb = p.downloaded_bytes / (1024 * 1024)
                total_mb = p.total_bytes / (1024 * 1024)
                sys.stderr.write(f"\r  {pct:3d}%  {mb:8.1f} / {total_mb:.1f} MiB")
                sys.stderr.flush()

    try:
        result = download_iso(
            entry.url, dest,
            checksum_url=entry.checksum_url,
            checksum_filename=entry.checksum_filename,
            progress=_progress,
        )
    except ChecksumMismatch as exc:
        sys.stderr.write("\n")
        _err(f"Checksum mismatch: {exc}")
        return 3
    except Exception as exc:
        sys.stderr.write("\n")
        _err(f"Download failed: {exc}")
        return 1
    sys.stderr.write("\n")
    _info(f"OK: {result.path} (sha256={result.sha256 or 'not-verified'})")
    print(str(result.path))
    return 0


# ---------------------------------------------------------------------------
# Subcommand: list-devices
# ---------------------------------------------------------------------------


def cmd_list_devices(args: argparse.Namespace) -> int:
    from agentboot.flasher import enumerate_usb_devices

    devices = enumerate_usb_devices()
    if args.json:
        import dataclasses
        print(json.dumps([dataclasses.asdict(d) for d in devices], indent=2, default=str))
        return 0

    if not devices:
        print("No removable USB devices detected.")
        return 0
    fmt = "{:<24} {:>10}  {:<32} {}"
    print(fmt.format("ID", "SIZE", "MODEL", "MOUNTS"))
    print("-" * 90)
    for d in devices:
        mounts = ",".join(d.mount_points) or "(none)"
        size_gb = f"{d.size_bytes / 1e9:.1f}GB"
        print(fmt.format(d.id, size_gb, (d.model or "?")[:32], mounts))
    return 0


# ---------------------------------------------------------------------------
# Subcommand: flash
# ---------------------------------------------------------------------------


def cmd_flash(args: argparse.Namespace) -> int:
    from agentboot.flasher import (
        find_device_by_id, plan_flash, flash_iso, FlashError,
    )

    iso = Path(args.iso).resolve()
    if not iso.is_file():
        _err(f"ISO not found: {iso}")
        return 2

    device = find_device_by_id(args.device)
    if device is None:
        _err(f"USB device {args.device!r} not found. Run `agentboot list-devices`.")
        return 2

    try:
        plan = plan_flash(iso, device)
    except FlashError as exc:
        _err(f"Cannot flash: {exc}")
        return 3

    print("\n" + "=" * 60)
    print("FLASH PLAN")
    print("=" * 60)
    print(plan.human_summary())
    print("=" * 60)

    if args.confirm != device.id:
        _err(
            f"\nThis will DESTROY all data on {device.id}.\n"
            f"Re-run with: --yes-destroy-device {device.id}"
        )
        return 4

    last_pct = [-1]
    def _progress(p):
        pct = int(p.fraction * 100)
        if pct != last_pct[0]:
            last_pct[0] = pct
            mb = p.bytes_written / (1024 * 1024)
            total_mb = p.total_bytes / (1024 * 1024)
            sys.stderr.write(f"\r  {pct:3d}%  {mb:8.1f} / {total_mb:.1f} MiB")
            sys.stderr.flush()

    try:
        flash_iso(plan, confirm_token=args.confirm, progress=_progress)
    except FlashError as exc:
        sys.stderr.write("\n")
        _err(f"Flash aborted: {exc}")
        return 3
    sys.stderr.write("\n")
    _info("Flash complete.")
    return 0


# ---------------------------------------------------------------------------
# Subcommand: gen-config
# ---------------------------------------------------------------------------


def cmd_gen_config(args: argparse.Namespace) -> int:
    from agentboot.autoinstall import (
        User, DiskLayout, NetworkConfig, InstallProfile, generate_for_os,
    )

    user = User(
        username=args.user,
        password=args.password,
        password_hash=args.password_hash,
        ssh_authorized_keys=list(args.ssh_key or []),
    )
    disk = DiskLayout(target=args.disk, mode=args.disk_mode)
    network = NetworkConfig(hostname=args.hostname, dhcp=True)
    profile = InstallProfile(
        user=user,
        disk=disk,
        network=network,
        timezone=args.timezone,
        locale=args.locale,
        keyboard=args.keyboard,
        packages=list(args.package or []),
    )

    try:
        files = generate_for_os(args.os, profile)
    except (ValueError, KeyError, NotImplementedError) as exc:
        _err(f"Config generation failed: {exc}")
        return 2

    out_dir = Path(args.output).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    for f in files:
        target = out_dir / f.path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(f.body_bytes)
        try:
            target.chmod(f.mode)
        except (OSError, NotImplementedError):
            pass  # Windows doesn't honour POSIX modes
        print(str(target))
    _info(f"Wrote {len(files)} file(s) to {out_dir}")
    return 0


# ---------------------------------------------------------------------------
# Subcommand: session
# ---------------------------------------------------------------------------


def cmd_session(args: argparse.Namespace) -> int:
    from agentboot.agent import load_session, SessionError

    session_dir = Path(args.dir).resolve()

    if args.action == "show":
        try:
            s = load_session(session_dir)
        except SessionError as exc:
            _err(str(exc))
            return 2
        print(f"Session ID:     {s.id}")
        print(f"State:          {s.state.value}")
        print(f"Created at:     {s.created_at}")
        if s.error:
            print(f"Error:          {s.error}")
        if s.hardware_profile:
            print("Hardware:       (profile present)")
        if s.os_recommendation:
            print(f"OS chosen:      {s.os_recommendation.get('name', '?')}")
        if s.iso_path:
            print(f"ISO path:       {s.iso_path}")
        if s.target_device_id:
            print(f"Target device:  {s.target_device_id}")
        print(f"History:        {len(s.history)} entries")
        return 0

    if args.action == "reset":
        try:
            s = load_session(session_dir)
        except SessionError as exc:
            _err(str(exc))
            return 2
        s.reset()
        _info(f"Session {s.id} reset to INIT.")
        return 0

    _err(f"Unknown session action: {args.action}")
    return 2


# ---------------------------------------------------------------------------
# Subcommand: install (orchestrated flow)
# ---------------------------------------------------------------------------


def cmd_install(args: argparse.Namespace) -> int:
    from agentboot.agent import InstallSession, Orchestrator, load_session, SessionError

    session_dir = Path(args.session_dir).resolve()
    session_dir.mkdir(parents=True, exist_ok=True)

    if args.resume:
        try:
            session = load_session(session_dir)
            _info(f"Resumed session {session.id} at state {session.state.value}")
        except SessionError:
            session = InstallSession()
            _info(f"Starting new session {session.id}")
    else:
        session = InstallSession()

    orc = Orchestrator(session, session_dir)

    # Phase 1: detect
    from agentboot.agent.session import State
    if session.state in (State.INIT, State.DETECTING, State.FAILED):
        _info("Phase 1/6: detecting hardware...")
        orc.detect()

    # Phase 2: recommend
    if session.state == State.RECOMMENDING:
        _info("Phase 2/6: recommending OS...")
        tags = _resolve_tags(args.filter)
        recs = orc.recommend(tags_filter=tags)
        if not recs:
            _err("No compatible OS found — stopping.")
            return 1
        _info(f"Chose: {session.os_recommendation.get('name', '?')}")

    # Phase 3: download
    if session.state == State.DOWNLOADING or (
        session.state == State.RECOMMENDING and args.download_dir
    ):
        _info("Phase 3/6: downloading ISO...")
        orc.download(args.download_dir)

    # Phase 4: flash
    if session.state == State.FLASHING and args.device:
        _info("Phase 4/6: flashing USB...")
        orc.flash(args.device, confirm_token=args.device)

    # Phase 5: configure
    if session.state == State.CONFIGURING and args.user:
        _info("Phase 5/6: generating autoinstall config...")
        from agentboot.autoinstall import (
            User, DiskLayout, NetworkConfig, InstallProfile,
        )
        profile = InstallProfile(
            user=User(
                username=args.user,
                password=args.password,
                password_hash=args.password_hash,
            ),
            disk=DiskLayout(),
            network=NetworkConfig(hostname=args.hostname or "agentboot-host"),
        )
        orc.configure(profile)

    _info(f"Stopped at state: {session.state.value}")
    return 0


# ---------------------------------------------------------------------------
# Subcommand: chat  (legacy M2 REPL)
# ---------------------------------------------------------------------------


def _do_recommend_text(profile, tags: Optional[list[str]] = None) -> str:
    from agentboot.os_compatibility import recommend_os, format_top_recommendations
    recs = recommend_os(profile, max_results=10, tags_filter=tags)
    return format_top_recommendations(recs, n=3)


def _parse_slash(text: str):
    s = text.strip()
    if not s.startswith("/"):
        return None
    parts = s[1:].split()
    return (parts[0].lower() if parts else ""), parts[1:]


def _handle_slash(cmd, args, history, profile):
    if cmd in ("quit", "exit", "q"):
        print("\n[AgentBoot] Goodbye!")
        return profile, False
    if cmd == "help":
        print(HELP_TEXT)
        return profile, True
    if cmd == "hardware":
        if profile is None:
            print("[AgentBoot] No profile yet. Run /detect first.")
        else:
            print(profile.summary())
        return profile, True
    if cmd == "detect":
        if args and args[0].lower() == "ssh":
            host = args[1] if len(args) > 1 else input("  SSH host: ").strip()
            port = int(args[2]) if len(args) > 2 else 22
            user = args[3] if len(args) > 3 else "root"
            try:
                profile = _do_detect_ssh(host, port, user)
            except Exception as exc:
                print(f"[AgentBoot] SSH failed: {exc}")
                return profile, True
        else:
            profile = _do_detect_local()
        print(profile.summary())
        print(_do_recommend_text(profile))
        history.append({"role": "user", "content": "Detected hardware:\n" + profile.summary()})
        return profile, True
    if cmd == "recommend":
        if profile is None:
            print("[AgentBoot] Run /detect first.")
            return profile, True
        tags = None
        if args:
            tags = _TAG_MAP.get(args[0].lower())
            if tags is None:
                print(f"[AgentBoot] Unknown filter. Valid: {', '.join(_TAG_MAP)}")
                return profile, True
        print(_do_recommend_text(profile, tags))
        return profile, True
    print(f"[AgentBoot] Unknown /{cmd}. See /help.")
    return profile, True


def cmd_chat(args: argparse.Namespace) -> int:
    from agentboot.llm.local import LocalLLM

    if not args.model.is_file():
        _err(f"Model file not found: {args.model}")
        _err("Hint: download Qwen3.5-0.8B GGUF and pass --model PATH.")
        return 2

    _info(f"Loading model: {args.model.name}")
    llm = LocalLLM(model_path=args.model)
    print(WELCOME_BANNER)

    history = [{"role": "system", "content": args.system}]
    profile = None
    stream = not args.no_stream

    while True:
        try:
            line = input("you> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n[AgentBoot] Goodbye!")
            return 0
        if not line:
            continue

        parsed = _parse_slash(line)
        if parsed is not None:
            cmd, cargs = parsed
            profile, cont = _handle_slash(cmd, cargs, history, profile)
            if not cont:
                return 0
            continue

        history.append({"role": "user", "content": line})
        print("bot> ", end="", flush=True)
        if stream:
            parts: list[str] = []
            for delta in llm.chat_stream(history):
                print(delta, end="", flush=True)
                parts.append(delta)
            reply = "".join(parts)
            print()
        else:
            reply = llm.chat(history)
            print(reply)
        history.append({"role": "assistant", "content": reply})


# ---------------------------------------------------------------------------
# Parser construction
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="agentboot",
        description="AgentBoot — AI agent for bare-metal OS installation.",
    )
    p.add_argument("-v", "--verbose", action="store_true", help="Enable debug logging")
    sub = p.add_subparsers(dest="command", metavar="COMMAND")

    # chat
    sp = sub.add_parser("chat", help="Conversational REPL with local LLM")
    sp.add_argument("--model", type=Path, default=DEFAULT_MODEL, help="Path to GGUF model file")
    sp.add_argument("--system", type=str, default=SYSTEM_PROMPT, help="System prompt override")
    sp.add_argument("--no-stream", action="store_true", help="Disable token streaming")
    sp.set_defaults(func=cmd_chat)

    # detect
    sp = sub.add_parser("detect", help="Detect hardware (local or remote)")
    sp.add_argument("--ssh", metavar="HOST", help="Detect via SSH instead of local")
    sp.add_argument("--port", type=int, default=22, help="SSH port (default: 22)")
    sp.add_argument("--user", default="root", help="SSH user (default: root)")
    sp.add_argument("--json", action="store_true", help="Emit JSON instead of summary")
    sp.set_defaults(func=cmd_detect)

    # recommend
    sp = sub.add_parser("recommend", help="Recommend OSes for local hardware")
    sp.add_argument("--filter", help=f"Tag filter: {', '.join(_TAG_MAP)}")
    sp.add_argument("--max-results", type=int, default=10, help="Max results to consider")
    sp.add_argument("--top", type=int, default=3, help="How many to display")
    sp.add_argument("--json", action="store_true", help="Emit JSON instead of human text")
    sp.set_defaults(func=cmd_recommend)

    # list-isos
    sp = sub.add_parser("list-isos", help="Show catalogued installable OS images")
    sp.add_argument("--arch", help="Filter by arch (x86_64, arm64, …)")
    sp.add_argument("--json", action="store_true", help="Emit JSON")
    sp.set_defaults(func=cmd_list_isos)

    # download
    sp = sub.add_parser("download", help="Download + verify an ISO by catalogue ID")
    sp.add_argument("os_id", help="Catalogue ID (e.g. ubuntu-server-2404)")
    sp.add_argument("--arch", default="x86_64", help="Target arch (default: x86_64)")
    sp.add_argument("--dest", default=".", help="Destination directory")
    sp.set_defaults(func=cmd_download)

    # list-devices
    sp = sub.add_parser("list-devices", help="Enumerate removable USB devices")
    sp.add_argument("--json", action="store_true", help="Emit JSON")
    sp.set_defaults(func=cmd_list_devices)

    # flash
    sp = sub.add_parser("flash", help="Write an ISO to a USB stick (DESTRUCTIVE)")
    sp.add_argument("--iso", required=True, help="Path to the ISO file")
    sp.add_argument("--device", required=True, help="USB device ID (from list-devices)")
    sp.add_argument(
        "--yes-destroy-device",
        dest="confirm", default="",
        help="Must equal --device to actually perform the flash",
    )
    sp.set_defaults(func=cmd_flash)

    # gen-config
    sp = sub.add_parser("gen-config", help="Generate autoinstall config files")
    sp.add_argument("--os", required=True, help="OS id (ubuntu-server, debian, rhel, windows, …)")
    sp.add_argument("--user", required=True, help="Initial username")
    sp.add_argument("--password", help="Plaintext password (POSIX only; prefer --password-hash)")
    sp.add_argument("--password-hash", help="Pre-computed sha512-crypt hash ($6$…)")
    sp.add_argument("--ssh-key", action="append", help="SSH authorized_keys line (can repeat)")
    sp.add_argument("--hostname", default="agentboot-host")
    sp.add_argument("--timezone", default="UTC")
    sp.add_argument("--locale", default="en_US.UTF-8")
    sp.add_argument("--keyboard", default="us")
    sp.add_argument("--disk", default="auto", help="Target disk (e.g. /dev/sda)")
    sp.add_argument("--disk-mode", choices=("wipe", "keep"), default="wipe")
    sp.add_argument("--package", action="append", help="Extra package to install (can repeat)")
    sp.add_argument("--output", default="./autoinstall-out", help="Output directory")
    sp.set_defaults(func=cmd_gen_config)

    # session
    sp = sub.add_parser("session", help="Inspect or reset a saved install session")
    sp.add_argument("action", choices=("show", "reset"))
    sp.add_argument("--dir", default="./.agentboot-session", help="Session directory")
    sp.set_defaults(func=cmd_session)

    # install (orchestrated)
    sp = sub.add_parser("install", help="Run the full orchestrated install flow")
    sp.add_argument("--session-dir", default="./.agentboot-session", help="Session directory")
    sp.add_argument("--resume", action="store_true", help="Resume existing session if present")
    sp.add_argument("--filter", help="OS tag filter during recommend")
    sp.add_argument("--download-dir", help="Where to put the downloaded ISO")
    sp.add_argument("--device", help="USB device ID to flash to (omit to stop before flash)")
    sp.add_argument("--user", help="Autoinstall initial username")
    sp.add_argument("--password", help="Autoinstall password (POSIX hashing)")
    sp.add_argument("--password-hash", help="Pre-hashed password")
    sp.add_argument("--hostname", help="Target hostname")
    sp.set_defaults(func=cmd_install)

    return p


def main(argv: Optional[list[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    if not getattr(args, "command", None):
        parser.print_help()
        return 1

    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
