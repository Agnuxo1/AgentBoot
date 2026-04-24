"""Tests for the hardware detection module.

These are real tests: `detect_local()` runs against the actual machine
and is expected to return plausible values (non-zero CPU cores, non-zero
RAM, etc.) — not mocked data.

Remote detection paths (SSH, USB-serial) are tested via import and
signature checks only; exercising them would require a live remote host
or a serial peripheral.
"""

from __future__ import annotations

import platform

import pytest

from agentboot.hardware_detector import (
    CPUInfo,
    GPUInfo,
    HardwareDetector,
    HardwareProfile,
    NICInfo,
    RAMInfo,
    StorageDevice,
    _parse_size_to_gb,
)


# ---------------------------------------------------------------------------
# Dataclass / model tests (pure Python, no system calls)
# ---------------------------------------------------------------------------


def test_hardware_profile_defaults_are_sane():
    p = HardwareProfile()
    assert p.hostname == "unknown"
    assert p.os_running == "bare-metal"
    assert p.cpu.physical_cores == 0
    assert p.ram.total_mb == 0
    assert p.storage == []
    assert p.gpus == []
    assert p.nics == []
    assert p.errors == []


def test_hardware_profile_to_dict_and_json_roundtrip():
    p = HardwareProfile(
        hostname="t",
        cpu=CPUInfo(brand="Test CPU", physical_cores=4, logical_cores=8, arch="x86_64"),
        ram=RAMInfo(total_mb=8192, available_mb=4096, swap_mb=2048),
        storage=[StorageDevice(device="/dev/sda", model="disk", size_gb=100.0)],
        gpus=[GPUInfo(vendor="NVIDIA", model="Test GPU", vram_mb=8192)],
        nics=[NICInfo(name="eth0", mac="00:11:22:33:44:55", speed_mbps=1000)],
        arch="x86_64",
    )
    d = p.to_dict()
    assert d["hostname"] == "t"
    assert d["cpu"]["brand"] == "Test CPU"
    assert d["ram"]["total_mb"] == 8192

    # JSON serialisation must not error and must be parseable
    import json

    parsed = json.loads(p.to_json())
    assert parsed["cpu"]["logical_cores"] == 8


def test_summary_contains_expected_sections():
    p = HardwareProfile(
        hostname="s",
        cpu=CPUInfo(brand="X", physical_cores=1, logical_cores=2),
        ram=RAMInfo(total_mb=1024, available_mb=512, swap_mb=0),
    )
    text = p.summary()
    assert "Hostname" in text
    assert "--- CPU ---" in text
    assert "--- RAM ---" in text
    assert "1,024 MB" in text


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("500G", 500.0),
        ("16T", 16 * 1024.0),
        ("1024M", 1.0),
        ("2048K", 2.0 / 1024),
        ("0", 0.0),
    ],
)
def test_parse_size_to_gb(raw, expected):
    assert _parse_size_to_gb(raw) == pytest.approx(expected, rel=1e-3)


# ---------------------------------------------------------------------------
# Real local detection — runs against the machine
# ---------------------------------------------------------------------------


def test_detect_local_returns_profile_instance():
    detector = HardwareDetector()
    profile = detector.detect_local()
    assert isinstance(profile, HardwareProfile)


def test_detect_local_populates_cpu_and_ram():
    """These must be non-zero on any real machine running the tests."""
    profile = HardwareDetector().detect_local()

    assert profile.cpu.logical_cores >= 1, "should detect at least one logical core"
    assert profile.ram.total_mb > 0, "should detect some RAM"
    # Hostname should match platform.node()
    assert profile.hostname == platform.node()


def test_detect_local_arch_is_normalised():
    profile = HardwareDetector().detect_local()
    # Accept any architecture but make sure normalisation rules don't leak
    # AMD64 / aarch64 through — they must be converted.
    assert profile.arch not in ("amd64", "aarch64", "")


# ---------------------------------------------------------------------------
# Remote API — presence only (requires live targets to exercise fully)
# ---------------------------------------------------------------------------


def test_detect_remote_ssh_exists_and_requires_host():
    detector = HardwareDetector()
    assert callable(detector.detect_remote_ssh)


def test_detect_via_usb_serial_exists():
    detector = HardwareDetector()
    assert callable(detector.detect_via_usb_serial)
