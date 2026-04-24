"""USB bootable-media flasher.

Writing an ISO image to the wrong block device destroys the data on
that device and can brick a running system if it happens to be the
boot disk. This subpackage therefore splits concerns:

- :mod:`enumerate` discovers candidate USB block devices per OS.
- :mod:`flash` performs the actual write *only* after a battery of
  safety checks (removable bit, not the system disk, user-supplied
  confirmation token matches the device id).

The flasher never silently assumes it may write to a device.
"""

from __future__ import annotations

from agentboot.flasher.enumerate import (
    UsbDevice,
    enumerate_usb_devices,
    find_device_by_id,
)
from agentboot.flasher.flash import (
    FlashError,
    FlashPlan,
    FlashProgress,
    FlashResult,
    flash_iso,
    plan_flash,
)

__all__ = [
    "UsbDevice",
    "enumerate_usb_devices",
    "find_device_by_id",
    "FlashError",
    "FlashPlan",
    "FlashProgress",
    "FlashResult",
    "flash_iso",
    "plan_flash",
]
