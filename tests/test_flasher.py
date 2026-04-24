"""Tests for the USB flasher.

Enumeration is platform-sensitive — we only check that it returns a
list and doesn't raise. The planner and writer, which guard data
safety, are tested exhaustively against fake :class:`UsbDevice`
instances.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agentboot.flasher import (
    FlashError,
    UsbDevice,
    enumerate_usb_devices,
    flash_iso,
    plan_flash,
)


def _fake_device(
    *,
    device_id: str = "sdx",
    size_bytes: int = 32 * 1024 * 1024 * 1024,
    removable: bool = True,
    is_system_disk: bool = False,
    mount_points: tuple[str, ...] = (),
    device_path: str = "",
) -> UsbDevice:
    return UsbDevice(
        id=device_id,
        device_path=device_path or f"/dev/{device_id}",
        size_bytes=size_bytes,
        vendor="Generic",
        model="USB Stick",
        removable=removable,
        is_system_disk=is_system_disk,
        mount_points=mount_points,
    )


# ---------------------------------------------------------------------------
# Enumeration (smoke test)
# ---------------------------------------------------------------------------


def test_enumerate_usb_devices_returns_list_without_raising():
    result = enumerate_usb_devices()
    assert isinstance(result, list)
    for d in result:
        assert isinstance(d, UsbDevice)
        assert d.device_path


# ---------------------------------------------------------------------------
# Planning — safety checks
# ---------------------------------------------------------------------------


def test_plan_rejects_missing_iso(tmp_path: Path):
    with pytest.raises(FlashError, match="does not exist"):
        plan_flash(tmp_path / "nope.iso", _fake_device())


def test_plan_rejects_empty_iso(tmp_path: Path):
    iso = tmp_path / "empty.iso"
    iso.write_bytes(b"")
    with pytest.raises(FlashError, match="empty"):
        plan_flash(iso, _fake_device())


def test_plan_rejects_system_disk(tmp_path: Path):
    iso = tmp_path / "x.iso"
    iso.write_bytes(b"a" * 1024)
    with pytest.raises(FlashError, match="system disk"):
        plan_flash(iso, _fake_device(is_system_disk=True))


def test_plan_rejects_non_removable(tmp_path: Path):
    iso = tmp_path / "x.iso"
    iso.write_bytes(b"a" * 1024)
    with pytest.raises(FlashError, match="not marked removable"):
        plan_flash(iso, _fake_device(removable=False))


def test_plan_rejects_undersized_target(tmp_path: Path):
    iso = tmp_path / "big.iso"
    iso.write_bytes(b"a" * 10_000)
    with pytest.raises(FlashError, match="too small"):
        plan_flash(iso, _fake_device(size_bytes=1000))


def test_plan_rejects_mounted_device(tmp_path: Path):
    iso = tmp_path / "x.iso"
    iso.write_bytes(b"a" * 1024)
    with pytest.raises(FlashError, match="mounted"):
        plan_flash(iso, _fake_device(mount_points=("/media/usb0",)))


def test_plan_rejects_unknown_size(tmp_path: Path):
    iso = tmp_path / "x.iso"
    iso.write_bytes(b"a" * 1024)
    with pytest.raises(FlashError, match="determine size"):
        plan_flash(iso, _fake_device(size_bytes=0))


def test_plan_succeeds_for_valid_inputs(tmp_path: Path):
    iso = tmp_path / "x.iso"
    iso.write_bytes(b"iso-payload" * 100)
    dev = _fake_device()
    plan = plan_flash(iso, dev)
    assert plan.source_iso == iso
    assert plan.target is dev
    assert plan.iso_size_bytes == iso.stat().st_size
    assert "Source:" in plan.human_summary()


# ---------------------------------------------------------------------------
# Flash — the write itself, using an injected file-backed target
# ---------------------------------------------------------------------------


def test_flash_iso_writes_exact_bytes(tmp_path: Path):
    payload = b"HELLOWORLD" * 10_000
    iso = tmp_path / "src.iso"
    iso.write_bytes(payload)

    fake_target = tmp_path / "fake-device.bin"
    # Pre-create as empty file to mimic a block device existing
    fake_target.write_bytes(b"")

    dev = _fake_device(
        device_id="fake1",
        size_bytes=10 * len(payload),
        device_path=str(fake_target),
    )
    plan = plan_flash(iso, dev)

    def _opener(path):
        return open(path, "wb", buffering=0)

    snapshots: list[int] = []
    result = flash_iso(
        plan,
        confirm_token="fake1",
        progress=lambda p: snapshots.append(p.bytes_written),
        _open_target=_opener,
    )

    assert fake_target.read_bytes() == payload
    assert result.bytes_written == len(payload)
    # Progress should have been called at least once
    assert snapshots
    assert snapshots[-1] == len(payload)


def test_flash_iso_refuses_wrong_confirm_token(tmp_path: Path):
    iso = tmp_path / "x.iso"
    iso.write_bytes(b"a" * 1024)
    dev = _fake_device(device_id="correct", device_path=str(tmp_path / "t.bin"))
    plan = plan_flash(iso, dev)

    with pytest.raises(FlashError, match="does not match"):
        flash_iso(
            plan,
            confirm_token="WRONG",
            _open_target=lambda p: open(p, "wb", buffering=0),
        )


def test_flash_iso_accepts_file_like_from_opener(tmp_path: Path):
    """The opener seam must not assume a path-based open — any binary
    file-like is acceptable, so the test can stub it without touching
    the filesystem."""
    import io

    iso = tmp_path / "x.iso"
    payload = b"abc123" * 500
    iso.write_bytes(payload)

    dev = _fake_device(device_id="mem0", device_path="MEMORY")
    plan = plan_flash(iso, dev)

    captured = io.BytesIO()

    def _opener(path):
        assert path == "MEMORY"
        # Wrap so .close() doesn't discard our buffer.
        class _Wrap:
            def write(self, b): captured.write(b)
            def flush(self): pass
            def close(self): pass
        return _Wrap()

    flash_iso(plan, confirm_token="mem0", _open_target=_opener)
    assert captured.getvalue() == payload
