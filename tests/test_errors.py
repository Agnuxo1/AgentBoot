"""The unified exception hierarchy."""

from __future__ import annotations

import pytest

from agentboot.errors import (
    AgentBootError,
    ChecksumMismatch,
    FlashError,
    LLMError,
    LLMUnavailable,
    ProtocolError,
    SessionError,
)


@pytest.mark.parametrize("cls", [
    LLMError, LLMUnavailable, ChecksumMismatch, FlashError,
    SessionError, ProtocolError,
])
def test_every_subclass_is_an_agentboot_error(cls):
    assert issubclass(cls, AgentBootError)


def test_legacy_base_classes_still_work():
    """Existing except-clauses must keep working."""
    assert issubclass(LLMError, RuntimeError)
    assert issubclass(ChecksumMismatch, RuntimeError)
    assert issubclass(FlashError, RuntimeError)
    assert issubclass(SessionError, RuntimeError)
    assert issubclass(ProtocolError, ValueError)


def test_llm_unavailable_is_an_llm_error():
    assert issubclass(LLMUnavailable, LLMError)


def test_catching_agentboot_error_catches_subpackage_errors():
    """The whole point of the hierarchy: one except covers everything."""
    caught = 0
    for cls in (LLMError, ChecksumMismatch, FlashError, SessionError, ProtocolError):
        try:
            raise cls("boom")
        except AgentBootError:
            caught += 1
    assert caught == 5
