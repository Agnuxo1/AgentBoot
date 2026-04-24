"""High-level install orchestrator.

Drives an :class:`InstallSession` from DETECTING all the way to DONE
by calling into the hardware detector, the OS recommender, the ISO
downloader, the USB flasher and the autoinstall generator in order.

Each phase method is idempotent given a persisted session: running
``.detect()`` twice re-does the detection but does not leave
half-deleted files behind; running ``.flash()`` twice is blocked by
the flasher's safety checks unless the caller explicitly re-plans.

The orchestrator deliberately does not import the LLM router — that
is a concern for the :mod:`agentboot.cli` chat layer, which may want
to summarise detections in natural language. The orchestrator's job
is to move a session through its state machine with no chatty IO.
"""

from __future__ import annotations

import dataclasses
import logging
from pathlib import Path
from typing import Callable, Optional

from agentboot.agent.session import InstallSession, SessionError, State

logger = logging.getLogger(__name__)


class Orchestrator:
    """Phase runner for an :class:`InstallSession`.

    Constructor takes the session and a *session_dir* (where state is
    persisted). Everything else — the ISO download URL, flash target,
    autoinstall profile — is passed per-phase so the same orchestrator
    instance can drive sessions that differ in those details.
    """

    def __init__(self, session: InstallSession, session_dir: Path | str) -> None:
        self.session = session
        self.session_dir = Path(session_dir)
        self.session.save(self.session_dir)

    # ------------------------------------------------------------------
    # Phase 1: detect
    # ------------------------------------------------------------------

    def detect(self) -> dict:
        """Run hardware detection and persist the profile on the session."""
        if self.session.state not in (State.INIT, State.FAILED, State.DETECTING):
            raise SessionError(
                f"detect() cannot run from state {self.session.state.value}; "
                "call session.reset() first."
            )
        if self.session.state != State.DETECTING:
            self.session.transition(State.DETECTING, note="starting hardware detection")

        from agentboot.hardware_detector import HardwareDetector

        det = HardwareDetector()
        profile = det.detect_local()
        profile_dict = _to_jsonable(profile)
        self.session.set_hardware_profile(profile_dict)
        self.session.transition(State.RECOMMENDING, note="hardware detection complete")
        return profile_dict

    # ------------------------------------------------------------------
    # Phase 2: recommend
    # ------------------------------------------------------------------

    def recommend(self, tags_filter: Optional[list[str]] = None, max_results: int = 5) -> list[dict]:
        """Compute OS recommendations and record the top pick."""
        if self.session.state not in (State.RECOMMENDING, State.FAILED):
            raise SessionError(
                f"recommend() cannot run from state {self.session.state.value}"
            )
        if self.session.hardware_profile is None:
            raise SessionError("recommend() requires a hardware_profile; call detect() first")

        from agentboot.hardware_detector import HardwareProfile
        from agentboot.os_compatibility import recommend_os

        profile = HardwareProfile.from_dict(self.session.hardware_profile) \
            if hasattr(HardwareProfile, "from_dict") \
            else _hw_from_dict(self.session.hardware_profile)
        recs = recommend_os(profile, max_results=max_results, tags_filter=tags_filter)
        compat = [r for r in recs if r.compatible]
        if not compat:
            self.session.transition(State.FAILED, note="no compatible OS found")
            return []
        chosen = compat[0]
        chosen_dict = _to_jsonable(chosen)
        self.session.set_os_recommendation(chosen_dict)
        return [_to_jsonable(r) for r in recs[:max_results]]

    # ------------------------------------------------------------------
    # Phase 3: download
    # ------------------------------------------------------------------

    def download(self, destination: Path | str, progress=None) -> str:
        """Download the ISO for the recommended OS, verify, record path+hash."""
        if self.session.state != State.RECOMMENDING:
            raise SessionError(
                f"download() cannot run from state {self.session.state.value}"
            )
        if self.session.os_recommendation is None:
            raise SessionError("download() requires an os_recommendation")

        self.session.transition(State.DOWNLOADING, note="starting ISO download")

        from agentboot.iso import download_iso, find_iso

        rec = self.session.os_recommendation
        arch = (self.session.hardware_profile or {}).get("arch", "x86_64")
        entry = find_iso(rec.get("os_id") or rec.get("name", ""), arch)
        if entry is None:
            # Fall back to the URL inside the recommendation dict if present.
            if rec.get("download_url"):
                url = rec["download_url"]
                dest = Path(destination) / url.rsplit("/", 1)[-1]
                result = download_iso(url, dest, progress=progress)
            else:
                self.session.transition(
                    State.FAILED,
                    note=f"no ISO entry for {rec.get('name')}",
                )
                raise SessionError("no ISO URL available for recommended OS")
        else:
            dest = Path(destination) / entry.filename
            result = download_iso(
                entry.url, dest,
                checksum_url=entry.checksum_url,
                checksum_filename=entry.checksum_filename,
                progress=progress,
            )
        self.session.set_iso(str(result.path), result.sha256)
        self.session.transition(State.FLASHING, note=f"iso downloaded: {result.path}")
        return str(result.path)

    # ------------------------------------------------------------------
    # Phase 4: flash
    # ------------------------------------------------------------------

    def flash(self, target_device_id: str, confirm_token: str, progress=None) -> None:
        """Write the downloaded ISO to the given USB device."""
        if self.session.state != State.FLASHING:
            raise SessionError(
                f"flash() cannot run from state {self.session.state.value}"
            )
        if self.session.iso_path is None:
            raise SessionError("flash() requires iso_path from a successful download")

        from agentboot.flasher import find_device_by_id, flash_iso, plan_flash

        device = find_device_by_id(target_device_id)
        if device is None:
            self.session.transition(
                State.FAILED,
                note=f"target device {target_device_id} not found",
            )
            raise SessionError(f"Device {target_device_id} not present")

        plan = plan_flash(self.session.iso_path, device)
        flash_iso(plan, confirm_token=confirm_token, progress=progress)
        self.session.set_target_device(target_device_id)
        self.session.transition(State.CONFIGURING, note="flash complete")

    # ------------------------------------------------------------------
    # Phase 5: configure (generate autoinstall files)
    # ------------------------------------------------------------------

    def configure(self, profile: "InstallProfileLike") -> list[dict]:
        """Generate auto-install config files based on the recommended OS.

        The caller owns placing the generated files on the bootable
        media; the orchestrator only records metadata in the session.
        """
        if self.session.state != State.CONFIGURING:
            raise SessionError(
                f"configure() cannot run from state {self.session.state.value}"
            )
        if self.session.os_recommendation is None:
            raise SessionError("configure() requires os_recommendation")

        from agentboot.autoinstall import generate_for_os

        os_id = self.session.os_recommendation.get("os_id") \
            or self.session.os_recommendation.get("name", "")
        files = generate_for_os(os_id, profile)
        files_meta = [
            {"path": f.path, "mode": f.mode, "size": len(f.body_bytes)}
            for f in files
        ]
        self.session.set_autoinstall_files(files_meta)
        self.session.transition(State.INSTALLING, note=f"{len(files)} autoinstall file(s)")
        # The actual files are returned so the caller can place them.
        return [{"path": f.path, "contents": f.contents, "mode": f.mode} for f in files]

    # ------------------------------------------------------------------
    # Phase 6 + 7 are driven by the bare-metal target and are outside
    # the phone-side orchestrator's control. We expose simple markers
    # so the operator UI can progress the state when they observe the
    # target booting into the installer / completing it.
    # ------------------------------------------------------------------

    def mark_installing(self, note: str = "operator confirmed boot into installer") -> None:
        if self.session.state != State.INSTALLING:
            raise SessionError(
                f"mark_installing() from state {self.session.state.value}"
            )
        # Already in INSTALLING after configure(); this just annotates.
        self.session.history.append(
            dataclasses.replace(
                self.session.history[-1], note=note
            ) if self.session.history else None  # type: ignore[arg-type]
        )
        self.session.save()

    def mark_verified(self, note: str = "") -> None:
        self.session.transition(State.VERIFIED, note=note or "install verified")

    def mark_done(self, note: str = "") -> None:
        self.session.transition(State.DONE, note=note or "session complete")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# Type alias for "anything the autoinstall generator accepts".
class InstallProfileLike:  # pragma: no cover — alias for typing
    pass


def _to_jsonable(obj) -> dict:
    """Turn any dataclass / nested-dataclass tree into plain dicts."""
    if dataclasses.is_dataclass(obj):
        d = dataclasses.asdict(obj)
    elif hasattr(obj, "to_dict"):
        d = obj.to_dict()
    elif isinstance(obj, dict):
        d = obj
    else:
        d = {"value": obj}
    return d


def _hw_from_dict(d: dict):
    """Rehydrate a HardwareProfile from a persisted dict.

    Not round-trip perfect — some nested dataclass fields are
    reconstructed as plain objects — but good enough for the
    recommend_os scoring routine which reads the dataclass attribute
    tree via getattr.
    """
    from types import SimpleNamespace

    def _ns(x):
        if isinstance(x, dict):
            return SimpleNamespace(**{k: _ns(v) for k, v in x.items()})
        if isinstance(x, list):
            return [_ns(i) for i in x]
        return x

    return _ns(d)
