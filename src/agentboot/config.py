"""User-level configuration for AgentBoot.

A configuration file lets an operator set defaults that don't belong on
every CLI invocation: which LLM backend to prefer, where to keep
sessions and downloaded ISOs, which cloud API keys to hand to the
router. The format is JSON — stdlib-only, round-trippable, and easy to
generate from shell scripts or secret stores.

Resolution order (first hit wins):

    1. The path passed explicitly to :func:`load_config`.
    2. ``$AGENTBOOT_CONFIG`` environment variable.
    3. ``<XDG_CONFIG_HOME>/agentboot/config.json`` (Linux/macOS).
    4. ``%APPDATA%\\AgentBoot\\config.json`` (Windows).
    5. No file — return an empty :class:`Config`.

API keys may alternatively be set via ``ANTHROPIC_API_KEY`` /
``GOOGLE_API_KEY``; :meth:`Config.merged_env` surfaces whichever is
present so callers don't need to check both.
"""

from __future__ import annotations

import json
import logging
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)


@dataclass
class Config:
    """Loaded configuration; all fields optional."""

    model_path: Optional[str] = None
    session_dir: Optional[str] = None
    download_dir: Optional[str] = None
    anthropic_api_key: Optional[str] = None
    google_api_key: Optional[str] = None
    preferred_llm: Optional[str] = None  # "local" | "anthropic" | "gemini"
    log_level: str = "INFO"
    extras: dict[str, Any] = field(default_factory=dict)

    # ----- resolution helpers --------------------------------------

    def merged_anthropic_key(self) -> Optional[str]:
        return self.anthropic_api_key or os.environ.get("ANTHROPIC_API_KEY")

    def merged_google_key(self) -> Optional[str]:
        return self.google_api_key or os.environ.get("GOOGLE_API_KEY")

    def resolved_model_path(self) -> Optional[Path]:
        if self.model_path:
            return Path(self.model_path).expanduser()
        return None

    def to_dict(self) -> dict[str, Any]:
        return {
            "model_path": self.model_path,
            "session_dir": self.session_dir,
            "download_dir": self.download_dir,
            "anthropic_api_key": self.anthropic_api_key,
            "google_api_key": self.google_api_key,
            "preferred_llm": self.preferred_llm,
            "log_level": self.log_level,
            "extras": self.extras,
        }


# ---------------------------------------------------------------------------
# Resolution
# ---------------------------------------------------------------------------


def default_config_path() -> Path:
    """Return the platform-appropriate default config path."""
    if sys.platform == "win32":
        base = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
        return Path(base) / "AgentBoot" / "config.json"
    xdg = os.environ.get("XDG_CONFIG_HOME")
    if xdg:
        return Path(xdg) / "agentboot" / "config.json"
    return Path.home() / ".config" / "agentboot" / "config.json"


def load_config(path: Optional[Path | str] = None) -> Config:
    """Return a :class:`Config`, from whichever file is resolvable.

    A missing or empty file is not an error — the returned config just
    has all-``None`` defaults. Malformed JSON raises ``ValueError`` so
    the operator learns about the typo rather than silently losing
    their settings.
    """
    resolved = _resolve_config_path(path)
    if resolved is None or not resolved.is_file():
        logger.debug("No config file found; using defaults")
        return Config()

    try:
        raw = resolved.read_text(encoding="utf-8")
    except OSError as exc:
        raise ValueError(f"Could not read config at {resolved}: {exc}") from exc
    if not raw.strip():
        return Config()

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Config at {resolved} is not valid JSON: {exc}") from exc

    if not isinstance(data, dict):
        raise ValueError(
            f"Config at {resolved} must be a JSON object at top level, "
            f"got {type(data).__name__}"
        )

    known = {
        "model_path", "session_dir", "download_dir",
        "anthropic_api_key", "google_api_key",
        "preferred_llm", "log_level",
    }
    kwargs: dict[str, Any] = {k: data[k] for k in known if k in data}
    extras = {k: v for k, v in data.items() if k not in known}
    if extras:
        kwargs["extras"] = extras
    return Config(**kwargs)


def save_config(config: Config, path: Optional[Path | str] = None) -> Path:
    """Write *config* to disk as pretty JSON; return the path used."""
    target = Path(path) if path else default_config_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    data = {k: v for k, v in config.to_dict().items() if v is not None and v != {}}
    target.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")
    return target


def _resolve_config_path(explicit: Optional[Path | str]) -> Optional[Path]:
    if explicit:
        return Path(explicit).expanduser()
    env = os.environ.get("AGENTBOOT_CONFIG")
    if env:
        return Path(env).expanduser()
    default = default_config_path()
    return default if default.is_file() else None
