"""ISO catalogue and downloader.

This subpackage knows *where* installable OS images live, *how big*
they are, and *how to verify* them. It is deliberately decoupled
from :mod:`agentboot.os_compatibility` which only decides *which*
OS fits a given machine.

Public API::

    from agentboot.iso import find_iso, download_iso, verify_sha256
"""

from __future__ import annotations

from agentboot.iso.catalog import (
    IsoEntry,
    ISO_CATALOG,
    find_iso,
    list_isos_for_arch,
)
from agentboot.iso.downloader import (
    DownloadProgress,
    DownloadResult,
    download_iso,
    fetch_expected_sha256,
    verify_sha256,
    ChecksumMismatch,
)

__all__ = [
    "IsoEntry",
    "ISO_CATALOG",
    "find_iso",
    "list_isos_for_arch",
    "DownloadProgress",
    "DownloadResult",
    "download_iso",
    "fetch_expected_sha256",
    "verify_sha256",
    "ChecksumMismatch",
]
