"""JSON-over-serial frame format.

Each frame is one JSON object per line. Four message kinds::

    {"v":1, "id":"abc123", "kind":"cmd",      "name":"hw.report"}
    {"v":1, "id":"abc123", "kind":"response", "ok":true, "data":{...}}
    {"v":1, "id":"evt001", "kind":"event",    "name":"progress", "data":{...}}
    {"v":1, "id":"abc123", "kind":"error",    "code":"TIMEOUT", "message":"..."}

The ``v`` field is the protocol version; the only supported value
right now is ``1``. An ``id`` correlates responses to commands. Events
are one-way notifications and may omit correlation.

Design notes:

- The wire format is UTF-8 JSON. We do not allow embedded newlines in
  the JSON (``separators=(',', ':')`` with no indent), so a single
  ``readline()`` always produces one complete frame.
- We reject oversized frames (>= 256 KiB) to protect the phone-side
  agent from a misbehaving target flooding the link.
"""

from __future__ import annotations

import json
import secrets
from dataclasses import dataclass, field
from typing import Any, Literal, Optional

PROTOCOL_VERSION = 1
MAX_FRAME_BYTES = 256 * 1024
MessageKind = Literal["cmd", "response", "event", "error"]


from agentboot._errors import AgentBootError


class ProtocolError(AgentBootError, ValueError):
    """Raised when a received frame is malformed or violates the schema."""


@dataclass
class Message:
    """A decoded frame."""

    kind: MessageKind
    id: str
    version: int = PROTOCOL_VERSION
    name: Optional[str] = None           # for cmd / event
    ok: Optional[bool] = None            # for response
    code: Optional[str] = None           # for error
    message: Optional[str] = None        # for error
    data: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        d: dict = {"v": self.version, "id": self.id, "kind": self.kind}
        if self.name is not None:
            d["name"] = self.name
        if self.ok is not None:
            d["ok"] = self.ok
        if self.code is not None:
            d["code"] = self.code
        if self.message is not None:
            d["message"] = self.message
        if self.data:
            d["data"] = self.data
        return d


# ---------------------------------------------------------------------------
# Encoding
# ---------------------------------------------------------------------------


def encode_message(msg: Message) -> bytes:
    """Encode ``msg`` as a single UTF-8 JSON line ending in ``\\n``."""
    payload = json.dumps(
        msg.to_dict(), ensure_ascii=False, separators=(",", ":")
    )
    if "\n" in payload:
        # Should not happen with ensure_ascii=False and no indent, but
        # we double-check so a pathological input can never break
        # framing.
        raise ProtocolError("encoded frame contains a newline")
    blob = (payload + "\n").encode("utf-8")
    if len(blob) > MAX_FRAME_BYTES:
        raise ProtocolError(f"frame too large ({len(blob)} > {MAX_FRAME_BYTES})")
    return blob


# ---------------------------------------------------------------------------
# Decoding
# ---------------------------------------------------------------------------


def decode_message(line: bytes | str) -> Message:
    """Decode a single serial line into a :class:`Message`."""
    if isinstance(line, (bytes, bytearray)):
        if len(line) > MAX_FRAME_BYTES:
            raise ProtocolError(f"frame exceeds {MAX_FRAME_BYTES} bytes")
        try:
            text = line.decode("utf-8").rstrip("\r\n")
        except UnicodeDecodeError as exc:
            raise ProtocolError(f"invalid UTF-8: {exc}") from exc
    else:
        text = line.rstrip("\r\n")

    if not text.strip():
        raise ProtocolError("empty frame")

    try:
        obj = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ProtocolError(f"invalid JSON: {exc}") from exc

    if not isinstance(obj, dict):
        raise ProtocolError("frame is not a JSON object")

    version = obj.get("v", 1)
    if version != PROTOCOL_VERSION:
        raise ProtocolError(f"unsupported protocol version {version}")

    kind = obj.get("kind")
    if kind not in ("cmd", "response", "event", "error"):
        raise ProtocolError(f"unknown kind: {kind!r}")

    mid = obj.get("id")
    if not isinstance(mid, str) or not mid:
        raise ProtocolError("missing or empty 'id'")

    # Kind-specific required fields
    if kind in ("cmd", "event") and not isinstance(obj.get("name"), str):
        raise ProtocolError(f"{kind} requires 'name' string")
    if kind == "response" and not isinstance(obj.get("ok"), bool):
        raise ProtocolError("response requires 'ok' boolean")
    if kind == "error" and not isinstance(obj.get("code"), str):
        raise ProtocolError("error requires 'code' string")

    data = obj.get("data", {})
    if not isinstance(data, dict):
        raise ProtocolError("'data' must be an object")

    return Message(
        kind=kind,  # type: ignore[arg-type]
        id=mid,
        version=version,
        name=obj.get("name"),
        ok=obj.get("ok"),
        code=obj.get("code"),
        message=obj.get("message"),
        data=data,
    )


# ---------------------------------------------------------------------------
# Factory helpers
# ---------------------------------------------------------------------------


def _new_id() -> str:
    return secrets.token_hex(6)


def make_command(name: str, data: Optional[dict] = None, *, id: Optional[str] = None) -> Message:
    return Message(kind="cmd", id=id or _new_id(), name=name, data=data or {})


def make_response(cmd_id: str, *, ok: bool, data: Optional[dict] = None) -> Message:
    return Message(kind="response", id=cmd_id, ok=ok, data=data or {})


def make_event(name: str, data: Optional[dict] = None, *, id: Optional[str] = None) -> Message:
    return Message(kind="event", id=id or _new_id(), name=name, data=data or {})


def make_error(cmd_id: str, *, code: str, message: str) -> Message:
    return Message(kind="error", id=cmd_id, code=code, message=message)
