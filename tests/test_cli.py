"""CLI subcommand tests.

We exercise argparse dispatch and pure-logic subcommands (list-isos,
list-devices, gen-config, session show). Subcommands that hit real
hardware or the network are mocked via the seams each module exposes.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agentboot import cli


# ---------------------------------------------------------------------------
# Parser / top-level
# ---------------------------------------------------------------------------


def test_build_parser_has_all_subcommands():
    parser = cli.build_parser()
    actions = [a for a in parser._actions if isinstance(a, type(parser._subparsers._actions[0]))
               or getattr(a, "choices", None)]
    # Pull the subparsers map via the known attribute.
    subparsers = None
    for a in parser._actions:
        if hasattr(a, "choices") and isinstance(a.choices, dict):
            subparsers = a.choices
            break
    assert subparsers is not None
    for name in (
        "chat", "detect", "recommend", "list-isos", "download",
        "list-devices", "flash", "gen-config", "session", "install",
    ):
        assert name in subparsers, f"missing subcommand: {name}"


def test_main_with_no_args_prints_help_and_exits_nonzero(capsys):
    rc = cli.main([])
    assert rc == 1
    out = capsys.readouterr().out
    assert "agentboot" in out.lower()


def test_default_model_path_points_under_models_dir():
    assert cli.DEFAULT_MODEL.name.endswith(".gguf")
    assert cli.DEFAULT_MODEL.parent.name == "models"


def test_system_prompt_defined():
    assert isinstance(cli.SYSTEM_PROMPT, str)
    assert len(cli.SYSTEM_PROMPT) > 0


# ---------------------------------------------------------------------------
# list-isos
# ---------------------------------------------------------------------------


def test_list_isos_human_output(capsys):
    rc = cli.main(["list-isos"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "ID" in out and "ARCH" in out
    assert "ubuntu-server-2404" in out


def test_list_isos_filtered_by_arch(capsys):
    rc = cli.main(["list-isos", "--arch", "arm64"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "arm64" in out
    # No x86_64 entries should show up
    lines = [ln for ln in out.splitlines() if "x86_64" in ln]
    assert lines == []


def test_list_isos_json(capsys):
    rc = cli.main(["list-isos", "--json"])
    assert rc == 0
    data = json.loads(capsys.readouterr().out)
    assert isinstance(data, list)
    assert any(e["id"] == "ubuntu-server-2404" for e in data)


# ---------------------------------------------------------------------------
# list-devices
# ---------------------------------------------------------------------------


def test_list_devices_empty_path(monkeypatch, capsys):
    monkeypatch.setattr(
        "agentboot.flasher.enumerate_usb_devices", lambda: []
    )
    rc = cli.main(["list-devices"])
    assert rc == 0
    assert "No removable USB devices" in capsys.readouterr().out


def test_list_devices_table(monkeypatch, capsys):
    from agentboot.flasher.enumerate import UsbDevice
    fake = [
        UsbDevice(
            id="/dev/sdb", device_path="/dev/sdb", size_bytes=16_000_000_000,
            vendor="SanDisk", model="SanDisk Ultra",
            removable=True, is_system_disk=False, mount_points=(),
        ),
    ]
    monkeypatch.setattr("agentboot.flasher.enumerate_usb_devices", lambda: fake)
    rc = cli.main(["list-devices"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "/dev/sdb" in out
    assert "SanDisk Ultra" in out
    assert "16.0GB" in out


# ---------------------------------------------------------------------------
# gen-config
# ---------------------------------------------------------------------------


def test_gen_config_writes_files(tmp_path, capsys):
    out_dir = tmp_path / "cfg"
    rc = cli.main([
        "gen-config",
        "--os", "ubuntu-server",
        "--user", "alice",
        "--password-hash", "$6$abc$def",
        "--hostname", "testhost",
        "--output", str(out_dir),
    ])
    assert rc == 0, capsys.readouterr().err
    # cloud-init produces user-data + meta-data
    files = sorted(p.relative_to(out_dir).as_posix() for p in out_dir.rglob("*") if p.is_file())
    assert any("user-data" in f for f in files)
    assert any("meta-data" in f for f in files)
    # user-data should contain our hostname
    content = next(out_dir.rglob("user-data")).read_text(encoding="utf-8")
    assert "testhost" in content
    assert "alice" in content


def test_gen_config_unknown_os_returns_error(tmp_path, capsys):
    rc = cli.main([
        "gen-config",
        "--os", "not-a-real-os",
        "--user", "bob",
        "--password-hash", "$6$x$y",
        "--output", str(tmp_path),
    ])
    assert rc == 2
    err = capsys.readouterr().err
    assert "failed" in err.lower() or "unknown" in err.lower() or "no generator" in err.lower()


# ---------------------------------------------------------------------------
# session
# ---------------------------------------------------------------------------


def test_session_show_missing_returns_error(tmp_path, capsys):
    rc = cli.main(["session", "show", "--dir", str(tmp_path)])
    assert rc == 2
    err = capsys.readouterr().err
    assert "No session" in err or "session" in err.lower()


def test_session_show_prints_state(tmp_path, capsys):
    from agentboot.agent import InstallSession
    s = InstallSession()
    s.save(tmp_path)
    rc = cli.main(["session", "show", "--dir", str(tmp_path)])
    assert rc == 0
    out = capsys.readouterr().out
    assert "init" in out
    assert "Session ID" in out


def test_session_reset_returns_to_init(tmp_path, capsys):
    from agentboot.agent import InstallSession, State
    s = InstallSession()
    s.save(tmp_path)
    s.transition(State.DETECTING)
    rc = cli.main(["session", "reset", "--dir", str(tmp_path)])
    assert rc == 0
    # Re-load to check.
    from agentboot.agent import load_session
    back = load_session(tmp_path)
    assert back.state == State.INIT


# ---------------------------------------------------------------------------
# download — error paths only (no real network)
# ---------------------------------------------------------------------------


def test_download_unknown_os_id(tmp_path, capsys):
    rc = cli.main(["download", "no-such-os", "--dest", str(tmp_path)])
    assert rc == 2
    err = capsys.readouterr().err
    assert "No ISO in catalogue" in err


# ---------------------------------------------------------------------------
# flash — safety refusal when confirm token absent
# ---------------------------------------------------------------------------


def test_flash_requires_confirm_token(tmp_path, monkeypatch, capsys):
    from agentboot.flasher.enumerate import UsbDevice
    from agentboot.flasher.flash import FlashPlan

    iso = tmp_path / "dummy.iso"
    iso.write_bytes(b"\x00" * 1024)

    device = UsbDevice(
        id="/dev/sdb", device_path="/dev/sdb", size_bytes=16_000_000_000,
        vendor="TestVendor", model="Test",
        removable=True, is_system_disk=False, mount_points=(),
    )
    monkeypatch.setattr("agentboot.flasher.find_device_by_id", lambda _id: device)
    monkeypatch.setattr(
        "agentboot.flasher.plan_flash",
        lambda iso_path, dev: FlashPlan(source_iso=iso_path, target=dev, iso_size_bytes=1024),
    )

    rc = cli.main(["flash", "--iso", str(iso), "--device", "/dev/sdb"])
    assert rc == 4  # confirm token missing
    err = capsys.readouterr().err
    assert "DESTROY" in err


# ---------------------------------------------------------------------------
# chat — model-missing error path (no llama.cpp needed)
# ---------------------------------------------------------------------------


def test_chat_reports_missing_model(tmp_path, capsys):
    missing = tmp_path / "nope.gguf"
    rc = cli.main(["chat", "--model", str(missing)])
    assert rc == 2
    err = capsys.readouterr().err
    assert "Model file not found" in err
