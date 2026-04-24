"""Tests for the JSON-over-serial protocol and loopback transport."""

from __future__ import annotations

import json
import threading

import pytest

from agentboot.serial_link import (
    Message,
    NullTransport,
    ProtocolError,
    decode_message,
    encode_message,
    make_command,
    make_error,
    make_event,
    make_response,
)
from agentboot.serial_link.protocol import MAX_FRAME_BYTES


# ---------------------------------------------------------------------------
# Encoding
# ---------------------------------------------------------------------------


def test_encode_message_terminates_with_newline():
    msg = make_command("ping")
    blob = encode_message(msg)
    assert blob.endswith(b"\n")
    # Must contain no embedded newlines in the payload
    assert blob.count(b"\n") == 1


def test_encode_message_is_utf8_json():
    msg = make_event("detected", {"model": "Café 9000"})
    blob = encode_message(msg)
    obj = json.loads(blob.decode("utf-8"))
    assert obj["data"]["model"] == "Café 9000"


def test_encode_rejects_oversized_frame():
    msg = make_command("big", {"payload": "x" * (MAX_FRAME_BYTES + 10)})
    with pytest.raises(ProtocolError, match="too large"):
        encode_message(msg)


# ---------------------------------------------------------------------------
# Decoding
# ---------------------------------------------------------------------------


def test_decode_roundtrip():
    msg = make_command("hw.report", {"deep": True})
    round_tripped = decode_message(encode_message(msg))
    assert round_tripped.kind == "cmd"
    assert round_tripped.name == "hw.report"
    assert round_tripped.data == {"deep": True}
    assert round_tripped.id == msg.id


def test_decode_rejects_invalid_json():
    with pytest.raises(ProtocolError, match="invalid JSON"):
        decode_message(b"{not-json\n")


def test_decode_rejects_non_object():
    with pytest.raises(ProtocolError, match="not a JSON object"):
        decode_message(b'[1,2,3]\n')


def test_decode_rejects_unknown_kind():
    bad = b'{"v":1,"id":"a","kind":"mystery"}\n'
    with pytest.raises(ProtocolError, match="unknown kind"):
        decode_message(bad)


def test_decode_rejects_unsupported_version():
    bad = b'{"v":99,"id":"a","kind":"cmd","name":"x"}\n'
    with pytest.raises(ProtocolError, match="unsupported protocol version"):
        decode_message(bad)


def test_decode_cmd_requires_name():
    with pytest.raises(ProtocolError, match="'name'"):
        decode_message(b'{"v":1,"id":"a","kind":"cmd"}\n')


def test_decode_response_requires_ok_bool():
    with pytest.raises(ProtocolError, match="'ok'"):
        decode_message(b'{"v":1,"id":"a","kind":"response","ok":"yes"}\n')


def test_decode_error_requires_code():
    with pytest.raises(ProtocolError, match="'code'"):
        decode_message(b'{"v":1,"id":"a","kind":"error","message":"m"}\n')


def test_decode_rejects_empty_frame():
    with pytest.raises(ProtocolError, match="empty"):
        decode_message(b"\n")


def test_decode_rejects_missing_id():
    with pytest.raises(ProtocolError, match="'id'"):
        decode_message(b'{"v":1,"kind":"cmd","name":"x"}\n')


# ---------------------------------------------------------------------------
# Factories
# ---------------------------------------------------------------------------


def test_make_command_generates_unique_ids():
    ids = {make_command("x").id for _ in range(100)}
    assert len(ids) == 100


def test_make_response_preserves_correlation_id():
    cmd = make_command("ping")
    resp = make_response(cmd.id, ok=True, data={"pong": True})
    assert resp.id == cmd.id


def test_make_error_factory():
    err = make_error("abc", code="BAD", message="nope")
    round_tripped = decode_message(encode_message(err))
    assert round_tripped.kind == "error"
    assert round_tripped.code == "BAD"
    assert round_tripped.message == "nope"


def test_make_event_factory():
    evt = make_event("progress", {"pct": 42})
    round_tripped = decode_message(encode_message(evt))
    assert round_tripped.kind == "event"
    assert round_tripped.name == "progress"
    assert round_tripped.data == {"pct": 42}


# ---------------------------------------------------------------------------
# NullTransport loopback
# ---------------------------------------------------------------------------


def test_null_transport_pair_passes_messages():
    a, b = NullTransport.make_pair()
    a.send(make_command("ping"))
    msg = b.recv(timeout=1.0)
    assert msg.kind == "cmd"
    assert msg.name == "ping"


def test_null_transport_recv_times_out():
    a, b = NullTransport.make_pair()
    with pytest.raises(TimeoutError):
        a.recv(timeout=0.05)


def test_null_transport_bidirectional():
    a, b = NullTransport.make_pair()
    a.send(make_command("ping"))
    cmd = b.recv(1.0)
    b.send(make_response(cmd.id, ok=True))
    resp = a.recv(1.0)
    assert resp.kind == "response"
    assert resp.id == cmd.id
    assert resp.ok is True


def test_null_transport_closed_rejects_send():
    a, b = NullTransport.make_pair()
    a.close()
    with pytest.raises(ConnectionError):
        a.send(make_command("x"))


def test_null_transport_works_across_threads():
    a, b = NullTransport.make_pair()
    received: list[Message] = []
    done = threading.Event()

    def reader():
        received.append(b.recv(2.0))
        done.set()

    t = threading.Thread(target=reader)
    t.start()
    a.send(make_command("hw.report"))
    assert done.wait(2.0)
    t.join()
    assert received[0].name == "hw.report"
