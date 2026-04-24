"""Actual dd-style ISO → block-device write with layered safety checks.

Writing to the wrong device destroys data. Every call therefore goes
through a two-step ritual:

1. :func:`plan_flash` collects the source ISO and target device,
   computes the checks, and returns a :class:`FlashPlan`. It raises
   :class:`FlashError` if anything is off (target too small, system
   disk, currently-mounted filesystem, etc.).
2. :func:`flash_iso` takes the plan plus a caller-supplied
   ``confirm_token`` that must equal the target's :attr:`UsbDevice.id`.
   Only then does it open the device and stream the bytes.

The write is chunked (4 MiB) and calls the supplied progress
callback after every chunk. On Linux/macOS we ``fsync`` at the end;
on Windows, ``os.fsync`` on a raw device handle is a best-effort
no-op, so we flush the Python buffer and trust the OS.
"""

from __future__ import annotations

import logging
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

from agentboot.flasher.enumerate import UsbDevice, find_device_by_id

logger = logging.getLogger(__name__)


FLASH_CHUNK = 4 * 1024 * 1024  # 4 MiB


class FlashError(RuntimeError):
    """Raised by :func:`plan_flash` / :func:`flash_iso` to abort a write."""


@dataclass
class FlashPlan:
    source_iso: Path
    target: UsbDevice
    iso_size_bytes: int

    def human_summary(self) -> str:
        return (
            f"Source: {self.source_iso} ({self.iso_size_bytes/1e9:.2f} GB)\n"
            f"Target: {self.target.describe()}\n"
            f"Target mounts: {', '.join(self.target.mount_points) or '(none)'}"
        )


@dataclass
class FlashProgress:
    bytes_written: int
    total_bytes: int

    @property
    def fraction(self) -> float:
        if not self.total_bytes:
            return 0.0
        return min(1.0, self.bytes_written / self.total_bytes)


@dataclass
class FlashResult:
    target_path: str
    bytes_written: int


ProgressCallback = Callable[[FlashProgress], None]


# ---------------------------------------------------------------------------
# Planning
# ---------------------------------------------------------------------------


def plan_flash(source_iso: str | Path, target: UsbDevice) -> FlashPlan:
    """Validate inputs and return a :class:`FlashPlan`, or raise :class:`FlashError`."""
    src = Path(source_iso)
    if not src.is_file():
        raise FlashError(f"Source ISO does not exist: {src}")
    size = src.stat().st_size
    if size == 0:
        raise FlashError(f"Source ISO is empty: {src}")

    if target.is_system_disk:
        raise FlashError(
            f"Refusing to flash onto the system disk ({target.device_path}). "
            "Disconnect this drive from the installer or pick a different target."
        )

    if not target.removable:
        raise FlashError(
            f"{target.device_path} is not marked removable. AgentBoot refuses to "
            "flash internal drives — use the OS tooling directly if that is really "
            "your intent."
        )

    if target.size_bytes == 0:
        raise FlashError(
            f"Could not determine size of {target.device_path}; aborting."
        )
    if target.size_bytes < size:
        raise FlashError(
            f"Target too small: {src} is {size/1e9:.2f} GB, "
            f"device has {target.size_gb:.2f} GB."
        )

    if target.mount_points:
        raise FlashError(
            f"{target.device_path} has currently-mounted partitions: "
            f"{', '.join(target.mount_points)}. "
            "Unmount them (Linux: umount; macOS: diskutil unmountDisk; "
            "Windows: right-click → Eject) and retry."
        )

    return FlashPlan(source_iso=src, target=target, iso_size_bytes=size)


# ---------------------------------------------------------------------------
# Writing
# ---------------------------------------------------------------------------


def _open_raw_block_device(path: str):
    r"""Open the device for unbuffered binary write.

    On POSIX we open with ``O_WRONLY | O_SYNC`` so the kernel does
    not silently buffer gigabytes. On Windows a normal binary open
    on ``\\.\PhysicalDriveN`` is sufficient — the NT kernel already
    writes through for raw device handles.
    """
    if sys.platform == "win32":
        # Windows: open raw physical drive. Requires admin.
        return open(path, "r+b", buffering=0)
    flags = os.O_WRONLY | getattr(os, "O_SYNC", 0)
    fd = os.open(path, flags)
    return os.fdopen(fd, "wb", buffering=0)


def flash_iso(
    plan: FlashPlan,
    confirm_token: str,
    progress: Optional[ProgressCallback] = None,
    _open_target: Optional[Callable[[str], object]] = None,
) -> FlashResult:
    """Write ``plan.source_iso`` to ``plan.target``.

    The caller must pass ``confirm_token`` equal to ``plan.target.id``.
    The token exists so that a higher-level CLI or UI cannot accept a
    user's "yes" without also echoing the exact device identifier the
    user intended to destroy — mitigating copy/paste-a-wrong-device
    mistakes.

    ``_open_target`` is an injection seam for tests: it receives the
    device path and must return a file-like object opened for binary
    writing. Production code leaves it as ``None`` to go through
    :func:`_open_raw_block_device`.
    """
    if confirm_token != plan.target.id:
        raise FlashError(
            f"confirm_token {confirm_token!r} does not match target id "
            f"{plan.target.id!r}; aborting as a safety measure."
        )

    # Re-check that the device still looks like we expect. Someone may
    # have inserted another stick between `plan_flash()` and now.
    current = find_device_by_id(plan.target.id)
    if current is None:
        logger.warning(
            "Could not re-enumerate device %s at flash time — proceeding "
            "with original plan.", plan.target.id,
        )
    else:
        if current.is_system_disk or not current.removable or current.mount_points:
            raise FlashError(
                f"Device {plan.target.id} changed state between plan and flash; "
                "aborting. Re-plan to pick up the new state."
            )

    opener = _open_target or _open_raw_block_device
    written = 0
    total = plan.iso_size_bytes

    with open(plan.source_iso, "rb") as src:
        tgt = opener(plan.target.device_path)
        try:
            while True:
                chunk = src.read(FLASH_CHUNK)
                if not chunk:
                    break
                tgt.write(chunk)
                written += len(chunk)
                if progress is not None:
                    progress(FlashProgress(bytes_written=written, total_bytes=total))
            flush = getattr(tgt, "flush", None)
            if callable(flush):
                flush()
            fileno = getattr(tgt, "fileno", None)
            if callable(fileno):
                try:
                    os.fsync(fileno())
                except (OSError, ValueError):
                    # Regular files in tests don't always support fsync;
                    # raw Windows devices don't either. Best-effort.
                    pass
        finally:
            close = getattr(tgt, "close", None)
            if callable(close):
                close()

    return FlashResult(target_path=plan.target.device_path, bytes_written=written)
