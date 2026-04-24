"""Base exception class for the whole package.

Kept in its own import-light module so every subpackage can subclass it
without pulling in the rest of the public API (which would cause
circular imports).
"""

from __future__ import annotations


class AgentBootError(Exception):
    """Base class for every AgentBoot-specific error."""
