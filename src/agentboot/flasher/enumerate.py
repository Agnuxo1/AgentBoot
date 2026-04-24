r"""Cross-platform USB / removable block device enumeration.

Platform strategies:

- **Linux**: parse ``lsblk -J -o NAME,SIZE,RM,TYPE,MOUNTPOINT,VENDOR,MODEL``.
  The ``RM`` (removable) flag and the absence of a mounted child
  partition on the root filesystem are our primary safety signals.
- **Windows**: query WMI ``Win32_DiskDrive`` via ``powershell -Command``.
  ``InterfaceType='USB'`` or ``MediaType`` hints at a removable
  device. We expose ``\\.\PhysicalDriveN`` as the write path.
- **macOS**: ``diskutil list -plist external`` enumerates non-system
  disks; device paths are ``/dev/diskN``.

Only candidates believed to be removable are returned. Callers MUST
still run :func:`plan_flash` before writing; enumeration is an
information source, not authorisation.
"""

from __future__ import annotations

import json
import logging
import plistlib
import subprocess
import sys
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class UsbDevice:
    """Abstract representation of a candidate removable block device.

    Attributes
    ----------
    id:
        Platform-specific stable identifier. On Linux this is the
        kernel device name (``sdb``); on Windows it's the physical
        drive index as a string (``"2"``); on macOS it's the disk id
        (``disk3``). Used as the confirmation token when flashing.
    device_path:
        OS-native path suitable for opening with :func:`open`. On
        Windows this is ``\\.\\PhysicalDrive2``; on Linux ``/dev/sdb``;
        on macOS ``/dev/rdiskN`` (raw disk, much faster than the
        buffered ``/dev/diskN``).
    size_bytes:
        Total capacity. ``0`` if the OS could not report it.
    vendor, model:
        Vendor and model strings, best-effort.
    removable:
        True if the OS marks the device as removable. Enumeration
        already filters to likely-removable devices, but this flag
        lets callers double-check.
    is_system_disk:
        True if this device hosts the running OS. The flasher refuses
        to write to such devices.
    mount_points:
        Paths where partitions of this device are currently mounted.
    """

    id: str
    device_path: str
    size_bytes: int
    vendor: str
    model: str
    removable: bool
    is_system_disk: bool
    mount_points: tuple[str, ...] = ()

    @property
    def size_gb(self) -> float:
        return self.size_bytes / (1024 ** 3)

    def describe(self) -> str:
        return (
            f"{self.id}  {self.vendor} {self.model}".strip()
            + f"  {self.size_gb:.1f} GB  [{self.device_path}]"
        )


# ---------------------------------------------------------------------------
# Linux
# ---------------------------------------------------------------------------


def _enumerate_linux() -> list[UsbDevice]:
    try:
        out = subprocess.run(
            ["lsblk", "-J", "-b", "-o", "NAME,SIZE,RM,TYPE,MOUNTPOINT,VENDOR,MODEL"],
            capture_output=True, text=True, check=True, timeout=10,
        )
    except (FileNotFoundError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        logger.warning("lsblk unavailable or failed: %s", exc)
        return []

    try:
        data = json.loads(out.stdout)
    except json.JSONDecodeError:
        return []

    root_mount_device: Optional[str] = None
    try:
        # Find what / is mounted on by reading /proc/mounts
        with open("/proc/mounts", encoding="utf-8") as f:
            for line in f:
                parts = line.split()
                if len(parts) >= 2 and parts[1] == "/":
                    root_mount_device = parts[0]
                    break
    except OSError:
        root_mount_device = None

    devices: list[UsbDevice] = []
    for dev in data.get("blockdevices", []):
        if dev.get("type") != "disk":
            continue
        removable = bool(int(dev.get("rm", 0) or 0))
        name = dev.get("name", "")
        path = f"/dev/{name}"

        mounts: list[str] = []
        is_system = False
        for child in dev.get("children") or []:
            mp = child.get("mountpoint")
            if mp:
                mounts.append(mp)
            child_path = f"/dev/{child.get('name','')}"
            if root_mount_device and root_mount_device.startswith(child_path):
                is_system = True
        if root_mount_device and root_mount_device.startswith(path):
            is_system = True

        # Only surface removable drives OR clearly-not-system disks.
        if not removable and is_system:
            continue
        if not removable:
            # Internal non-removable drive — omit from enumeration to
            # reduce risk. Callers that need raw access go to the OS
            # directly.
            continue

        devices.append(UsbDevice(
            id=name,
            device_path=path,
            size_bytes=int(dev.get("size") or 0),
            vendor=(dev.get("vendor") or "").strip(),
            model=(dev.get("model") or "").strip(),
            removable=removable,
            is_system_disk=is_system,
            mount_points=tuple(mounts),
        ))

    return devices


# ---------------------------------------------------------------------------
# Windows
# ---------------------------------------------------------------------------


_WINDOWS_PS_SCRIPT = r"""
$ErrorActionPreference = 'Stop'
$sys = (Get-CimInstance Win32_OperatingSystem).SystemDrive
$sysVolume = Get-CimInstance Win32_Volume | Where-Object { $_.DriveLetter -eq $sys }
$disks = Get-CimInstance Win32_DiskDrive
$result = @()
foreach ($d in $disks) {
    $parts = Get-CimAssociatedInstance -InputObject $d -ResultClassName Win32_DiskPartition
    $mounts = @()
    $isSystem = $false
    foreach ($p in $parts) {
        $logs = Get-CimAssociatedInstance -InputObject $p -ResultClassName Win32_LogicalDisk
        foreach ($l in $logs) {
            $mounts += $l.DeviceID
            if ($l.DeviceID -eq $sys) { $isSystem = $true }
        }
    }
    $result += [PSCustomObject]@{
        Index          = $d.Index
        DeviceID       = $d.DeviceID
        Size           = [int64]($d.Size)
        Model          = $d.Model
        InterfaceType  = $d.InterfaceType
        MediaType      = $d.MediaType
        Mounts         = $mounts
        IsSystemDisk   = $isSystem
    }
}
$result | ConvertTo-Json -Depth 3 -Compress
"""


def _enumerate_windows() -> list[UsbDevice]:
    try:
        proc = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", _WINDOWS_PS_SCRIPT],
            capture_output=True, text=True, check=True, timeout=30,
        )
    except (FileNotFoundError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        logger.warning("PowerShell WMI query failed: %s", exc)
        return []

    raw = proc.stdout.strip()
    if not raw:
        return []
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return []
    if isinstance(data, dict):
        data = [data]

    devices: list[UsbDevice] = []
    for d in data:
        iface = (d.get("InterfaceType") or "").upper()
        media = (d.get("MediaType") or "")
        # Accept only USB or explicit "Removable Media" reports.
        is_removable = iface == "USB" or "Removable" in media
        if not is_removable:
            continue
        if d.get("IsSystemDisk"):
            continue
        mounts = tuple(d.get("Mounts") or ())
        idx = str(d.get("Index", ""))
        devices.append(UsbDevice(
            id=idx,
            device_path=d.get("DeviceID") or fr"\\.\PhysicalDrive{idx}",
            size_bytes=int(d.get("Size") or 0),
            vendor="",
            model=(d.get("Model") or "").strip(),
            removable=True,
            is_system_disk=bool(d.get("IsSystemDisk")),
            mount_points=mounts,
        ))
    return devices


# ---------------------------------------------------------------------------
# macOS
# ---------------------------------------------------------------------------


def _enumerate_macos() -> list[UsbDevice]:
    try:
        proc = subprocess.run(
            ["diskutil", "list", "-plist", "external"],
            capture_output=True, check=True, timeout=10,
        )
    except (FileNotFoundError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        logger.warning("diskutil failed: %s", exc)
        return []

    try:
        plist = plistlib.loads(proc.stdout)
    except Exception:
        return []

    devices: list[UsbDevice] = []
    for disk_id in plist.get("WholeDisks", []):
        try:
            info_proc = subprocess.run(
                ["diskutil", "info", "-plist", disk_id],
                capture_output=True, check=True, timeout=10,
            )
            info = plistlib.loads(info_proc.stdout)
        except Exception:
            continue

        # "Internal" True → skip. "SystemImage" / "VirtualOrPhysical" set by OS.
        if info.get("Internal") is True:
            continue
        if info.get("SystemImage") is True:
            continue

        size = int(info.get("TotalSize") or 0)
        model = info.get("MediaName") or info.get("IORegistryEntryName") or ""
        # /dev/rdiskN is the raw (unbuffered) counterpart; flashing to
        # it is an order of magnitude faster than /dev/diskN.
        raw_path = f"/dev/r{disk_id}"
        devices.append(UsbDevice(
            id=disk_id,
            device_path=raw_path,
            size_bytes=size,
            vendor=(info.get("DeviceVendor") or "").strip(),
            model=str(model).strip(),
            removable=not info.get("Internal", False),
            is_system_disk=False,
            mount_points=(),
        ))
    return devices


# ---------------------------------------------------------------------------
# Public dispatcher
# ---------------------------------------------------------------------------


def enumerate_usb_devices() -> list[UsbDevice]:
    """Return a list of candidate removable block devices.

    Never raises — returns an empty list if the OS-specific tool is
    missing or refuses to cooperate. Root / admin may be required on
    some platforms for full information.
    """
    if sys.platform.startswith("linux"):
        return _enumerate_linux()
    if sys.platform == "win32":
        return _enumerate_windows()
    if sys.platform == "darwin":
        return _enumerate_macos()
    logger.warning("Unsupported platform for USB enumeration: %s", sys.platform)
    return []


def find_device_by_id(device_id: str) -> Optional[UsbDevice]:
    """Look up an enumerated device by its :attr:`UsbDevice.id`."""
    for d in enumerate_usb_devices():
        if d.id == device_id:
            return d
    return None
