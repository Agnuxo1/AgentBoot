"""JSON-over-serial link between the AgentBoot phone agent and a
bare-metal target running the :mod:`collector` script.

The protocol is intentionally tiny so it works over the lowest common
denominator: 115200-baud 8N1 serial, no flow control. Every frame is
a single line of JSON terminated by ``\\n``. That gives us:

- Natural framing — ``readline()`` is the unit of work.
- Easy debugging — you can paste frames into ``picocom`` / ``minicom``.
- No binary payloads, no base64, no length prefixes.

Public API::

    from agentboot.serial_link import encode_message, decode_message
    from agentboot.serial_link import SerialTransport, NullTransport
"""

from __future__ import annotations

from agentboot.serial_link.protocol import (
    Message,
    ProtocolError,
    decode_message,
    encode_message,
    make_command,
    make_response,
    make_event,
    make_error,
)
from agentboot.serial_link.transport import (
    SerialTransport,
    NullTransport,
    Transport,
)

__all__ = [
    "Message",
    "ProtocolError",
    "decode_message",
    "encode_message",
    "make_command",
    "make_response",
    "make_event",
    "make_error",
    "Transport",
    "SerialTransport",
    "NullTransport",
]
