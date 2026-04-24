"""Auto-install configuration generators.

Four formats in scope — they are the ones covering ~95% of real
bare-metal installs today:

- **cloud-init** (``user-data`` + ``meta-data``) — Ubuntu Server
  subiquity (22.04+) autoinstall, Fedora CoreOS, RHEL 9 kickstart-
  compatible mode, most modern cloud images.
- **Debian preseed** — Debian 10–12 and older Ubuntu (≤20.04).
- **Red Hat kickstart** — RHEL / CentOS / Rocky / AlmaLinux.
- **Windows unattend.xml** — Server 2016/2019/2022 and Windows 10/11.

All generators take the same :class:`InstallProfile` dataclass and
return a list of :class:`GeneratedFile` describing (path, mode,
contents). The caller decides where to place the files (ISO overlay,
secondary partition on the USB, HTTP seed URL, etc.).
"""

from __future__ import annotations

from agentboot.autoinstall.profile import (
    DiskLayout,
    GeneratedFile,
    InstallProfile,
    NetworkConfig,
    User,
)
from agentboot.autoinstall.generators import (
    generate_cloud_init,
    generate_preseed,
    generate_kickstart,
    generate_windows_unattend,
    generate_for_os,
)

__all__ = [
    "DiskLayout",
    "GeneratedFile",
    "InstallProfile",
    "NetworkConfig",
    "User",
    "generate_cloud_init",
    "generate_preseed",
    "generate_kickstart",
    "generate_windows_unattend",
    "generate_for_os",
]
