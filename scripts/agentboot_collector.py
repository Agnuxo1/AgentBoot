#!/usr/bin/env python3
"""AgentBoot bare-metal collector.

Runs on the *target* machine (the bare-metal server being installed)
after it has booted from a small live OS on the AgentBoot USB. Speaks
AgentBoot's JSON-over-serial protocol so the phone-side agent can:

- Request a detailed hardware report
- Stream progress events during long operations
- Receive auto-install configs written to local disk
- Trigger a reboot when the operator is ready

The script is designed to be **self-contained**: pure standard
library, no third-party deps, so it runs on any Python 3.8+ live ISO
(Ubuntu mini.iso, Alpine netboot, FreeBSD mfsBSD, etc.).

Usage on the target::

    python3 agentboot_collector.py /dev/ttyGS0
    python3 agentboot_collector.py /dev/ttyS0 --baud 115200

Over the link the phone sends a ``cmd`` frame; this script answers
with a ``response`` (or ``error``) and may emit ``event`` frames in
between for long-running commands.

Supported commands::

    hw.report                  → {"data": {HardwareProfile dict}}
    iso.write  {"path": "..."} → writes incoming base64-ish? no; not used here
    config.write {"path":"...","contents":"..."} → saves an auto-install
                                                    file on the target
    system.reboot              → schedules a reboot (default in 5s)
    system.poweroff            → schedules poweroff
    ping                       → responds with pong

This file intentionally avoids importing the ``agentboot`` package —
it must run inside a minimal live OS where the package isn't
installed. The protocol format is therefore duplicated here (kept
tiny on purpose).
"""

from __future__ import annotations

import argparse
import base64
import json
import logging
import os
import platform
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Optional

PROTO_VERSION = 1
logger = logging.getLogger("agentboot.collector")


# ---------------------------------------------------------------------------
# Minimal protocol (duplicated from agentboot.serial_link.protocol)
# ---------------------------------------------------------------------------


def _encode(obj: dict) -> bytes:
    return (json.dumps(obj, separators=(",", ":"), ensure_ascii=False) + "\n").encode("utf-8")


def _response(cmd_id: str, *, ok: bool, data: Optional[dict] = None) -> dict:
    out = {"v": PROTO_VERSION, "id": cmd_id, "kind": "response", "ok": ok}
    if data:
        out["data"] = data
    return out


def _error(cmd_id: str, code: str, message: str) -> dict:
    return {
        "v": PROTO_VERSION, "id": cmd_id, "kind": "error",
        "code": code, "message": message,
    }


def _event(name: str, data: Optional[dict] = None) -> dict:
    return {
        "v": PROTO_VERSION, "id": os.urandom(6).hex(),
        "kind": "event", "name": name, "data": data or {},
    }


# ---------------------------------------------------------------------------
# Hardware report — purely stdlib + /proc & /sys
# ---------------------------------------------------------------------------


def _read_proc(path: str) -> str:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except OSError:
        return ""


def _detect_cpu() -> dict:
    brand = ""
    vendor = ""
    flags: list[str] = []
    logical = os.cpu_count() or 0
    physical = logical
    max_mhz = 0.0

    cpuinfo = _read_proc("/proc/cpuinfo")
    if cpuinfo:
        for line in cpuinfo.splitlines():
            k, _, v = line.partition(":")
            k, v = k.strip(), v.strip()
            if not brand and k in ("model name", "Hardware", "Processor"):
                brand = v
            elif not vendor and k == "vendor_id":
                vendor = v
            elif not flags and k in ("flags", "Features"):
                flags = v.split()
    # Cores: Linux exposes siblings/cpu cores per physical id.
    if cpuinfo:
        ids = set()
        core_ids = set()
        for block in cpuinfo.split("\n\n"):
            phys_id = None
            core_id = None
            for line in block.splitlines():
                if line.startswith("physical id"):
                    phys_id = line.split(":", 1)[1].strip()
                elif line.startswith("core id"):
                    core_id = line.split(":", 1)[1].strip()
            if phys_id is not None:
                ids.add(phys_id)
                if core_id is not None:
                    core_ids.add(f"{phys_id}:{core_id}")
        if core_ids:
            physical = len(core_ids)

    # Max freq from sysfs (Linux)
    freq_path = "/sys/devices/system/cpu/cpu0/cpufreq/cpuinfo_max_freq"
    if os.path.exists(freq_path):
        try:
            max_mhz = int(_read_proc(freq_path).strip()) / 1000.0
        except ValueError:
            max_mhz = 0.0

    return {
        "brand": brand or platform.processor() or "unknown",
        "arch": platform.machine() or "unknown",
        "vendor": vendor or "unknown",
        "physical_cores": physical,
        "logical_cores": logical,
        "max_freq_mhz": max_mhz,
        "flags": flags,
    }


def _detect_ram() -> dict:
    meminfo = _read_proc("/proc/meminfo")
    total_kb = 0
    avail_kb = 0
    swap_kb = 0
    for line in meminfo.splitlines():
        if line.startswith("MemTotal:"):
            total_kb = int(line.split()[1])
        elif line.startswith("MemAvailable:"):
            avail_kb = int(line.split()[1])
        elif line.startswith("SwapTotal:"):
            swap_kb = int(line.split()[1])
    return {
        "total_mb": total_kb // 1024,
        "available_mb": avail_kb // 1024,
        "swap_mb": swap_kb // 1024,
    }


def _detect_storage() -> list[dict]:
    devices: list[dict] = []
    sys_block = Path("/sys/block")
    if not sys_block.is_dir():
        return devices
    for dev in sorted(sys_block.iterdir()):
        name = dev.name
        # Skip loops, ram disks, device-mapper — focus on real block devices.
        if name.startswith(("loop", "ram", "dm-", "sr")):
            continue
        size_sectors = 0
        try:
            size_sectors = int((dev / "size").read_text().strip())
        except (OSError, ValueError):
            pass
        model = ""
        try:
            model = (dev / "device" / "model").read_text().strip()
        except OSError:
            pass
        rotational = False
        try:
            rotational = (dev / "queue" / "rotational").read_text().strip() == "1"
        except OSError:
            pass
        devices.append({
            "device": f"/dev/{name}",
            "model": model,
            "size_gb": round(size_sectors * 512 / (1024 ** 3), 2),
            "is_ssd": not rotational,
        })
    return devices


def _detect_nics() -> list[dict]:
    nics: list[dict] = []
    sys_net = Path("/sys/class/net")
    if not sys_net.is_dir():
        return nics
    for iface in sorted(sys_net.iterdir()):
        if iface.name == "lo":
            continue
        mac = ""
        try:
            mac = (iface / "address").read_text().strip()
        except OSError:
            pass
        is_wireless = (iface / "wireless").exists()
        nics.append({"name": iface.name, "mac": mac, "is_wireless": is_wireless})
    return nics


def _detect_gpus() -> list[dict]:
    """Best-effort GPU listing via lspci. Missing lspci → empty list."""
    gpus: list[dict] = []
    try:
        out = subprocess.run(
            ["lspci", "-D", "-nn", "-mm"],
            capture_output=True, text=True, timeout=5, check=True,
        ).stdout
    except (FileNotFoundError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return gpus
    for line in out.splitlines():
        if "VGA" in line or "3D" in line or "Display" in line:
            # Very loose — the operator-side code in os_compatibility
            # only needs vendor + model strings.
            parts = line.split('"')
            vendor = parts[3] if len(parts) > 3 else ""
            model = parts[5] if len(parts) > 5 else line.strip()
            gpus.append({"vendor": vendor, "model": model})
    return gpus


def _is_virtual() -> bool:
    try:
        out = subprocess.run(
            ["systemd-detect-virt"],
            capture_output=True, text=True, timeout=2,
        ).stdout.strip()
        return out and out != "none"
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def hw_report() -> dict:
    return {
        "hostname": platform.node() or "bare-metal",
        "arch": platform.machine() or "unknown",
        "os_running": "bare-metal-live",
        "kernel": platform.release(),
        "is_virtual": _is_virtual(),
        "cpu": _detect_cpu(),
        "ram": _detect_ram(),
        "storage": _detect_storage(),
        "nics": _detect_nics(),
        "gpus": _detect_gpus(),
    }


# ---------------------------------------------------------------------------
# Command handlers
# ---------------------------------------------------------------------------


def _handle_hw_report(cmd: dict) -> dict:
    return _response(cmd["id"], ok=True, data=hw_report())


def _handle_ping(cmd: dict) -> dict:
    return _response(cmd["id"], ok=True, data={"pong": True, "ts": time.time()})


def _handle_config_write(cmd: dict) -> dict:
    data = cmd.get("data") or {}
    target = data.get("path")
    contents = data.get("contents")
    encoding = data.get("encoding", "utf-8")
    if not isinstance(target, str) or not isinstance(contents, str):
        return _error(cmd["id"], "BAD_ARGS", "path and contents (strings) are required")
    target_path = Path(target)
    try:
        target_path.parent.mkdir(parents=True, exist_ok=True)
        if encoding == "base64":
            target_path.write_bytes(base64.b64decode(contents))
        else:
            target_path.write_text(contents, encoding=encoding)
    except OSError as exc:
        return _error(cmd["id"], "WRITE_FAILED", str(exc))
    return _response(
        cmd["id"], ok=True,
        data={"path": str(target_path), "bytes": target_path.stat().st_size},
    )


def _handle_system_reboot(cmd: dict) -> dict:
    delay = int((cmd.get("data") or {}).get("delay_seconds", 5))
    try:
        subprocess.Popen(["/bin/sh", "-c", f"(sleep {delay}; reboot) &"])
    except OSError as exc:
        return _error(cmd["id"], "REBOOT_FAILED", str(exc))
    return _response(cmd["id"], ok=True, data={"reboot_in": delay})


def _handle_system_poweroff(cmd: dict) -> dict:
    delay = int((cmd.get("data") or {}).get("delay_seconds", 5))
    try:
        subprocess.Popen(["/bin/sh", "-c", f"(sleep {delay}; poweroff) &"])
    except OSError as exc:
        return _error(cmd["id"], "POWEROFF_FAILED", str(exc))
    return _response(cmd["id"], ok=True, data={"poweroff_in": delay})


_HANDLERS = {
    "hw.report":        _handle_hw_report,
    "ping":             _handle_ping,
    "config.write":     _handle_config_write,
    "system.reboot":    _handle_system_reboot,
    "system.poweroff":  _handle_system_poweroff,
}


# ---------------------------------------------------------------------------
# Serial loop
# ---------------------------------------------------------------------------


def serve(port: str, baud: int = 115200) -> None:
    try:
        import serial  # type: ignore
    except ImportError:
        sys.stderr.write(
            "pyserial not installed on the target. Install with:\n"
            "  pip install pyserial\n"
            "or use a live OS that bundles it.\n"
        )
        sys.exit(2)

    ser = serial.Serial(port, baud, timeout=None)  # block forever
    sys.stderr.write(f"AgentBoot collector listening on {port} @ {baud}\n")
    hello = _event("hello", {"protocol": PROTO_VERSION, "collector": "agentboot"})
    ser.write(_encode(hello))
    ser.flush()

    while True:
        line = ser.readline()
        if not line:
            continue
        try:
            cmd = json.loads(line.decode("utf-8", errors="replace"))
        except json.JSONDecodeError as exc:
            ser.write(_encode(_error("unknown", "BAD_FRAME", f"invalid JSON: {exc}")))
            ser.flush()
            continue
        if cmd.get("kind") != "cmd" or "name" not in cmd or "id" not in cmd:
            ser.write(_encode(_error(cmd.get("id", "unknown"), "BAD_FRAME", "not a cmd frame")))
            ser.flush()
            continue
        handler = _HANDLERS.get(cmd["name"])
        if handler is None:
            resp = _error(cmd["id"], "UNKNOWN_CMD", f"no handler for {cmd['name']}")
        else:
            try:
                resp = handler(cmd)
            except Exception as exc:  # noqa: BLE001 — last-line-of-defence log
                logger.exception("handler crashed")
                resp = _error(cmd["id"], "INTERNAL", str(exc))
        ser.write(_encode(resp))
        ser.flush()


def main(argv: Optional[list[str]] = None) -> int:
    p = argparse.ArgumentParser(description="AgentBoot bare-metal collector")
    p.add_argument("port", help="Serial device path, e.g. /dev/ttyGS0 or /dev/ttyS0")
    p.add_argument("--baud", type=int, default=115200)
    p.add_argument("--report-only", action="store_true",
                   help="Print a hardware report JSON to stdout and exit.")
    args = p.parse_args(argv)

    if args.report_only:
        json.dump(hw_report(), sys.stdout, indent=2)
        sys.stdout.write("\n")
        return 0

    try:
        serve(args.port, args.baud)
    except KeyboardInterrupt:
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
