"""Tests for the ISO catalogue.

Catalogue correctness is enforced purely from in-memory data; no
network access. We do not assert that URLs are *reachable* here —
that would couple CI to vendor mirror availability.
"""

from __future__ import annotations

import re

import pytest

from agentboot.iso import ISO_CATALOG, IsoEntry, find_iso, list_isos_for_arch


# ---------------------------------------------------------------------------
# Structural invariants
# ---------------------------------------------------------------------------


def test_catalogue_is_non_empty():
    assert len(ISO_CATALOG) > 0


def test_every_entry_has_a_https_url():
    for entry in ISO_CATALOG:
        assert entry.url.startswith("https://"), f"{entry.id} has non-HTTPS URL: {entry.url}"


def test_every_entry_has_a_reasonable_size():
    for entry in ISO_CATALOG:
        # ISO images range from ~100 MB (Alpine netinst) to a few GB.
        # Anything outside this window is almost certainly a typo.
        assert 0.05 <= entry.size_gb <= 20, (
            f"{entry.id}/{entry.arch} size_gb={entry.size_gb} out of sane range"
        )


def test_arch_values_are_canonical():
    allowed = {"x86_64", "arm64", "armhf", "riscv64"}
    for entry in ISO_CATALOG:
        assert entry.arch in allowed, f"{entry.id} has non-canonical arch {entry.arch!r}"


def test_checksum_filename_defaults_to_url_basename():
    # When an entry provides a checksum_url but no explicit filename,
    # the downloader will use the basename of the URL. Validate that
    # is at least a plausible filename.
    for entry in ISO_CATALOG:
        if entry.checksum_url and not entry.checksum_filename:
            assert entry.filename, f"{entry.id} has empty filename from URL"
            assert "/" not in entry.filename


def test_filename_property_matches_url_basename():
    entry = IsoEntry(
        id="x", name="X", arch="x86_64",
        url="https://example.com/foo/bar.iso", size_gb=1.0,
    )
    assert entry.filename == "bar.iso"


# ---------------------------------------------------------------------------
# Lookup
# ---------------------------------------------------------------------------


def test_find_iso_returns_none_for_unknown_id():
    assert find_iso("does-not-exist") is None


def test_find_iso_matches_by_id_and_arch():
    # There are multiple Ubuntu entries; we want the x86_64 one.
    result = find_iso("ubuntu-server-2404", "x86_64")
    assert result is not None
    assert "amd64" in result.url or "x86_64" in result.url
    assert result.arch == "x86_64"


def test_find_iso_distinguishes_arches():
    x = find_iso("ubuntu-server-2404", "x86_64")
    a = find_iso("ubuntu-server-2404", "arm64")
    assert x is not None and a is not None
    assert x.url != a.url


def test_list_isos_for_arch_returns_only_that_arch():
    x86 = list_isos_for_arch("x86_64")
    assert x86  # non-empty
    for entry in x86:
        assert entry.arch == "x86_64"


def test_list_isos_for_arch_unknown_arch_is_empty():
    assert list_isos_for_arch("ia64") == []
