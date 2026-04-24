"""ISO catalogue.

Each entry points to a real, currently-published installer image and,
when available, to the vendor's signed *SHA256SUMS* file. We do **not**
hardcode per-release hashes: they rot whenever the vendor ships a point
release, and stale hashes would make the downloader falsely report
corruption. Instead the downloader fetches the vendor's checksum file
at download time and parses out the matching filename.

Entries are intentionally curated (not exhaustive) — only distributions
we can validate end-to-end, across the architectures we actually
support in :mod:`agentboot.os_compatibility`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass(frozen=True)
class IsoEntry:
    """A single installable OS image.

    Attributes
    ----------
    id:
        Stable identifier (e.g. ``"ubuntu-server-2404"``). Matches the
        ``id`` field in :data:`agentboot.os_compatibility.OS_CATALOG`.
    name:
        Human-readable display name.
    arch:
        CPU architecture this URL targets (``x86_64``, ``arm64``, …).
    url:
        Direct HTTPS URL to the ISO.
    size_gb:
        Approximate on-disk size. Used for UI display and free-space
        pre-checks, not for correctness.
    checksum_url:
        Optional URL to a ``SHA256SUMS`` (or ``*.sha256``) file that
        contains an entry for this ISO. The downloader will fetch it
        and parse out the hash by matching ``checksum_filename``.
    checksum_filename:
        Exact filename as it appears in the SHA256SUMS file. If
        *None*, the basename of :attr:`url` is used.
    """

    id: str
    name: str
    arch: str
    url: str
    size_gb: float
    checksum_url: Optional[str] = None
    checksum_filename: Optional[str] = None
    notes: str = ""

    @property
    def filename(self) -> str:
        """The filename the ISO will be saved as (from the URL path)."""
        return self.url.rsplit("/", 1)[-1]


# ---------------------------------------------------------------------------
# Curated catalogue
# ---------------------------------------------------------------------------
#
# Kept short on purpose: every entry must point at a real, still-live
# installer image that the project's maintainers can re-verify. Add
# entries sparingly — stale URLs cause silent confusion.

ISO_CATALOG: list[IsoEntry] = [
    # -------------------------------------------------------------------
    # Ubuntu Server 24.04 LTS
    # -------------------------------------------------------------------
    IsoEntry(
        id="ubuntu-server-2404",
        name="Ubuntu Server 24.04 LTS",
        arch="x86_64",
        url="https://releases.ubuntu.com/24.04/ubuntu-24.04.3-live-server-amd64.iso",
        size_gb=3.2,
        checksum_url="https://releases.ubuntu.com/24.04/SHA256SUMS",
        checksum_filename="ubuntu-24.04.3-live-server-amd64.iso",
    ),
    IsoEntry(
        id="ubuntu-server-2404",
        name="Ubuntu Server 24.04 LTS",
        arch="arm64",
        url="https://cdimage.ubuntu.com/releases/24.04/release/ubuntu-24.04.3-live-server-arm64.iso",
        size_gb=2.9,
        checksum_url="https://cdimage.ubuntu.com/releases/24.04/release/SHA256SUMS",
        checksum_filename="ubuntu-24.04.3-live-server-arm64.iso",
    ),
    # -------------------------------------------------------------------
    # Debian 12
    # -------------------------------------------------------------------
    IsoEntry(
        id="debian-12",
        name="Debian 12 Bookworm (netinst)",
        arch="x86_64",
        url="https://cdimage.debian.org/debian-cd/current/amd64/iso-cd/debian-12.11.0-amd64-netinst.iso",
        size_gb=0.7,
        checksum_url="https://cdimage.debian.org/debian-cd/current/amd64/iso-cd/SHA256SUMS",
        checksum_filename="debian-12.11.0-amd64-netinst.iso",
        notes="Point release changes with every Debian update; catalog "
              "should be refreshed when upstream rolls a new 12.x ISO.",
    ),
    IsoEntry(
        id="debian-12",
        name="Debian 12 Bookworm (netinst)",
        arch="arm64",
        url="https://cdimage.debian.org/debian-cd/current/arm64/iso-cd/debian-12.11.0-arm64-netinst.iso",
        size_gb=0.4,
        checksum_url="https://cdimage.debian.org/debian-cd/current/arm64/iso-cd/SHA256SUMS",
        checksum_filename="debian-12.11.0-arm64-netinst.iso",
    ),
    # -------------------------------------------------------------------
    # Alpine Linux 3.20
    # -------------------------------------------------------------------
    IsoEntry(
        id="alpine-320",
        name="Alpine Linux 3.20 (standard)",
        arch="x86_64",
        url="https://dl-cdn.alpinelinux.org/alpine/v3.20/releases/x86_64/alpine-standard-3.20.3-x86_64.iso",
        size_gb=0.2,
        checksum_url="https://dl-cdn.alpinelinux.org/alpine/v3.20/releases/x86_64/alpine-standard-3.20.3-x86_64.iso.sha256",
    ),
    IsoEntry(
        id="alpine-320",
        name="Alpine Linux 3.20 (standard)",
        arch="arm64",
        url="https://dl-cdn.alpinelinux.org/alpine/v3.20/releases/aarch64/alpine-standard-3.20.3-aarch64.iso",
        size_gb=0.2,
        checksum_url="https://dl-cdn.alpinelinux.org/alpine/v3.20/releases/aarch64/alpine-standard-3.20.3-aarch64.iso.sha256",
    ),
    # -------------------------------------------------------------------
    # Proxmox VE 8
    # -------------------------------------------------------------------
    IsoEntry(
        id="proxmox-ve-8",
        name="Proxmox VE 8.2",
        arch="x86_64",
        url="https://enterprise.proxmox.com/iso/proxmox-ve_8.2-2.iso",
        size_gb=1.5,
        notes="Proxmox publishes checksums on their news page rather than "
              "a machine-readable SHA256SUMS; pass --sha256 explicitly.",
    ),
    # -------------------------------------------------------------------
    # TrueNAS SCALE
    # -------------------------------------------------------------------
    IsoEntry(
        id="truenas-scale",
        name="TrueNAS SCALE 24.04 Dragonfish",
        arch="x86_64",
        url="https://download.sys.truenas.net/TrueNAS-SCALE-Dragonfish/24.04.2.3/TrueNAS-SCALE-24.04.2.3.iso",
        size_gb=1.3,
    ),
    # -------------------------------------------------------------------
    # OPNsense (firewall)
    # -------------------------------------------------------------------
    IsoEntry(
        id="opnsense-24",
        name="OPNsense 24.7",
        arch="x86_64",
        url="https://pkg.opnsense.org/releases/24.7/OPNsense-24.7-dvd-amd64.iso.bz2",
        size_gb=0.5,
        notes="Compressed image — downloader stores the .bz2; decompress "
              "before flashing.",
    ),
    # -------------------------------------------------------------------
    # FreeBSD 14
    # -------------------------------------------------------------------
    IsoEntry(
        id="freebsd-14",
        name="FreeBSD 14.1-RELEASE (disc1)",
        arch="x86_64",
        url="https://download.freebsd.org/releases/ISO-IMAGES/14.1/FreeBSD-14.1-RELEASE-amd64-disc1.iso",
        size_gb=1.1,
        checksum_url="https://download.freebsd.org/releases/ISO-IMAGES/14.1/CHECKSUM.SHA256-FreeBSD-14.1-RELEASE-amd64",
        checksum_filename="FreeBSD-14.1-RELEASE-amd64-disc1.iso",
    ),
]


# ---------------------------------------------------------------------------
# Lookup helpers
# ---------------------------------------------------------------------------


def find_iso(os_id: str, arch: str = "x86_64") -> Optional[IsoEntry]:
    """Return the catalogue entry for ``os_id`` on ``arch``, or ``None``.

    Architecture matching is strict (no aliasing: ``x86_64`` and
    ``amd64`` are *not* treated as the same). Callers that want to
    accept multiple aliases should canonicalise beforehand.
    """
    for entry in ISO_CATALOG:
        if entry.id == os_id and entry.arch == arch:
            return entry
    return None


def list_isos_for_arch(arch: str) -> list[IsoEntry]:
    """Return all catalogue entries available for the given architecture."""
    return [e for e in ISO_CATALOG if e.arch == arch]
