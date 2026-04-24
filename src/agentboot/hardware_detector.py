"""AgentBoot — Hardware Detection Module (M2).

Provides three detection strategies:
  1. detect_local()         — introspect the machine running AgentBoot
  2. detect_remote_ssh()    — SSH into a live remote host and gather data
  3. detect_via_usb_serial()— read a pre-collected JSON profile from a USB
                              serial port (works on bare-metal servers with
                              an IPMI/iDRAC management console or a live USB
                              that runs the companion collector script)

All strategies return a HardwareProfile dataclass that the OS recommender
and the conversational CLI can consume directly.
"""

from __future__ import annotations

import json
import logging
import platform
import re
import shutil
import subprocess
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass
class CPUInfo:
    brand: str = "unknown"
    arch: str = "unknown"          # x86_64 / arm64 / riscv64 …
    physical_cores: int = 0
    logical_cores: int = 0
    max_freq_mhz: float = 0.0
    flags: list[str] = field(default_factory=list)  # e.g. ["sse4_2", "avx2"]
    vendor: str = "unknown"


@dataclass
class RAMInfo:
    total_mb: int = 0
    available_mb: int = 0
    swap_mb: int = 0


@dataclass
class StorageDevice:
    device: str = ""
    model: str = "unknown"
    size_gb: float = 0.0
    fstype: str = ""
    mountpoint: str = ""
    is_removable: bool = False
    smart_ok: Optional[bool] = None   # None = not checked


@dataclass
class GPUInfo:
    vendor: str = "unknown"
    model: str = "unknown"
    vram_mb: int = 0
    driver: str = "unknown"


@dataclass
class NICInfo:
    name: str = ""
    mac: str = ""
    speed_mbps: Optional[int] = None
    is_wireless: bool = False


@dataclass
class HardwareProfile:
    hostname: str = "unknown"
    os_running: str = "bare-metal"   # OS on the machine at detection time
    cpu: CPUInfo = field(default_factory=CPUInfo)
    ram: RAMInfo = field(default_factory=RAMInfo)
    storage: list[StorageDevice] = field(default_factory=list)
    gpus: list[GPUInfo] = field(default_factory=list)
    nics: list[NICInfo] = field(default_factory=list)
    arch: str = "unknown"           # convenience mirror of cpu.arch
    is_virtual: bool = False
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent)

    def summary(self) -> str:
        """Human-readable one-screen summary."""
        lines = [
            f"Hostname : {self.hostname}",
            f"OS (live): {self.os_running}",
            f"Arch     : {self.arch}",
            f"Virtual  : {'yes' if self.is_virtual else 'no'}",
            "",
            "--- CPU ---",
            f"  {self.cpu.brand}",
            f"  Vendor : {self.cpu.vendor}",
            f"  Cores  : {self.cpu.physical_cores} physical / {self.cpu.logical_cores} logical",
            f"  Max MHz: {self.cpu.max_freq_mhz:.0f}",
            f"  Flags  : {', '.join(self.cpu.flags[:8])}{'...' if len(self.cpu.flags) > 8 else ''}",
            "",
            "--- RAM ---",
            f"  Total    : {self.ram.total_mb:,} MB  ({self.ram.total_mb / 1024:.1f} GB)",
            f"  Available: {self.ram.available_mb:,} MB",
            f"  Swap     : {self.ram.swap_mb:,} MB",
        ]
        if self.storage:
            lines += ["", "--- Storage ---"]
            for d in self.storage:
                lines.append(
                    f"  {d.device}: {d.model} — {d.size_gb:.1f} GB"
                    + (f"  [{d.fstype}]" if d.fstype else "")
                )
        if self.gpus:
            lines += ["", "--- GPU ---"]
            for g in self.gpus:
                vram = f"  VRAM: {g.vram_mb} MB" if g.vram_mb else ""
                lines.append(f"  {g.vendor} {g.model}{vram}")
        if self.nics:
            lines += ["", "--- NICs ---"]
            for n in self.nics:
                lines.append(
                    f"  {n.name}: {n.mac}"
                    + (" [wifi]" if n.is_wireless else "")
                    + (f"  {n.speed_mbps} Mbps" if n.speed_mbps else "")
                )
        if self.errors:
            lines += ["", "--- Detection warnings ---"]
            for e in self.errors:
                lines.append(f"  ! {e}")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _run(cmd: list[str], timeout: int = 10) -> str:
    """Run a subprocess and return stdout as a string; empty on failure."""
    try:
        r = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return r.stdout.strip()
    except Exception as exc:
        logger.debug("Command %s failed: %s", cmd, exc)
        return ""


def _cmd_exists(name: str) -> bool:
    return shutil.which(name) is not None


def _detect_virtualization() -> bool:
    """Heuristic: are we inside a VM or container?"""
    indicators = [
        "/.dockerenv",
        "/run/.containerenv",
    ]
    for p in indicators:
        if Path(p).exists():
            return True

    # systemd-detect-virt
    if _cmd_exists("systemd-detect-virt"):
        out = _run(["systemd-detect-virt"])
        return out not in ("none", "")

    # DMI table keywords (Linux)
    dmi = _run(["cat", "/sys/class/dmi/id/product_name"])
    vm_keywords = ("virtualbox", "vmware", "kvm", "qemu", "hyper-v", "xen")
    if any(k in dmi.lower() for k in vm_keywords):
        return True

    # Windows: wmic
    if sys.platform == "win32":
        out = _run(["wmic", "computersystem", "get", "model"]).lower()
        if any(k in out for k in vm_keywords):
            return True

    return False


# ---------------------------------------------------------------------------
# CPU detection
# ---------------------------------------------------------------------------


def _cpu_linux() -> CPUInfo:
    info = CPUInfo()
    try:
        import psutil  # type: ignore

        freq = psutil.cpu_freq()
        info.max_freq_mhz = freq.max if freq else 0.0
        info.logical_cores = psutil.cpu_count(logical=True) or 0
        info.physical_cores = psutil.cpu_count(logical=False) or 0
    except ImportError:
        pass

    # /proc/cpuinfo for brand & flags
    cpuinfo = Path("/proc/cpuinfo")
    if cpuinfo.exists():
        text = cpuinfo.read_text(errors="ignore")
        for line in text.splitlines():
            if "model name" in line.lower() and info.brand == "unknown":
                info.brand = line.split(":", 1)[-1].strip()
            if "vendor_id" in line.lower() and info.vendor == "unknown":
                info.vendor = line.split(":", 1)[-1].strip()
            if line.lower().startswith("flags"):
                info.flags = line.split(":", 1)[-1].strip().split()
        # architecture from uname
        info.arch = platform.machine().lower()
    return info


def _cpu_windows() -> CPUInfo:
    info = CPUInfo()
    try:
        import psutil  # type: ignore

        freq = psutil.cpu_freq()
        info.max_freq_mhz = freq.max if freq else 0.0
        info.logical_cores = psutil.cpu_count(logical=True) or 0
        info.physical_cores = psutil.cpu_count(logical=False) or 0
    except ImportError:
        pass

    out = _run(["wmic", "cpu", "get", "Name,Manufacturer,MaxClockSpeed", "/format:list"])
    for line in out.splitlines():
        if "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip().lower()
        val = val.strip()
        if key == "name":
            info.brand = val
        elif key == "manufacturer":
            info.vendor = val
        elif key == "maxclockspeed" and not info.max_freq_mhz:
            try:
                info.max_freq_mhz = float(val)
            except ValueError:
                pass

    info.arch = platform.machine().lower()
    # Normalise AMD64 → x86_64
    if info.arch in ("amd64", "x86_64"):
        info.arch = "x86_64"
    return info


def _cpu_darwin() -> CPUInfo:
    info = CPUInfo()
    try:
        import psutil  # type: ignore

        freq = psutil.cpu_freq()
        info.max_freq_mhz = freq.max if freq else 0.0
        info.logical_cores = psutil.cpu_count(logical=True) or 0
        info.physical_cores = psutil.cpu_count(logical=False) or 0
    except ImportError:
        pass

    brand = _run(["sysctl", "-n", "machdep.cpu.brand_string"])
    info.brand = brand if brand else "unknown"
    info.arch = platform.machine().lower()
    if info.arch == "arm64":
        info.vendor = "Apple"
    return info


def _detect_cpu() -> CPUInfo:
    p = sys.platform
    if p == "linux":
        cpu = _cpu_linux()
    elif p == "win32":
        cpu = _cpu_windows()
    elif p == "darwin":
        cpu = _cpu_darwin()
    else:
        cpu = CPUInfo(arch=platform.machine().lower())

    # Normalise arch
    arch = cpu.arch.lower()
    if arch in ("amd64", "x86_64"):
        cpu.arch = "x86_64"
    elif arch in ("aarch64", "arm64"):
        cpu.arch = "arm64"
    return cpu


# ---------------------------------------------------------------------------
# RAM detection
# ---------------------------------------------------------------------------


def _detect_ram(errors: list[str]) -> RAMInfo:
    try:
        import psutil  # type: ignore

        vm = psutil.virtual_memory()
        sw = psutil.swap_memory()
        return RAMInfo(
            total_mb=vm.total // (1024 * 1024),
            available_mb=vm.available // (1024 * 1024),
            swap_mb=sw.total // (1024 * 1024),
        )
    except ImportError:
        errors.append("psutil not installed — RAM detection unavailable")
    return RAMInfo()


# ---------------------------------------------------------------------------
# Storage detection
# ---------------------------------------------------------------------------


def _detect_storage(errors: list[str]) -> list[StorageDevice]:
    devices: list[StorageDevice] = []
    try:
        import psutil  # type: ignore

        seen: set[str] = set()
        for part in psutil.disk_partitions(all=False):
            dev = part.device
            if dev in seen:
                continue
            seen.add(dev)
            try:
                usage = psutil.disk_usage(part.mountpoint)
                size_gb = usage.total / (1024 ** 3)
            except PermissionError:
                size_gb = 0.0

            model = _get_disk_model(dev)
            removable = _is_removable(dev)

            devices.append(
                StorageDevice(
                    device=dev,
                    model=model,
                    size_gb=round(size_gb, 2),
                    fstype=part.fstype,
                    mountpoint=part.mountpoint,
                    is_removable=removable,
                )
            )
    except ImportError:
        errors.append("psutil not installed — storage detection unavailable")
    return devices


def _get_disk_model(device: str) -> str:
    name = Path(device).name
    # Linux sysfs
    model_path = Path(f"/sys/block/{name}/device/model")
    if model_path.exists():
        return model_path.read_text(errors="ignore").strip()
    # macOS diskutil
    if sys.platform == "darwin":
        out = _run(["diskutil", "info", device])
        for line in out.splitlines():
            if "media name" in line.lower():
                return line.split(":", 1)[-1].strip()
    # Windows
    if sys.platform == "win32":
        out = _run(["wmic", "diskdrive", "get", "Caption,DeviceID", "/format:list"])
        for line in out.splitlines():
            if line.lower().startswith("caption"):
                return line.split("=", 1)[-1].strip()
    return "unknown"


def _is_removable(device: str) -> bool:
    name = Path(device).name
    removable_path = Path(f"/sys/block/{name}/removable")
    if removable_path.exists():
        return removable_path.read_text(errors="ignore").strip() == "1"
    return False


# ---------------------------------------------------------------------------
# GPU detection
# ---------------------------------------------------------------------------


def _detect_gpus(errors: list[str]) -> list[GPUInfo]:
    gpus: list[GPUInfo] = []

    # 1. nvidia-smi (NVIDIA, all platforms)
    if _cmd_exists("nvidia-smi"):
        out = _run([
            "nvidia-smi",
            "--query-gpu=name,memory.total,driver_version",
            "--format=csv,noheader,nounits",
        ])
        for line in out.splitlines():
            parts = [p.strip() for p in line.split(",")]
            if len(parts) >= 3:
                try:
                    vram = int(parts[1])
                except ValueError:
                    vram = 0
                gpus.append(GPUInfo(vendor="NVIDIA", model=parts[0], vram_mb=vram, driver=parts[2]))

    # 2. lspci (Linux)
    if not gpus and sys.platform == "linux" and _cmd_exists("lspci"):
        out = _run(["lspci", "-mm", "-v"])
        current: dict[str, str] = {}
        for line in out.splitlines():
            if not line.strip():
                if current.get("class", "").lower() in ("vga compatible controller", "display controller", "3d controller"):
                    vendor = current.get("vendor", "unknown").strip('"')
                    model = current.get("device", "unknown").strip('"')
                    gpus.append(GPUInfo(vendor=vendor, model=model))
                current = {}
            elif ":" in line:
                k, _, v = line.partition(":")
                current[k.strip().lower()] = v.strip()

    # 3. wmic (Windows, fallback)
    if not gpus and sys.platform == "win32":
        out = _run(["wmic", "path", "win32_videocontroller", "get",
                    "Name,AdapterRAM,DriverVersion", "/format:list"])
        block: dict[str, str] = {}
        for line in out.splitlines():
            if "=" in line:
                k, _, v = line.partition("=")
                block[k.strip().lower()] = v.strip()
            elif not line.strip() and block:
                name = block.get("name", "unknown")
                try:
                    vram = int(block.get("adapterram", "0")) // (1024 * 1024)
                except ValueError:
                    vram = 0
                driver = block.get("driverversion", "unknown")
                vendor = "Intel" if "intel" in name.lower() else (
                    "AMD" if "amd" in name.lower() or "radeon" in name.lower() else "unknown"
                )
                gpus.append(GPUInfo(vendor=vendor, model=name, vram_mb=vram, driver=driver))
                block = {}

    # 4. system_profiler (macOS)
    if not gpus and sys.platform == "darwin":
        out = _run(["system_profiler", "SPDisplaysDataType"])
        for line in out.splitlines():
            if "chipset model" in line.lower():
                model = line.split(":", 1)[-1].strip()
                vendor = "Apple" if "apple" in model.lower() else (
                    "AMD" if "amd" in model.lower() or "radeon" in model.lower() else (
                        "NVIDIA" if "nvidia" in model.lower() else "Intel"
                    )
                )
                gpus.append(GPUInfo(vendor=vendor, model=model))

    return gpus


# ---------------------------------------------------------------------------
# NIC detection
# ---------------------------------------------------------------------------


def _detect_nics(errors: list[str]) -> list[NICInfo]:
    nics: list[NICInfo] = []
    try:
        import psutil  # type: ignore

        addrs = psutil.net_if_addrs()
        stats = psutil.net_if_stats()
        for name, addr_list in addrs.items():
            # skip loopback
            if name.lower() in ("lo", "loopback"):
                continue
            mac = ""
            import socket
            for addr in addr_list:
                if addr.family == psutil.AF_LINK:   # type: ignore[attr-defined]
                    mac = addr.address
            is_wireless = any(k in name.lower() for k in ("wl", "wifi", "wlan", "wi-fi", "airport"))
            speed = None
            if name in stats and stats[name].speed:
                speed = stats[name].speed
            nics.append(NICInfo(name=name, mac=mac, speed_mbps=speed, is_wireless=is_wireless))
    except ImportError:
        errors.append("psutil not installed — NIC detection unavailable")
    return nics


# ---------------------------------------------------------------------------
# SSH detection helpers
# ---------------------------------------------------------------------------


def _ssh_run(client, cmd: str) -> str:
    """Execute a command over an open Paramiko SSH client."""
    _, stdout, stderr = client.exec_command(cmd, timeout=15)
    return stdout.read().decode(errors="ignore").strip()


def _build_profile_from_ssh_output(outputs: dict[str, str]) -> HardwareProfile:
    """Parse raw command outputs collected via SSH into a HardwareProfile."""
    profile = HardwareProfile()
    profile.os_running = outputs.get("uname", "linux")
    profile.hostname = outputs.get("hostname", "unknown")

    # CPU
    cpuinfo_text = outputs.get("cpuinfo", "")
    cpu = CPUInfo()
    for line in cpuinfo_text.splitlines():
        if "model name" in line.lower() and cpu.brand == "unknown":
            cpu.brand = line.split(":", 1)[-1].strip()
        if "vendor_id" in line.lower() and cpu.vendor == "unknown":
            cpu.vendor = line.split(":", 1)[-1].strip()
        if line.lower().startswith("flags") and not cpu.flags:
            cpu.flags = line.split(":", 1)[-1].strip().split()
    cpu.arch = platform.machine().lower()
    # Try lscpu for core counts
    lscpu = outputs.get("lscpu", "")
    for line in lscpu.splitlines():
        ll = line.lower()
        if "cpu(s):" in ll and not cpu.logical_cores:
            try:
                cpu.logical_cores = int(line.split(":", 1)[-1].strip())
            except ValueError:
                pass
        if "core(s) per socket" in ll and not cpu.physical_cores:
            try:
                cpu.physical_cores = int(line.split(":", 1)[-1].strip())
            except ValueError:
                pass
        if "architecture" in ll:
            cpu.arch = line.split(":", 1)[-1].strip().lower()
        if "cpu max mhz" in ll and not cpu.max_freq_mhz:
            try:
                cpu.max_freq_mhz = float(line.split(":", 1)[-1].strip())
            except ValueError:
                pass
    profile.cpu = cpu
    profile.arch = cpu.arch

    # RAM — free -m
    free_out = outputs.get("free", "")
    for line in free_out.splitlines():
        if line.lower().startswith("mem:"):
            parts = line.split()
            try:
                profile.ram = RAMInfo(
                    total_mb=int(parts[1]),
                    available_mb=int(parts[6]) if len(parts) > 6 else 0,
                )
            except (IndexError, ValueError):
                pass
        if line.lower().startswith("swap:"):
            parts = line.split()
            try:
                profile.ram.swap_mb = int(parts[1])
            except (IndexError, ValueError):
                pass

    # Storage — lsblk
    lsblk = outputs.get("lsblk", "")
    for line in lsblk.splitlines():
        parts = line.split()
        if len(parts) >= 4 and not parts[0].startswith(("├", "└", "─")):
            name = parts[0].lstrip("─├└")
            try:
                size_gb = _parse_size_to_gb(parts[3])
            except (ValueError, IndexError):
                size_gb = 0.0
            if name:
                profile.storage.append(StorageDevice(device=f"/dev/{name}", size_gb=size_gb))

    # GPU — nvidia-smi
    nvidia = outputs.get("nvidia", "")
    for line in nvidia.splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) >= 3:
            try:
                vram = int(parts[1])
            except ValueError:
                vram = 0
            profile.gpus.append(GPUInfo(vendor="NVIDIA", model=parts[0], vram_mb=vram, driver=parts[2]))

    return profile


def _parse_size_to_gb(s: str) -> float:
    """Parse strings like '500G', '16T', '256M' into GB float."""
    s = s.strip()
    if not s:
        return 0.0
    match = re.match(r"([0-9.]+)\s*([KMGTP]?)", s, re.IGNORECASE)
    if not match:
        return float(s) / (1024 ** 3)
    value = float(match.group(1))
    unit = match.group(2).upper()
    # Convert to GB. K is kilobytes, M is megabytes, etc.
    multipliers = {
        "K": 1 / (1024 ** 2),
        "M": 1 / 1024,
        "G": 1.0,
        "T": 1024.0,
        "P": 1024 ** 2,
    }
    return value * multipliers.get(unit, 1.0)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


class HardwareDetector:
    """Detect hardware using three different strategies."""

    # ------------------------------------------------------------------
    # 1. Local detection
    # ------------------------------------------------------------------

    def detect_local(self) -> HardwareProfile:
        """Introspect the machine running AgentBoot.

        Works on Linux, Windows and macOS.
        Requires *psutil* for full RAM/storage/NIC data (installed by default).
        """
        errors: list[str] = []
        profile = HardwareProfile()

        profile.hostname = platform.node()
        profile.os_running = f"{platform.system()} {platform.release()}"
        profile.is_virtual = _detect_virtualization()

        profile.cpu = _detect_cpu()
        profile.arch = profile.cpu.arch
        profile.ram = _detect_ram(errors)
        profile.storage = _detect_storage(errors)
        profile.gpus = _detect_gpus(errors)
        profile.nics = _detect_nics(errors)
        profile.errors = errors

        return profile

    # ------------------------------------------------------------------
    # 2. Remote SSH detection
    # ------------------------------------------------------------------

    def detect_remote_ssh(
        self,
        host: str,
        port: int = 22,
        user: str = "root",
        password: str | None = None,
        key_path: str | None = None,
        timeout: int = 30,
    ) -> HardwareProfile:
        """SSH into a live remote host and gather hardware data.

        Requires ``paramiko`` (``pip install paramiko``).

        At least one of *password* or *key_path* must be provided.
        If *key_path* is None and *password* is None, paramiko will
        attempt to use the SSH agent and ~/.ssh/id_* keys.
        """
        try:
            import paramiko  # type: ignore
        except ImportError as exc:
            raise ImportError(
                "paramiko is required for SSH detection: pip install paramiko"
            ) from exc

        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

        connect_kwargs: dict = dict(
            hostname=host,
            port=port,
            username=user,
            timeout=timeout,
            allow_agent=True,
            look_for_keys=True,
        )
        if password:
            connect_kwargs["password"] = password
        if key_path:
            connect_kwargs["key_filename"] = key_path

        client.connect(**connect_kwargs)

        try:
            outputs = {
                "hostname": _ssh_run(client, "hostname"),
                "uname": _ssh_run(client, "uname -sr"),
                "cpuinfo": _ssh_run(client, "cat /proc/cpuinfo 2>/dev/null || true"),
                "lscpu": _ssh_run(client, "lscpu 2>/dev/null || true"),
                "free": _ssh_run(client, "free -m 2>/dev/null || true"),
                "lsblk": _ssh_run(client, "lsblk -d -o NAME,TYPE,SIZE 2>/dev/null || true"),
                "nvidia": _ssh_run(
                    client,
                    "nvidia-smi --query-gpu=name,memory.total,driver_version "
                    "--format=csv,noheader,nounits 2>/dev/null || true",
                ),
            }
        finally:
            client.close()

        profile = _build_profile_from_ssh_output(outputs)
        profile.hostname = host
        return profile

    # ------------------------------------------------------------------
    # 3. USB-Serial detection (bare-metal without OS)
    # ------------------------------------------------------------------

    def detect_via_usb_serial(
        self,
        port: str,
        baud: int = 115200,
        timeout: float = 30.0,
    ) -> HardwareProfile:
        """Read a JSON hardware profile from a USB serial / management port.

        Two use cases:
          a) **IPMI/iDRAC/iLO console** — some server BMCs accept a special
             ``HW_REPORT`` command and respond with a JSON blob.
          b) **Live USB companion** — boot the target from the AgentBoot live
             USB; the on-boot Python collector writes a JSON profile to the
             serial port and waits.

        The expected wire protocol is simple:
          1. AgentBoot sends ``IDENTIFY\\n``.
          2. The remote side responds with a single JSON line terminated by
             ``\\n``.

        Requires ``pyserial`` (``pip install pyserial``).
        """
        try:
            import serial  # type: ignore
        except ImportError as exc:
            raise ImportError(
                "pyserial is required for USB-serial detection: pip install pyserial"
            ) from exc

        logger.info("Opening serial port %s @ %d baud", port, baud)
        errors: list[str] = []

        with serial.Serial(port, baud, timeout=timeout) as ser:
            ser.write(b"IDENTIFY\n")
            ser.flush()

            raw = ser.readline()
            if not raw:
                errors.append(f"No response from {port} within {timeout}s")
                return HardwareProfile(os_running="bare-metal", errors=errors)

        try:
            data = json.loads(raw.decode("utf-8", errors="ignore").strip())
        except json.JSONDecodeError as exc:
            errors.append(f"Serial port returned non-JSON data: {exc}")
            return HardwareProfile(os_running="bare-metal", errors=errors)

        # Parse standardised JSON into HardwareProfile
        profile = HardwareProfile(os_running="bare-metal")
        profile.hostname = data.get("hostname", "bare-metal")
        profile.arch = data.get("arch", "unknown")
        profile.is_virtual = data.get("is_virtual", False)

        cpu_d = data.get("cpu", {})
        profile.cpu = CPUInfo(
            brand=cpu_d.get("brand", "unknown"),
            arch=cpu_d.get("arch", profile.arch),
            physical_cores=cpu_d.get("physical_cores", 0),
            logical_cores=cpu_d.get("logical_cores", 0),
            max_freq_mhz=cpu_d.get("max_freq_mhz", 0.0),
            flags=cpu_d.get("flags", []),
            vendor=cpu_d.get("vendor", "unknown"),
        )

        ram_d = data.get("ram", {})
        profile.ram = RAMInfo(
            total_mb=ram_d.get("total_mb", 0),
            available_mb=ram_d.get("available_mb", 0),
            swap_mb=ram_d.get("swap_mb", 0),
        )

        for sd in data.get("storage", []):
            profile.storage.append(
                StorageDevice(
                    device=sd.get("device", ""),
                    model=sd.get("model", "unknown"),
                    size_gb=sd.get("size_gb", 0.0),
                    fstype=sd.get("fstype", ""),
                    mountpoint=sd.get("mountpoint", ""),
                )
            )

        for gd in data.get("gpus", []):
            profile.gpus.append(
                GPUInfo(
                    vendor=gd.get("vendor", "unknown"),
                    model=gd.get("model", "unknown"),
                    vram_mb=gd.get("vram_mb", 0),
                    driver=gd.get("driver", "unknown"),
                )
            )

        for nd in data.get("nics", []):
            profile.nics.append(
                NICInfo(
                    name=nd.get("name", ""),
                    mac=nd.get("mac", ""),
                    speed_mbps=nd.get("speed_mbps"),
                    is_wireless=nd.get("is_wireless", False),
                )
            )

        profile.errors = errors
        return profile
