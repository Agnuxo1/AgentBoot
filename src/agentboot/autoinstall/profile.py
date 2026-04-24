"""Shared data model consumed by every auto-install generator.

The profile abstracts over the common vocabulary of bare-metal
installers: a user account, a disk layout, a network config, a
hostname and timezone. Generator-specific knobs (preseed ``d-i`` keys,
kickstart ``%packages`` sections, cloud-init ``runcmd``) are exposed
via passthrough fields so callers can layer detail without forking
the generator.
"""

from __future__ import annotations

import secrets
import sys
from dataclasses import dataclass, field
from typing import Literal, Optional


@dataclass
class User:
    """Initial user account to create during installation.

    ``password_hash`` is the preferred input — pass an already-hashed
    value (``mkpasswd -m sha-512``, ``openssl passwd -6``, etc.).
    ``password`` is a convenience for development: on POSIX hosts it
    is hashed via :mod:`crypt`; on Windows, where :mod:`crypt` is
    absent, plaintext ``password`` raises :class:`ValueError` — the
    caller must supply ``password_hash`` instead.
    """

    username: str
    password: Optional[str] = None
    password_hash: Optional[str] = None
    ssh_authorized_keys: list[str] = field(default_factory=list)
    sudo: bool = True
    shell: str = "/bin/bash"

    def resolve_password_hash(self) -> str:
        if self.password_hash:
            return self.password_hash
        if self.password is None:
            raise ValueError(
                f"User {self.username!r}: either password or password_hash is required."
            )
        return _sha512_crypt(self.password)


@dataclass
class DiskLayout:
    """High-level disk layout hint.

    ``mode="wipe"`` lets the installer take the whole disk; ``"keep"``
    preserves existing partitions (for dual boot / reinstallation).
    Advanced partitioning is delegated to the generator-specific raw
    fields in :class:`InstallProfile`.
    """

    target: str = "auto"              # "auto", "/dev/sda", "\\Disk 0"
    mode: Literal["wipe", "keep"] = "wipe"
    filesystem: str = "ext4"          # cloud-init: "ext4", "xfs", "btrfs"
    swap_gb: int = 2
    use_lvm: bool = False
    encrypt: bool = False
    encryption_passphrase: Optional[str] = None


@dataclass
class NetworkConfig:
    hostname: str = "agentboot-host"
    dhcp: bool = True
    static_ip: Optional[str] = None        # "192.168.1.50/24"
    gateway: Optional[str] = None
    dns: list[str] = field(default_factory=lambda: ["1.1.1.1", "9.9.9.9"])


@dataclass
class GeneratedFile:
    """Represents a single file to be emitted on an install media."""

    path: str                 # Relative install-media path, e.g. "nocloud/user-data"
    contents: str
    mode: int = 0o644
    encoding: str = "utf-8"

    @property
    def body_bytes(self) -> bytes:
        return self.contents.encode(self.encoding) if self.encoding else b""


@dataclass
class InstallProfile:
    """The inputs to every generator."""

    user: User
    disk: DiskLayout = field(default_factory=DiskLayout)
    network: NetworkConfig = field(default_factory=NetworkConfig)
    timezone: str = "UTC"
    locale: str = "en_US.UTF-8"
    keyboard: str = "us"
    packages: list[str] = field(default_factory=list)
    runcmd: list[str] = field(default_factory=list)
    reboot_when_done: bool = True
    # Generator-specific passthrough — only used by that generator.
    extra_cloud_init: dict = field(default_factory=dict)
    extra_preseed: dict = field(default_factory=dict)
    extra_kickstart: dict = field(default_factory=dict)
    extra_unattend: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Password hashing
# ---------------------------------------------------------------------------


def _sha512_crypt(password: str) -> str:
    """Compute a SHA-512 crypt(3) hash of ``password`` (``$6$...`` format).

    Uses :mod:`crypt` when present (all POSIX Pythons ship it). On
    Windows, where the module is not available, raises
    :class:`NotImplementedError` so callers can surface a clear
    message: either run AgentBoot from WSL / Linux, or pass a
    pre-computed ``password_hash``.
    """
    if sys.platform == "win32":
        raise NotImplementedError(
            "Automatic password hashing requires POSIX crypt(3), which "
            "Windows does not provide. Pass User(password_hash=...) — "
            "generate the hash with e.g. `openssl passwd -6 yourpassword` "
            "on any Linux host or WSL, or via an online crypt generator."
        )
    try:
        import crypt  # type: ignore[import]
    except ImportError as exc:
        raise NotImplementedError(
            "Python's `crypt` module is not available on this platform. "
            "Pass User(password_hash=...) explicitly."
        ) from exc
    salt = secrets.token_hex(8)
    return crypt.crypt(password, f"$6${salt}$")
