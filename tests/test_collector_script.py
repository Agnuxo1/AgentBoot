"""Tests for scripts/agentboot_collector.py.

The collector runs on minimal live OSes that may not have pytest —
so here we only verify the script is well-formed: it imports as a
module, and its hardware-report function returns a dict with the
expected shape. The serial loop itself (``serve``) is not unit
tested; exercising it requires pyserial + a real port, which we do
in integration tests instead.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


def _load_collector():
    root = Path(__file__).resolve().parents[1]
    path = root / "scripts" / "agentboot_collector.py"
    spec = importlib.util.spec_from_file_location("agentboot_collector", path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["agentboot_collector"] = mod
    spec.loader.exec_module(mod)
    return mod


def test_collector_module_imports_cleanly():
    mod = _load_collector()
    assert hasattr(mod, "main")
    assert hasattr(mod, "hw_report")
    assert hasattr(mod, "_HANDLERS")


def test_hw_report_returns_expected_keys():
    mod = _load_collector()
    report = mod.hw_report()
    assert isinstance(report, dict)
    # All top-level keys the phone-side parser expects.
    expected = {
        "hostname", "arch", "os_running", "kernel", "is_virtual",
        "cpu", "ram", "storage", "nics", "gpus",
    }
    assert expected.issubset(report.keys())


def test_hw_report_cpu_shape():
    mod = _load_collector()
    cpu = mod.hw_report()["cpu"]
    assert "brand" in cpu
    assert "arch" in cpu
    assert "logical_cores" in cpu
    assert isinstance(cpu["logical_cores"], int)


def test_collector_handlers_registered():
    mod = _load_collector()
    names = set(mod._HANDLERS.keys())
    # The four named operations we document
    assert {
        "hw.report", "ping", "config.write",
        "system.reboot", "system.poweroff",
    }.issubset(names)


def test_handle_ping_returns_pong():
    mod = _load_collector()
    cmd = {"v": 1, "id": "p1", "kind": "cmd", "name": "ping"}
    resp = mod._HANDLERS["ping"](cmd)
    assert resp["kind"] == "response"
    assert resp["ok"] is True
    assert resp["data"]["pong"] is True
    assert resp["id"] == "p1"


def test_handle_config_write_writes_file(tmp_path):
    mod = _load_collector()
    target = tmp_path / "nested" / "preseed.cfg"
    cmd = {
        "v": 1, "id": "w1", "kind": "cmd", "name": "config.write",
        "data": {"path": str(target), "contents": "d-i foo/bar string baz\n"},
    }
    resp = mod._HANDLERS["config.write"](cmd)
    assert resp["ok"] is True
    assert target.is_file()
    assert target.read_text() == "d-i foo/bar string baz\n"


def test_handle_config_write_rejects_missing_args():
    mod = _load_collector()
    cmd = {"v": 1, "id": "w2", "kind": "cmd", "name": "config.write", "data": {}}
    resp = mod._HANDLERS["config.write"](cmd)
    assert resp["kind"] == "error"
    assert resp["code"] == "BAD_ARGS"


def test_hw_report_json_roundtrips():
    """The whole report must be JSON-serialisable with no custom encoder."""
    import json
    mod = _load_collector()
    blob = json.dumps(mod.hw_report())
    back = json.loads(blob)
    assert back["cpu"]["logical_cores"] == mod.hw_report()["cpu"]["logical_cores"]
