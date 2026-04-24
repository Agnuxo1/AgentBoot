"""Central logging setup.

AgentBoot emits logs at four meaningful levels:

- ``DEBUG``    — fine-grained module trace (what URL, what bytes written)
- ``INFO``     — phase transitions, user-visible progress
- ``WARNING``  — recoverable oddity (server ignored Range, no checksum file)
- ``ERROR``    — aborted a phase; caller decides whether to retry

The :func:`setup_logging` helper applies a single consistent format so
``agentboot detect``, ``agentboot install``, and embedded uses all
produce the same log shape. It's idempotent — re-calling it with a
different level updates the root logger rather than adding handlers.
"""

from __future__ import annotations

import logging
import sys
from typing import Optional, TextIO

_DEFAULT_FORMAT = "%(asctime)s %(levelname)-7s %(name)s: %(message)s"
_DEFAULT_DATEFMT = "%Y-%m-%d %H:%M:%S"

_CONFIGURED = False


def setup_logging(
    level: str | int = "INFO",
    stream: Optional[TextIO] = None,
    fmt: str = _DEFAULT_FORMAT,
    datefmt: str = _DEFAULT_DATEFMT,
) -> None:
    """Configure the root logger with AgentBoot's standard format.

    Called automatically from :func:`agentboot.cli.main`. Library
    callers that embed AgentBoot should call this once near startup,
    or set up their own logging and skip this helper entirely.
    """
    global _CONFIGURED

    if isinstance(level, str):
        numeric = logging.getLevelName(level.upper())
        if not isinstance(numeric, int):
            raise ValueError(f"Unknown log level: {level!r}")
        level = numeric

    root = logging.getLogger()
    root.setLevel(level)

    if _CONFIGURED:
        # Reuse existing handler, just update its level + formatter.
        for h in root.handlers:
            h.setLevel(level)
            h.setFormatter(logging.Formatter(fmt, datefmt=datefmt))
        return

    handler = logging.StreamHandler(stream or sys.stderr)
    handler.setLevel(level)
    handler.setFormatter(logging.Formatter(fmt, datefmt=datefmt))
    # Remove any pre-existing handlers (e.g. basicConfig from a test).
    for h in list(root.handlers):
        root.removeHandler(h)
    root.addHandler(handler)
    _CONFIGURED = True


def reset_for_tests() -> None:
    """Tear down handlers — used by test fixtures to avoid state leaks."""
    global _CONFIGURED
    root = logging.getLogger()
    for h in list(root.handlers):
        root.removeHandler(h)
    _CONFIGURED = False
