"""Tests for the OS compatibility / recommendation engine.

All tests use synthetic HardwareProfile objects so they run identically
on any developer machine or CI runner.
"""

from __future__ import annotations

import pytest

from agentboot.hardware_detector import (
    CPUInfo,
    GPUInfo,
    HardwareProfile,
    NICInfo,
    RAMInfo,
    StorageDevice,
)
from agentboot.os_compatibility import (
    OS_CATALOG,
    OSRecommendation,
    format_recommendation,
    format_top_recommendations,
    recommend_os,
)


def _make_profile(
    arch: str = "x86_64",
    ram_mb: int = 16384,
    disk_gb: float = 500.0,
    cores: int = 8,
    gpus: list[GPUInfo] | None = None,
    nics: int = 1,
) -> HardwareProfile:
    return HardwareProfile(
        hostname="test",
        arch=arch,
        cpu=CPUInfo(brand="Test CPU", arch=arch, logical_cores=cores, physical_cores=cores // 2 or 1),
        ram=RAMInfo(total_mb=ram_mb, available_mb=ram_mb),
        storage=[StorageDevice(device="/dev/sda", model="d", size_gb=disk_gb)],
        gpus=gpus or [],
        nics=[NICInfo(name=f"eth{i}", mac=f"00:00:00:00:00:{i:02x}") for i in range(nics)],
    )


# ---------------------------------------------------------------------------
# Catalogue integrity
# ---------------------------------------------------------------------------


def test_catalog_has_entries():
    assert len(OS_CATALOG) >= 10


def test_catalog_entries_have_required_fields():
    required = {"id", "name", "family", "arch", "min_ram_mb", "min_disk_gb", "tags"}
    for entry in OS_CATALOG:
        missing = required - entry.keys()
        assert not missing, f"OS {entry.get('id', '?')} missing fields: {missing}"
        assert isinstance(entry["arch"], list) and entry["arch"]


def test_catalog_ids_are_unique():
    ids = [e["id"] for e in OS_CATALOG]
    assert len(ids) == len(set(ids)), "duplicate OS ids in catalogue"


# ---------------------------------------------------------------------------
# Recommendation engine
# ---------------------------------------------------------------------------


def test_recommend_os_returns_osrecommendation_objects():
    recs = recommend_os(_make_profile())
    assert recs
    assert all(isinstance(r, OSRecommendation) for r in recs)


def test_compatible_results_come_first():
    recs = recommend_os(_make_profile())
    seen_incompatible = False
    for r in recs:
        if not r.compatible:
            seen_incompatible = True
        else:
            assert not seen_incompatible, "compatible entry appeared after an incompatible one"


def test_unsupported_arch_marks_incompatible():
    recs = recommend_os(_make_profile(arch="riscv64"))
    # ESXi is x86_64-only — must be marked incompatible for riscv64
    esxi = next(r for r in recs if r.os_id == "esxi-8")
    assert not esxi.compatible
    assert esxi.score == 0.0


def test_tiny_ram_excludes_heavyweight_os():
    recs = recommend_os(_make_profile(ram_mb=128, disk_gb=2.0))
    # Proxmox needs 2 GB min — must be incompatible with 128 MB
    proxmox = next(r for r in recs if r.os_id == "proxmox-ve-8")
    assert not proxmox.compatible


def test_low_ram_prefers_minimal_distros():
    recs = recommend_os(_make_profile(ram_mb=256, disk_gb=4.0))
    compatible_ids = [r.os_id for r in recs if r.compatible]
    # Alpine should be compatible and near the top for tiny hardware
    assert "alpine-319" in compatible_ids
    top_three = compatible_ids[:3]
    assert "alpine-319" in top_three or "debian-12" in top_three


def test_tags_filter_restricts_results():
    profile = _make_profile()
    recs = recommend_os(profile, tags_filter=["hypervisor"])
    assert recs
    # Every returned entry must carry the hypervisor tag
    for r in recs:
        entry = next(e for e in OS_CATALOG if e["id"] == r.os_id)
        assert "hypervisor" in entry["tags"]


def test_multi_nic_boosts_firewall_recommendation():
    # Two NICs on a firewall-class machine. Use max_results=20 to make
    # sure OPNsense is in the result set regardless of other scores.
    with_two = _make_profile(nics=2, ram_mb=2048)
    with_one = _make_profile(nics=1, ram_mb=2048)
    r2 = next(r for r in recommend_os(with_two, max_results=20) if r.os_id == "opnsense-241")
    r1 = next(r for r in recommend_os(with_one, max_results=20) if r.os_id == "opnsense-241")
    assert r2.score > r1.score


def test_nvidia_gpu_boosts_container_host():
    base = _make_profile()
    gpu = _make_profile(gpus=[GPUInfo(vendor="NVIDIA", model="T4", vram_mb=16384)])
    talos_base = next(r for r in recommend_os(base) if r.os_id == "talos-linux")
    talos_gpu = next(r for r in recommend_os(gpu) if r.os_id == "talos-linux")
    assert talos_gpu.score > talos_base.score


def test_score_is_clamped_to_0_100():
    for r in recommend_os(_make_profile()):
        assert 0.0 <= r.score <= 100.0


def test_max_results_is_respected():
    recs = recommend_os(_make_profile(), max_results=3)
    assert len(recs) <= 3


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------


def test_format_recommendation_is_non_empty_string():
    recs = recommend_os(_make_profile(), max_results=1)
    assert recs
    text = format_recommendation(recs[0], rank=1)
    assert isinstance(text, str) and text.strip()


def test_format_top_recommendations_handles_empty_list():
    text = format_top_recommendations([], n=3)
    assert isinstance(text, str)
    assert "Top 0" in text or "Top " in text


def test_format_top_recommendations_with_real_data():
    recs = recommend_os(_make_profile())
    text = format_top_recommendations(recs, n=3)
    assert text.count("Score:") >= 1
