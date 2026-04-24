"""setup_logging helper."""

from __future__ import annotations

import io
import logging

import pytest

from agentboot.logging_setup import reset_for_tests, setup_logging


@pytest.fixture(autouse=True)
def _clean():
    reset_for_tests()
    yield
    reset_for_tests()


def test_setup_logging_installs_single_handler():
    setup_logging("INFO")
    assert len(logging.getLogger().handlers) == 1


def test_setup_logging_is_idempotent():
    setup_logging("INFO")
    setup_logging("DEBUG")
    assert len(logging.getLogger().handlers) == 1
    assert logging.getLogger().level == logging.DEBUG


def test_setup_logging_accepts_numeric_level():
    setup_logging(logging.WARNING)
    assert logging.getLogger().level == logging.WARNING


def test_setup_logging_rejects_unknown_level():
    with pytest.raises(ValueError, match="Unknown log level"):
        setup_logging("NOTALEVEL")


def test_log_output_contains_name_and_message():
    buf = io.StringIO()
    setup_logging("INFO", stream=buf)
    logging.getLogger("agentboot.test").info("hello world")
    text = buf.getvalue()
    assert "agentboot.test" in text
    assert "hello world" in text
    assert "INFO" in text
