"""Install session: state machine + JSON persistence.

The session is *the* long-lived object during an install. Everything
the orchestrator does — detecting hardware, recommending an OS,
downloading an ISO, flashing it, writing configs, rebooting — is
recorded in a session file so a crash or an operator pause can be
resumed exactly where it left off.

Persistence format: a single JSON document at ``<session_dir>/session.json``,
written atomically on every state change (temp file + rename).
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
import time
import uuid
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)


from agentboot._errors import AgentBootError


class SessionError(AgentBootError, RuntimeError):
    """Raised on invalid state transitions or corrupt session data."""


class State(str, Enum):
    """States an install session moves through.

    The string values are persisted to disk, so don't rename them
    without a migration. Adding new states is backwards-compatible.
    """

    INIT         = "init"
    DETECTING    = "detecting"
    RECOMMENDING = "recommending"
    DOWNLOADING  = "downloading"
    FLASHING     = "flashing"
    CONFIGURING  = "configuring"
    INSTALLING   = "installing"
    VERIFIED     = "verified"
    DONE         = "done"
    FAILED       = "failed"


# Legal forward transitions. Backwards jumps (e.g. DETECTING ← FLASHING)
# are not allowed except via an explicit .reset() call.
_TRANSITIONS: dict[State, set[State]] = {
    State.INIT:         {State.DETECTING, State.FAILED},
    State.DETECTING:    {State.RECOMMENDING, State.FAILED},
    State.RECOMMENDING: {State.DOWNLOADING, State.FAILED, State.CONFIGURING},
    State.DOWNLOADING:  {State.FLASHING, State.FAILED},
    State.FLASHING:     {State.CONFIGURING, State.FAILED},
    State.CONFIGURING:  {State.INSTALLING, State.FAILED},
    State.INSTALLING:   {State.VERIFIED, State.FAILED},
    State.VERIFIED:     {State.DONE, State.FAILED},
    State.DONE:         set(),
    State.FAILED:       {State.DETECTING},  # allow retry from scratch
}


@dataclass
class HistoryEntry:
    state: State
    at: float                  # unix timestamp
    note: str = ""

    def to_dict(self) -> dict:
        return {"state": self.state.value, "at": self.at, "note": self.note}


@dataclass
class InstallSession:
    """The durable state of one install."""

    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    created_at: float = field(default_factory=time.time)
    state: State = State.INIT
    history: list[HistoryEntry] = field(default_factory=list)

    # Artifacts and decisions collected along the way. All optional —
    # early states haven't computed them yet.
    hardware_profile: Optional[dict] = None
    os_recommendation: Optional[dict] = None
    iso_path: Optional[str] = None
    iso_sha256: Optional[str] = None
    target_device_id: Optional[str] = None
    autoinstall_files: list[dict] = field(default_factory=list)
    error: Optional[str] = None

    # Bookkeeping
    session_dir: Optional[str] = None   # absolute path; set when persisted

    # ----------------------------------------------------------------
    # Transitions
    # ----------------------------------------------------------------

    def transition(self, new_state: State, *, note: str = "") -> None:
        """Move to ``new_state`` if the transition is legal, else raise."""
        if new_state not in _TRANSITIONS[self.state]:
            raise SessionError(
                f"Illegal transition: {self.state.value} → {new_state.value}. "
                f"Legal from here: {sorted(s.value for s in _TRANSITIONS[self.state])}"
            )
        self.history.append(HistoryEntry(state=new_state, at=time.time(), note=note))
        self.state = new_state
        if new_state == State.FAILED and note:
            self.error = note
        self.save()

    def reset(self) -> None:
        """Discard progress and return to INIT. Callers use this after a
        failure when they want to retry from scratch."""
        self.history.append(HistoryEntry(state=State.INIT, at=time.time(), note="reset"))
        self.state = State.INIT
        self.error = None
        self.save()

    # ----------------------------------------------------------------
    # Persistence
    # ----------------------------------------------------------------

    def to_dict(self) -> dict:
        d = asdict(self)
        d["state"] = self.state.value
        d["history"] = [h.to_dict() for h in self.history]
        return d

    def save(self, session_dir: Optional[Path | str] = None) -> Path:
        """Atomically write the session to disk.

        If ``session_dir`` is provided it overrides :attr:`session_dir`;
        otherwise the last known directory is used. At least one of
        them must be set.
        """
        target_dir = Path(session_dir) if session_dir else Path(self.session_dir) if self.session_dir else None
        if target_dir is None:
            raise SessionError("save() requires session_dir on first call")
        target_dir.mkdir(parents=True, exist_ok=True)
        self.session_dir = str(target_dir.resolve())
        target_file = target_dir / "session.json"

        payload = json.dumps(self.to_dict(), indent=2, sort_keys=False, default=str)
        # Atomic replace: write to a temp file in the same directory,
        # then os.replace.
        fd, tmp_path = tempfile.mkstemp(
            prefix=".session-", suffix=".tmp", dir=str(target_dir),
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(payload)
            os.replace(tmp_path, target_file)
        except Exception:
            # Best-effort cleanup on failure
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise
        return target_file

    # ----------------------------------------------------------------
    # Convenience setters — each saves on update so a crash between
    # setters loses at most the last step, not earlier work.
    # ----------------------------------------------------------------

    def set_hardware_profile(self, profile: dict) -> None:
        self.hardware_profile = profile
        self.save()

    def set_os_recommendation(self, rec: dict) -> None:
        self.os_recommendation = rec
        self.save()

    def set_iso(self, path: str, sha256: str) -> None:
        self.iso_path = path
        self.iso_sha256 = sha256
        self.save()

    def set_target_device(self, device_id: str) -> None:
        self.target_device_id = device_id
        self.save()

    def set_autoinstall_files(self, files: list[dict]) -> None:
        self.autoinstall_files = files
        self.save()


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------


def load_session(session_dir: Path | str) -> InstallSession:
    """Read ``session.json`` from disk and return a :class:`InstallSession`.

    Raises :class:`SessionError` if the file is missing or unreadable.
    Unknown fields (forward compatibility) are silently dropped;
    unknown state values raise so we don't silently corrupt a session
    from a newer AgentBoot version.
    """
    d = Path(session_dir)
    f = d / "session.json"
    if not f.is_file():
        raise SessionError(f"No session file at {f}")
    try:
        payload = json.loads(f.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SessionError(f"Session file at {f} is unreadable: {exc}") from exc

    try:
        state = State(payload.get("state", "init"))
    except ValueError as exc:
        raise SessionError(
            f"Unknown state {payload.get('state')!r}; session was likely "
            "written by a newer AgentBoot version."
        ) from exc

    history = [
        HistoryEntry(state=State(h["state"]), at=float(h["at"]), note=h.get("note", ""))
        for h in payload.get("history", [])
    ]

    # Only pass known fields to the constructor — forward compatible.
    allowed = {
        "id", "created_at", "hardware_profile", "os_recommendation",
        "iso_path", "iso_sha256", "target_device_id",
        "autoinstall_files", "error",
    }
    kwargs: dict[str, Any] = {k: payload[k] for k in allowed if k in payload}
    session = InstallSession(**kwargs, state=state, history=history)
    session.session_dir = str(d.resolve())
    return session
