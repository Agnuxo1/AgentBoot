"""Tests for the install session state machine and persistence."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agentboot.agent import InstallSession, SessionError, State, load_session


# ---------------------------------------------------------------------------
# Transitions
# ---------------------------------------------------------------------------


def test_initial_state_is_init():
    s = InstallSession()
    assert s.state == State.INIT


def test_legal_linear_transitions(tmp_path: Path):
    s = InstallSession()
    s.save(tmp_path)
    for step in [
        State.DETECTING, State.RECOMMENDING, State.DOWNLOADING,
        State.FLASHING, State.CONFIGURING, State.INSTALLING,
        State.VERIFIED, State.DONE,
    ]:
        s.transition(step)
    assert s.state == State.DONE
    # History entries recorded for each step
    assert [h.state for h in s.history] == [
        State.DETECTING, State.RECOMMENDING, State.DOWNLOADING,
        State.FLASHING, State.CONFIGURING, State.INSTALLING,
        State.VERIFIED, State.DONE,
    ]


def test_illegal_backwards_transition_raises(tmp_path: Path):
    s = InstallSession()
    s.save(tmp_path)
    s.transition(State.DETECTING)
    with pytest.raises(SessionError, match="Illegal transition"):
        s.transition(State.INIT)


def test_failed_records_error_from_note(tmp_path: Path):
    s = InstallSession()
    s.save(tmp_path)
    s.transition(State.DETECTING)
    s.transition(State.FAILED, note="hardware detection broke")
    assert s.error == "hardware detection broke"


def test_reset_returns_to_init(tmp_path: Path):
    s = InstallSession()
    s.save(tmp_path)
    s.transition(State.DETECTING)
    s.transition(State.RECOMMENDING)
    s.reset()
    assert s.state == State.INIT
    assert s.error is None
    # Next transition after reset is allowed.
    s.transition(State.DETECTING)


def test_transition_from_failed_allows_retry(tmp_path: Path):
    s = InstallSession()
    s.save(tmp_path)
    s.transition(State.DETECTING)
    s.transition(State.FAILED, note="oh no")
    s.transition(State.DETECTING)  # retry from scratch


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------


def test_save_writes_session_json(tmp_path: Path):
    s = InstallSession()
    path = s.save(tmp_path)
    assert path == tmp_path / "session.json"
    assert path.is_file()
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["state"] == "init"
    assert "id" in payload
    assert "created_at" in payload


def test_save_without_directory_raises():
    s = InstallSession()
    with pytest.raises(SessionError, match="session_dir"):
        s.save()


def test_save_is_atomic_no_stray_tmp_files(tmp_path: Path):
    s = InstallSession()
    s.save(tmp_path)
    s.transition(State.DETECTING)
    names = sorted(p.name for p in tmp_path.iterdir())
    # Only the final session.json should remain. No .tmp leftovers.
    assert names == ["session.json"]


def test_load_session_roundtrip(tmp_path: Path):
    s = InstallSession()
    s.save(tmp_path)
    s.transition(State.DETECTING, note="first step")
    s.set_hardware_profile({"cpu": {"brand": "Intel i5"}})
    s.transition(State.RECOMMENDING)

    loaded = load_session(tmp_path)
    assert loaded.id == s.id
    assert loaded.state == State.RECOMMENDING
    assert loaded.hardware_profile == {"cpu": {"brand": "Intel i5"}}
    assert len(loaded.history) == 2
    assert loaded.history[0].note == "first step"


def test_load_session_missing_file_raises(tmp_path: Path):
    with pytest.raises(SessionError, match="No session file"):
        load_session(tmp_path)


def test_load_session_corrupt_json_raises(tmp_path: Path):
    (tmp_path / "session.json").write_text("{not json", encoding="utf-8")
    with pytest.raises(SessionError, match="unreadable"):
        load_session(tmp_path)


def test_load_session_unknown_state_raises(tmp_path: Path):
    (tmp_path / "session.json").write_text(
        json.dumps({"state": "exploring_mars", "history": []}),
        encoding="utf-8",
    )
    with pytest.raises(SessionError, match="Unknown state"):
        load_session(tmp_path)


def test_load_session_forward_compatible_extra_fields(tmp_path: Path):
    """A session.json written by a newer AgentBoot with extra fields
    should still load — we just ignore unknown top-level keys."""
    payload = {
        "id": "abc123",
        "created_at": 1234567890.0,
        "state": "recommending",
        "history": [
            {"state": "detecting", "at": 1.0, "note": ""},
            {"state": "recommending", "at": 2.0, "note": ""},
        ],
        "future_field_v2": {"unknown": True},
    }
    (tmp_path / "session.json").write_text(json.dumps(payload), encoding="utf-8")
    loaded = load_session(tmp_path)
    assert loaded.id == "abc123"
    assert loaded.state == State.RECOMMENDING


# ---------------------------------------------------------------------------
# Convenience setters persist
# ---------------------------------------------------------------------------


def test_convenience_setters_persist_immediately(tmp_path: Path):
    s = InstallSession()
    s.save(tmp_path)
    s.set_hardware_profile({"cpu": "Intel"})
    # Re-read from disk to confirm it was flushed
    on_disk = json.loads((tmp_path / "session.json").read_text(encoding="utf-8"))
    assert on_disk["hardware_profile"] == {"cpu": "Intel"}


def test_set_iso_records_path_and_hash(tmp_path: Path):
    s = InstallSession()
    s.save(tmp_path)
    s.set_iso("/tmp/ubuntu.iso", "deadbeef" * 8)
    assert s.iso_path == "/tmp/ubuntu.iso"
    assert s.iso_sha256 == "deadbeef" * 8
