"""Resumable HTTP(S) downloader with SHA256 verification.

The downloader is deliberately dependency-free (``urllib`` only) so
the core install pipeline does not require ``requests`` or ``aiohttp``.
It supports:

- **Resume** via HTTP ``Range`` requests. If the server returns
  ``206 Partial Content``, the existing bytes are kept and we append.
  If the server replies ``200 OK`` to our range request, it does not
  support resume; we restart the file from scratch.
- **SHA256 verification**. If an expected hash is supplied (either
  directly or via :func:`fetch_expected_sha256`), the final file is
  verified and :class:`ChecksumMismatch` is raised on failure.
- **Progress callback** so callers can render a progress bar without
  the downloader having to know about TTYs.
"""

from __future__ import annotations

import hashlib
import logging
import os
import re
import shutil
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

logger = logging.getLogger(__name__)

# 1 MiB — a good balance between syscall overhead and progress granularity.
CHUNK_SIZE = 1024 * 1024

# Conservative default; some vendor mirrors (cdimage.debian.org, FreeBSD)
# can stall for ~30s while routing.
DEFAULT_TIMEOUT = 60.0

USER_AGENT = "AgentBoot/0.3 (+https://github.com/Agnuxo1/AgentBoot)"


from agentboot._errors import AgentBootError


class ChecksumMismatch(AgentBootError, RuntimeError):
    """Raised when a downloaded file's SHA256 does not match the expected value."""


@dataclass
class DownloadProgress:
    """Snapshot of an in-progress download, passed to the progress callback."""

    downloaded_bytes: int
    total_bytes: Optional[int]  # None when the server didn't advertise Content-Length
    url: str
    destination: Path

    @property
    def fraction(self) -> Optional[float]:
        if not self.total_bytes:
            return None
        return min(1.0, self.downloaded_bytes / self.total_bytes)


@dataclass
class DownloadResult:
    """Outcome of a completed download."""

    path: Path
    size_bytes: int
    sha256: str
    resumed: bool
    verified: bool


ProgressCallback = Callable[[DownloadProgress], None]


# ---------------------------------------------------------------------------
# Checksum helpers
# ---------------------------------------------------------------------------


def verify_sha256(path: Path, expected: str, chunk_size: int = CHUNK_SIZE) -> str:
    """Compute the SHA256 of ``path`` and raise if it doesn't match ``expected``.

    Returns the computed hex digest on success. Hash comparison is
    case-insensitive so mixed-case SHA256SUMS files work.
    """
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            chunk = f.read(chunk_size)
            if not chunk:
                break
            h.update(chunk)
    digest = h.hexdigest()
    if digest.lower() != expected.lower():
        raise ChecksumMismatch(
            f"SHA256 mismatch for {path}:\n"
            f"  expected {expected.lower()}\n"
            f"  got      {digest}"
        )
    return digest


# SHA256SUMS files come in several shapes across distros. Be forgiving.
#   Ubuntu / Debian:  "<hash> *<filename>"        (with asterisk prefix)
#   Alpine (.sha256): "<hash>  <filename>"        (two spaces, no asterisk)
#   FreeBSD:          "SHA256 (<filename>) = <hash>"
_SHA256_LINE_RE = re.compile(
    r"""^\s*
        (?:(?P<hash1>[0-9a-fA-F]{64})\s+\*?(?P<file1>\S.*?)\s*$)     # GNU / BSD coreutils style
        |
        (?:SHA256\s*\(\s*(?P<file2>[^)]+?)\s*\)\s*=\s*(?P<hash2>[0-9a-fA-F]{64})\s*$)  # FreeBSD style
    """,
    re.VERBOSE,
)


def _parse_sha256sums(contents: str, wanted_filename: str) -> Optional[str]:
    """Find the 64-hex SHA256 for ``wanted_filename`` in a checksum file body."""
    for line in contents.splitlines():
        m = _SHA256_LINE_RE.match(line)
        if not m:
            continue
        fname = m.group("file1") or m.group("file2")
        digest = m.group("hash1") or m.group("hash2")
        # Vendor files sometimes list paths relative to a subdirectory.
        # Match on basename if the literal filename doesn't match.
        if fname == wanted_filename or fname.rsplit("/", 1)[-1] == wanted_filename:
            return digest
    return None


def fetch_expected_sha256(
    checksum_url: str,
    filename: str,
    timeout: float = DEFAULT_TIMEOUT,
) -> Optional[str]:
    """Download a vendor SHA256SUMS file and extract the hash for ``filename``.

    Returns ``None`` if the file is reachable but does not contain an
    entry for ``filename``. Raises :class:`urllib.error.URLError` on
    network failure so callers can decide whether to abort or proceed
    without verification.
    """
    req = urllib.request.Request(checksum_url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        body = resp.read().decode("utf-8", errors="replace")
    return _parse_sha256sums(body, filename)


# ---------------------------------------------------------------------------
# Downloader
# ---------------------------------------------------------------------------


def _request_with_range(
    url: str,
    start_offset: int,
    timeout: float,
) -> tuple[urllib.request.addinfourl, bool, Optional[int]]:
    """Open ``url`` with a Range header if ``start_offset > 0``.

    Returns ``(response, is_partial, total_size)`` where:
    - ``is_partial`` is True if the server honoured the range (HTTP 206).
    - ``total_size`` is the *full* file size when determinable, or None.
    """
    headers = {"User-Agent": USER_AGENT}
    if start_offset > 0:
        headers["Range"] = f"bytes={start_offset}-"
    req = urllib.request.Request(url, headers=headers)
    resp = urllib.request.urlopen(req, timeout=timeout)

    status = resp.status if hasattr(resp, "status") else resp.getcode()
    is_partial = status == 206

    total_size: Optional[int] = None
    if is_partial:
        # Content-Range: bytes 1234-5678/9999
        cr = resp.headers.get("Content-Range", "")
        if "/" in cr:
            try:
                total_size = int(cr.rsplit("/", 1)[-1])
            except ValueError:
                total_size = None
    else:
        cl = resp.headers.get("Content-Length")
        if cl:
            try:
                total_size = int(cl)
            except ValueError:
                total_size = None

    return resp, is_partial, total_size


def download_iso(
    url: str,
    destination: Path | str,
    expected_sha256: Optional[str] = None,
    checksum_url: Optional[str] = None,
    checksum_filename: Optional[str] = None,
    resume: bool = True,
    timeout: float = DEFAULT_TIMEOUT,
    progress: Optional[ProgressCallback] = None,
) -> DownloadResult:
    """Download a file over HTTP(S) with optional resume and SHA256 check.

    Parameters
    ----------
    url:
        The full HTTPS URL to fetch.
    destination:
        Target path on disk. Parent directories are created if missing.
    expected_sha256:
        Explicit expected digest. Takes priority over ``checksum_url``.
    checksum_url:
        Optional URL to a SHA256SUMS-like file. When ``expected_sha256``
        is not given, the digest is parsed from this file at runtime.
    checksum_filename:
        Filename to look up inside the checksum file. Defaults to the
        basename of ``destination``.
    resume:
        If True and the destination already has partial bytes, attempt
        an HTTP Range request to continue. Falls back to a fresh
        download if the server doesn't support ranges.
    progress:
        Optional callback; invoked roughly once per :data:`CHUNK_SIZE`
        bytes with a :class:`DownloadProgress` snapshot.
    """
    dest = Path(destination)
    dest.parent.mkdir(parents=True, exist_ok=True)

    # Decide on resume offset
    start_offset = 0
    if resume and dest.is_file():
        start_offset = dest.stat().st_size

    resp, is_partial, total_size = _request_with_range(url, start_offset, timeout)

    try:
        mode = "ab" if is_partial else "wb"
        if not is_partial and start_offset > 0:
            # Server ignored our Range header; start over cleanly.
            logger.info("Server does not support resume, restarting download")
            start_offset = 0

        downloaded = start_offset
        # total_size from the response is the *remaining* portion when
        # partial; we normalised it to full-file in _request_with_range
        # when Content-Range is present. When the response is a fresh
        # 200, total_size IS the full file size.
        with open(dest, mode) as f:
            while True:
                chunk = resp.read(CHUNK_SIZE)
                if not chunk:
                    break
                f.write(chunk)
                downloaded += len(chunk)
                if progress is not None:
                    progress(DownloadProgress(
                        downloaded_bytes=downloaded,
                        total_bytes=total_size,
                        url=url,
                        destination=dest,
                    ))
    finally:
        resp.close()

    # Resolve expected hash
    digest_expected = expected_sha256
    if digest_expected is None and checksum_url is not None:
        want = checksum_filename or dest.name
        try:
            digest_expected = fetch_expected_sha256(checksum_url, want, timeout=timeout)
        except urllib.error.URLError as exc:
            logger.warning("Could not fetch %s: %s — skipping verification", checksum_url, exc)

    # Verify
    verified = False
    if digest_expected:
        computed = verify_sha256(dest, digest_expected)
        verified = True
    else:
        # No expected hash — still compute the digest so callers know
        # what they got, even without verification.
        h = hashlib.sha256()
        with open(dest, "rb") as f:
            for chunk in iter(lambda: f.read(CHUNK_SIZE), b""):
                h.update(chunk)
        computed = h.hexdigest()

    return DownloadResult(
        path=dest,
        size_bytes=dest.stat().st_size,
        sha256=computed,
        resumed=(start_offset > 0 and is_partial),
        verified=verified,
    )


# ---------------------------------------------------------------------------
# Disk-space pre-check (helper, not used by download_iso itself)
# ---------------------------------------------------------------------------


def ensure_free_space(destination: Path | str, required_bytes: int, safety_margin: float = 1.1) -> None:
    """Raise :class:`OSError` if the filesystem under ``destination`` is too small.

    ``safety_margin`` multiplies ``required_bytes`` to allow for the
    filesystem overhead that happens during write. The caller should
    pass the ISO's advertised size in bytes.
    """
    dest = Path(destination)
    parent = dest.parent if dest.suffix else dest
    parent.mkdir(parents=True, exist_ok=True)
    usage = shutil.disk_usage(parent)
    need = int(required_bytes * safety_margin)
    if usage.free < need:
        raise OSError(
            f"Not enough free space at {parent}: need "
            f"{need / 1e9:.2f} GB, have {usage.free / 1e9:.2f} GB free."
        )
