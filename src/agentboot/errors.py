"""Unified AgentBoot exception hierarchy.

Every error raised by AgentBoot code inherits from
:class:`agentboot._errors.AgentBootError` so callers can catch the
whole family in one ``except`` clause::

    from agentboot.errors import AgentBootError
    try:
        orchestrator.flash(...)
    except AgentBootError as exc:
        log.error("AgentBoot aborted: %s", exc)

Subpackage-specific exceptions continue to live in their own modules
and are re-exported here for convenience.
"""

from __future__ import annotations

from agentboot._errors import AgentBootError
from agentboot.llm.base import LLMError, LLMUnavailable
from agentboot.iso.downloader import ChecksumMismatch
from agentboot.flasher.flash import FlashError
from agentboot.agent.session import SessionError
from agentboot.serial_link.protocol import ProtocolError

__all__ = [
    "AgentBootError",
    "LLMError",
    "LLMUnavailable",
    "ChecksumMismatch",
    "FlashError",
    "SessionError",
    "ProtocolError",
]
