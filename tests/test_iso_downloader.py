"""Tests for the ISO downloader.

We spin up a tiny stdlib ``http.server`` on localhost so the tests
exercise the real HTTP code path (Range requests, Content-Length
handling, checksum fetching) without touching the public internet.
"""

from __future__ import annotations

import hashlib
import http.server
import socket
import threading
from pathlib import Path

import pytest

from agentboot.iso.downloader import (
    ChecksumMismatch,
    DownloadProgress,
    _parse_sha256sums,
    download_iso,
    ensure_free_space,
    fetch_expected_sha256,
    verify_sha256,
)


# ---------------------------------------------------------------------------
# Test HTTP server fixture
# ---------------------------------------------------------------------------


class _RangeHandler(http.server.BaseHTTPRequestHandler):
    """Minimal HTTP handler with Range support, for download tests."""

    # Per-class registry of files: {path: bytes}
    files: dict[str, bytes] = {}
    # If True, the server ignores Range headers (to exercise fallback).
    disable_range: bool = False

    def log_message(self, *a, **kw):  # pragma: no cover — silence test noise
        return

    def do_GET(self):  # noqa: N802 — required name
        data = self.files.get(self.path)
        if data is None:
            self.send_error(404, "not found")
            return

        range_header = self.headers.get("Range")
        if range_header and not self.disable_range:
            # "bytes=<start>-" — only form we care about.
            try:
                start = int(range_header.removeprefix("bytes=").split("-", 1)[0])
            except ValueError:
                self.send_error(400, "bad range")
                return
            body = data[start:]
            self.send_response(206)
            self.send_header("Content-Type", "application/octet-stream")
            self.send_header("Content-Length", str(len(body)))
            self.send_header(
                "Content-Range", f"bytes {start}-{len(data)-1}/{len(data)}"
            )
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_response(200)
            self.send_header("Content-Type", "application/octet-stream")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)


@pytest.fixture
def http_server():
    _RangeHandler.files = {}
    _RangeHandler.disable_range = False

    # Bind to an ephemeral port on localhost
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]

    srv = http.server.ThreadingHTTPServer(("127.0.0.1", port), _RangeHandler)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()

    base = f"http://127.0.0.1:{port}"
    try:
        yield base, _RangeHandler
    finally:
        srv.shutdown()
        srv.server_close()


# ---------------------------------------------------------------------------
# SHA256 parsing
# ---------------------------------------------------------------------------


def test_parse_sha256sums_gnu_style():
    body = (
        "abc  other.iso\n"
        + ("0" * 64) + " *wanted.iso\n"
        + "something-else\n"
    )
    assert _parse_sha256sums(body, "wanted.iso") == "0" * 64


def test_parse_sha256sums_freebsd_style():
    body = (
        "SHA256 (FreeBSD-14.1-RELEASE-amd64-disc1.iso) = " + "a" * 64 + "\n"
        "SHA256 (unrelated) = " + "b" * 64 + "\n"
    )
    assert (
        _parse_sha256sums(body, "FreeBSD-14.1-RELEASE-amd64-disc1.iso")
        == "a" * 64
    )


def test_parse_sha256sums_returns_none_when_file_absent():
    body = "deadbeef" * 8 + "  other.iso\n"
    assert _parse_sha256sums(body, "wanted.iso") is None


def test_parse_sha256sums_matches_basename_for_pathy_lines():
    body = ("f" * 64) + "  ./subdir/wanted.iso\n"
    assert _parse_sha256sums(body, "wanted.iso") == "f" * 64


# ---------------------------------------------------------------------------
# verify_sha256
# ---------------------------------------------------------------------------


def test_verify_sha256_passes_on_match(tmp_path: Path):
    body = b"hello world"
    digest = hashlib.sha256(body).hexdigest()
    p = tmp_path / "f.bin"
    p.write_bytes(body)
    assert verify_sha256(p, digest) == digest


def test_verify_sha256_case_insensitive(tmp_path: Path):
    body = b"hi"
    digest = hashlib.sha256(body).hexdigest()
    p = tmp_path / "f.bin"
    p.write_bytes(body)
    # Upper-case should work too
    assert verify_sha256(p, digest.upper()) == digest


def test_verify_sha256_raises_on_mismatch(tmp_path: Path):
    p = tmp_path / "f.bin"
    p.write_bytes(b"hello world")
    with pytest.raises(ChecksumMismatch):
        verify_sha256(p, "0" * 64)


# ---------------------------------------------------------------------------
# fetch_expected_sha256 (via local HTTP server)
# ---------------------------------------------------------------------------


def test_fetch_expected_sha256_over_http(http_server):
    base, handler = http_server
    body = ("d" * 64) + " *wanted.iso\n"
    handler.files["/SHA256SUMS"] = body.encode()
    got = fetch_expected_sha256(f"{base}/SHA256SUMS", "wanted.iso")
    assert got == "d" * 64


def test_fetch_expected_sha256_missing_entry_returns_none(http_server):
    base, handler = http_server
    handler.files["/SHA256SUMS"] = (("a" * 64) + "  other.iso\n").encode()
    assert fetch_expected_sha256(f"{base}/SHA256SUMS", "wanted.iso") is None


# ---------------------------------------------------------------------------
# download_iso
# ---------------------------------------------------------------------------


def test_download_iso_writes_file_and_computes_hash(http_server, tmp_path: Path):
    base, handler = http_server
    payload = b"x" * 5000
    handler.files["/demo.iso"] = payload

    dest = tmp_path / "demo.iso"
    result = download_iso(f"{base}/demo.iso", dest)

    assert dest.is_file()
    assert dest.read_bytes() == payload
    assert result.size_bytes == len(payload)
    assert result.sha256 == hashlib.sha256(payload).hexdigest()
    assert result.verified is False  # no expected hash supplied
    assert result.resumed is False


def test_download_iso_verifies_expected_hash(http_server, tmp_path: Path):
    base, handler = http_server
    payload = b"real data"
    handler.files["/demo.iso"] = payload
    digest = hashlib.sha256(payload).hexdigest()

    result = download_iso(
        f"{base}/demo.iso", tmp_path / "demo.iso", expected_sha256=digest,
    )
    assert result.verified is True


def test_download_iso_raises_on_checksum_mismatch(http_server, tmp_path: Path):
    base, handler = http_server
    handler.files["/demo.iso"] = b"something"
    with pytest.raises(ChecksumMismatch):
        download_iso(
            f"{base}/demo.iso",
            tmp_path / "demo.iso",
            expected_sha256="0" * 64,
        )


def test_download_iso_resumes_partial_file(http_server, tmp_path: Path):
    base, handler = http_server
    payload = b"y" * 10_000
    handler.files["/big.iso"] = payload

    dest = tmp_path / "big.iso"
    # Pre-create a partial file (first 3000 bytes)
    dest.write_bytes(payload[:3000])

    progress_snapshots: list[DownloadProgress] = []
    result = download_iso(
        f"{base}/big.iso", dest, progress=progress_snapshots.append,
    )

    assert dest.read_bytes() == payload
    assert result.resumed is True
    # First progress snapshot should be >= 3000 (already had those bytes)
    assert progress_snapshots
    assert progress_snapshots[0].downloaded_bytes >= 3000


def test_download_iso_falls_back_when_server_ignores_range(http_server, tmp_path: Path):
    base, handler = http_server
    payload = b"z" * 2000
    handler.files["/nr.iso"] = payload
    handler.disable_range = True

    dest = tmp_path / "nr.iso"
    # Pretend we had a corrupted partial file
    dest.write_bytes(b"garbage garbage garbage")
    result = download_iso(f"{base}/nr.iso", dest)

    # Should have started over; file matches payload exactly
    assert dest.read_bytes() == payload
    assert result.resumed is False


def test_download_iso_fetches_checksum_from_url(http_server, tmp_path: Path):
    base, handler = http_server
    payload = b"abc123"
    digest = hashlib.sha256(payload).hexdigest()
    handler.files["/demo.iso"] = payload
    handler.files["/SHA256SUMS"] = (f"{digest} *demo.iso\n").encode()

    result = download_iso(
        f"{base}/demo.iso",
        tmp_path / "demo.iso",
        checksum_url=f"{base}/SHA256SUMS",
    )
    assert result.verified is True
    assert result.sha256 == digest


def test_download_iso_skips_verification_if_checksum_url_404(http_server, tmp_path: Path):
    base, handler = http_server
    handler.files["/demo.iso"] = b"hello"
    # /SHA256SUMS not registered → 404
    result = download_iso(
        f"{base}/demo.iso",
        tmp_path / "demo.iso",
        checksum_url=f"{base}/SHA256SUMS",
    )
    # Download itself must still succeed
    assert result.verified is False
    assert result.size_bytes == 5


# ---------------------------------------------------------------------------
# ensure_free_space
# ---------------------------------------------------------------------------


def test_ensure_free_space_passes_when_small_request(tmp_path: Path):
    # 1 byte is always available on any working filesystem.
    ensure_free_space(tmp_path / "file", required_bytes=1)


def test_ensure_free_space_raises_when_absurdly_large(tmp_path: Path):
    # 10 EB — no filesystem has this.
    with pytest.raises(OSError):
        ensure_free_space(tmp_path / "f", required_bytes=10 * 10**18)
