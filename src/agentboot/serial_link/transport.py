"""Serial transports.

The :class:`Transport` protocol is the small, testable surface the
rest of AgentBoot talks to. A :class:`SerialTransport` wraps
``pyserial`` for real hardware; :class:`NullTransport` is a
thread-safe in-memory loopback used by unit tests.
"""

from __future__ import annotations

import logging
import threading
from queue import Empty, Queue
from typing import Optional, Protocol

from agentboot.serial_link.protocol import (
    MAX_FRAME_BYTES,
    Message,
    ProtocolError,
    decode_message,
    encode_message,
)

logger = logging.getLogger(__name__)


class Transport(Protocol):
    """A bidirectional framed message channel."""

    def send(self, msg: Message) -> None: ...
    def recv(self, timeout: Optional[float] = None) -> Message: ...
    def close(self) -> None: ...


# ---------------------------------------------------------------------------
# Real hardware — pyserial
# ---------------------------------------------------------------------------


class SerialTransport:
    """pyserial-backed :class:`Transport`.

    Creation imports ``pyserial`` lazily; AgentBoot only has the
    dependency in the ``[serial]`` extra. If the caller tries to use
    this without installing it, we give a clear error at construction
    time rather than at first ``send()``.
    """

    def __init__(self, port: str, baud: int = 115200, read_timeout: float = 30.0) -> None:
        try:
            import serial  # type: ignore
        except ImportError as exc:
            raise ImportError(
                "pyserial is required for SerialTransport — pip install "
                "'agentboot[serial]'"
            ) from exc
        self._serial_mod = serial
        self._ser = serial.Serial(port, baud, timeout=read_timeout)
        self._read_buffer = bytearray()

    # --- send ----------------------------------------------------------
    def send(self, msg: Message) -> None:
        self._ser.write(encode_message(msg))
        self._ser.flush()

    # --- recv ----------------------------------------------------------
    def recv(self, timeout: Optional[float] = None) -> Message:
        if timeout is not None:
            self._ser.timeout = timeout
        # pyserial's readline reads up to the first \n or until timeout,
        # whichever comes first. That's exactly our framing.
        while True:
            line = self._ser.readline()
            if not line:
                raise TimeoutError("no frame received within timeout")
            if len(line) > MAX_FRAME_BYTES:
                raise ProtocolError(f"frame too large: {len(line)} bytes")
            if line.strip() == b"":
                # Ignore keepalive blank lines.
                continue
            return decode_message(line)

    def close(self) -> None:
        try:
            self._ser.close()
        except Exception:
            logger.exception("closing serial port failed")


# ---------------------------------------------------------------------------
# In-memory loopback — for tests and phone-emulator scenarios
# ---------------------------------------------------------------------------


class NullTransport:
    """Thread-safe paired queue loopback.

    Useful pattern::

        a, b = NullTransport.make_pair()
        a.send(msg)           # msg appears on b
        msg2 = b.recv(1.0)

    Messages flow a → b's inbox and b → a's inbox, so the two halves
    act like opposite ends of a serial link. Each side can be used
    from a different thread.
    """

    def __init__(self, inbox: Queue, outbox: Queue) -> None:
        self._inbox = inbox
        self._outbox = outbox
        self._closed = threading.Event()

    @classmethod
    def make_pair(cls) -> tuple["NullTransport", "NullTransport"]:
        q_a, q_b = Queue(), Queue()
        # a reads from q_a, writes to q_b; b reads from q_b, writes to q_a.
        a = cls(inbox=q_a, outbox=q_b)
        b = cls(inbox=q_b, outbox=q_a)
        return a, b

    def send(self, msg: Message) -> None:
        if self._closed.is_set():
            raise ConnectionError("transport is closed")
        # Round-trip encode/decode to catch schema errors like a real link.
        frame = encode_message(msg)
        self._outbox.put(decode_message(frame))

    def recv(self, timeout: Optional[float] = None) -> Message:
        try:
            return self._inbox.get(timeout=timeout)
        except Empty as exc:
            raise TimeoutError("no frame received within timeout") from exc

    def close(self) -> None:
        self._closed.set()
