"""Agent orchestrator: the state machine that drives an install.

A full install moves through a small number of well-defined states:

    DETECTING → RECOMMENDING → DOWNLOADING → FLASHING → CONFIGURING
              → INSTALLING → VERIFIED → DONE

Each state's entry logic is idempotent: restarting from a persisted
session recomputes the downstream outputs rather than re-running
destructive actions. This is what lets a phone-side operator pause
on a subway stop and resume twenty minutes later.

Public API::

    from agentboot.agent import InstallSession, State, load_session
"""

from __future__ import annotations

from agentboot.agent.session import (
    InstallSession,
    SessionError,
    State,
    load_session,
)
from agentboot.agent.orchestrator import Orchestrator

__all__ = [
    "InstallSession",
    "SessionError",
    "State",
    "load_session",
    "Orchestrator",
]
