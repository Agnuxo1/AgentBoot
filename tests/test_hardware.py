"""Tests for hardware_detector.py and os_compatibility.py (M2)."""

from __future__ import annotations

import json
from dataclasses import asdict

import pytest

from agentboot.hardware_detector import (
    HardwareDetector,
    HardwareProfile,
    CPUInfo,
    RAMInfo,
    StorageDevice,
    GPUInfo,
    NICInfo,
    _parse_size_to_gb,
)
from agentboot.os_compatibility import (
    OS_CATALOG,
    recommend_os,
    format_top_recommendations,
    format_recommendation,
)


# ---------------------------------------------------------------------------
# HardwareProfile helpers
# ---------------------------------------------------------------------------

def make_profile(
    arch: str = "x86_64",
    ram_mb: int = 8192,
    disk_gb: float = 250.0,
    cores: int = 4,
    gpus: list | None = None,
    nics: int = 1,
) -> HardwareProfile:
    profile = HardwareProfile(
        hostname="test-host",
        os_running="test-os",
        arch=arch,
        cpu=CPUInfo(brand="Test CPU", arch=arch, logical_cores=cores, physical_cores=cores // 2),
        ram=RAMInfo(total_mb=ram_mb, available_mb=ram_mb // 2),
        storage=[StorageDevice(device="/dev/sda", size_gb=disk_gb)],
        gpus=gpus or [],
        nics=[NICInfo(name=f"eth{i}") for i in range(nics)],
    )
    return profile


# ---------------------------------------------------------------------------
# HardwareProfile serialisation
# ---------------------------------------------------------------------------

class TestHardwareProfile:
    def test_to_dict_returns_dict(self):
        p = make_profile()
        d = p.to_dict()
        assert isinstance(d, dict)
        assert d["arch"] == "x86_64"
        assert d["ram"]["total_mb"] == 8192

    def test_to_json_is_valid_json(self):
        p = make_profile()
        j = p.to_json()
        loaded = json.loads(j)
        assert loaded["hostname"] == "test-host"

    def test_summary_contains_key_sections(self):
        p = make_profile(gpus=[GPUInfo(vendor="NVIDIA", model="RTX 3080")])
        s = p.summary()
        assert "CPU" in s
        assert "RAM" in s
        assert "Storage" in s
        assert "GPU" in s
        assert "NVIDIA" in s


# ---------------------------------------------------------------------------
# Local detection (smoke — just runs without crashing)
# ---------------------------------------------------------------------------

class TestHardwareDetectorLocal:
    def test_detect_local_returns_profile(self):
        detector = HardwareDetector()
        profile = detector.detect_local()
        assert isinstance(profile, HardwareProfile)

    def test_detect_local_cpu_arch_normalised(self):
        detector = HardwareDetector()
        profile = detector.detect_local()
        assert profile.arch in ("x86_64", "arm64", "armhf", "riscv64", "unknown", "amd64")

    def test_detect_local_has_hostname(self):
        detector = HardwareDetector()
        profile = detector.detect_local()
        assert isinstance(profile.hostname, str)
        assert len(profile.hostname) > 0

    def test_detect_local_ram_positive(self):
        detector = HardwareDetector()
        profile = detector.detect_local()
        # psutil is installed, so RAM should be detectable
        assert profile.ram.total_mb > 0

    def test_detect_local_no_hard_crash_on_summary(self):
        detector = HardwareDetector()
        profile = detector.detect_local()
        summary = profile.summary()
        assert isinstance(summary, str)
        assert len(summary) > 10


# ---------------------------------------------------------------------------
# _parse_size_to_gb helper
# ---------------------------------------------------------------------------

class TestParseSizeToGb:
    def test_gigabytes(self):
        assert _parse_size_to_gb("500G") == pytest.approx(500.0)

    def test_terabytes(self):
        assert _parse_size_to_gb("2T") == pytest.approx(2048.0)

    def test_megabytes(self):
        assert _parse_size_to_gb("256M") == pytest.approx(0.25)

    def test_lowercase(self):
        assert _parse_size_to_gb("100g") == pytest.approx(100.0)

    def test_empty(self):
        assert _parse_size_to_gb("") == 0.0


# ---------------------------------------------------------------------------
# OS Catalogue
# ---------------------------------------------------------------------------

class TestOSCatalog:
    def test_catalog_not_empty(self):
        assert len(OS_CATALOG) >= 10

    def test_all_entries_have_required_keys(self):
        required = {"id", "name", "arch", "min_ram_mb", "min_disk_gb", "url"}
        for entry in OS_CATALOG:
            missing = required - entry.keys()
            assert not missing, f"Entry '{entry.get('id')}' missing keys: {missing}"

    def test_all_entries_have_pros_and_cons(self):
        for entry in OS_CATALOG:
            assert entry.get("pros"), f"Entry '{entry['id']}' has no pros"
            assert entry.get("cons"), f"Entry '{entry['id']}' has no cons"

    def test_all_entries_have_use_cases(self):
        for entry in OS_CATALOG:
            assert entry.get("use_cases"), f"Entry '{entry['id']}' has no use_cases"


# ---------------------------------------------------------------------------
# recommend_os
# ---------------------------------------------------------------------------

class TestRecommendOs:
    def test_returns_list(self):
        profile = make_profile()
        recs = recommend_os(profile)
        assert isinstance(recs, list)

    def test_respects_max_results(self):
        profile = make_profile()
        recs = recommend_os(profile, max_results=3)
        assert len(recs) <= 3

    def test_sorted_by_score_descending(self):
        profile = make_profile(ram_mb=32768, disk_gb=500, cores=16)
        recs = recommend_os(profile)
        scores = [r.score for r in recs]
        assert scores == sorted(scores, reverse=True)

    def test_compatible_first(self):
        # Very low RAM ensures some OS entries are marked incompatible
        profile = make_profile(ram_mb=128, disk_gb=1, cores=1)
        recs = recommend_os(profile)
        # Compatible entries should come before incompatible ones
        found_incompatible = False
        for r in recs:
            if not r.compatible:
                found_incompatible = True
            if found_incompatible:
                assert not r.compatible or r.score == 0

    def test_arch_filter(self):
        # arm64 profile should not get x86_64-only entries as compatible
        profile = make_profile(arch="arm64", ram_mb=4096, disk_gb=100)
        recs = recommend_os(profile)
        for r in recs:
            if r.compatible:
                # Find the entry and check it supports arm64
                entry = next((e for e in OS_CATALOG if e["id"] == r.os_id), None)
                if entry:
                    assert "arm64" in entry["arch"]

    def test_tag_filter_server(self):
        profile = make_profile()
        recs = recommend_os(profile, tags_filter=["server"])
        for r in recs:
            entry = next((e for e in OS_CATALOG if e["id"] == r.os_id), None)
            if entry:
                assert "server" in entry.get("tags", [])

    def test_low_ram_prefers_lightweight(self):
        profile = make_profile(ram_mb=256, disk_gb=4, cores=1)
        recs = recommend_os(profile, tags_filter=["minimal", "lightweight"])
        assert len(recs) > 0, "Should have at least one lightweight OS for 256 MB RAM"

    def test_hypervisor_scores_high_with_lots_of_ram(self):
        profile = make_profile(ram_mb=65536, disk_gb=1000, cores=32)
        recs = recommend_os(profile, tags_filter=["hypervisor"])
        compatible = [r for r in recs if r.compatible]
        assert compatible, "Should find compatible hypervisor OS"
        assert compatible[0].score > 60

    def test_firewall_nic_bonus(self):
        profile_multi_nic = make_profile(nics=4, ram_mb=4096, disk_gb=50)
        profile_single_nic = make_profile(nics=1, ram_mb=4096, disk_gb=50)
        recs_multi = recommend_os(profile_multi_nic, tags_filter=["firewall"])
        recs_single = recommend_os(profile_single_nic, tags_filter=["firewall"])
        if recs_multi and recs_single:
            assert recs_multi[0].score >= recs_single[0].score

    def test_recommendation_has_download_url(self):
        profile = make_profile(ram_mb=8192, disk_gb=50)
        recs = recommend_os(profile)
        compatible = [r for r in recs if r.compatible]
        assert any(r.download_url for r in compatible)

    def test_format_recommendation_string(self):
        profile = make_profile()
        recs = recommend_os(profile, max_results=1)
        if recs:
            s = format_recommendation(recs[0], 1)
            assert isinstance(s, str)
            assert recs[0].name in s

    def test_format_top_recommendations_string(self):
        profile = make_profile(ram_mb=8192, disk_gb=100)
        recs = recommend_os(profile)
        s = format_top_recommendations(recs, n=3)
        assert isinstance(s, str)
        assert len(s) > 50
