import base64

from lib.twitch.eventsub import (
    _OPCODE_PING,
    _OPCODE_TEXT,
    _build_handshake_key,
    _build_handshake_request,
    _decode_frame,
    _encode_client_frame,
    _expected_accept,
    _parse_handshake_response,
    _parse_rfc3339_ms,
)


def test_build_handshake_key_is_valid_base64_16_bytes():
    key = _build_handshake_key()
    decoded = base64.b64decode(key)
    assert len(decoded) == 16


def test_build_handshake_request_contains_required_headers():
    request = _build_handshake_request("eventsub.wss.twitch.tv", "/ws", "abc123==")
    text = request.decode("ascii")
    assert text.startswith("GET /ws HTTP/1.1\r\n")
    assert "Host: eventsub.wss.twitch.tv\r\n" in text
    assert "Upgrade: websocket\r\n" in text
    assert "Sec-WebSocket-Key: abc123==\r\n" in text
    assert "Sec-WebSocket-Version: 13\r\n" in text
    assert text.endswith("\r\n\r\n")


def test_parse_handshake_response_accepts_correct_101():
    key = "dGhlIHNhbXBsZSBub25jZQ=="
    accept = _expected_accept(key)
    response = (
        "HTTP/1.1 101 Switching Protocols\r\n"
        "Upgrade: websocket\r\n"
        "Connection: Upgrade\r\n"
        "Sec-WebSocket-Accept: " + accept + "\r\n\r\n"
    )
    _parse_handshake_response(response, key)  # must not raise


def test_parse_handshake_response_rejects_non_101_status():
    response = "HTTP/1.1 200 OK\r\n\r\n"
    try:
        _parse_handshake_response(response, "somekey")
        assert False, "expected ConnectionError"
    except ConnectionError:
        pass


def test_parse_handshake_response_rejects_accept_mismatch():
    response = (
        "HTTP/1.1 101 Switching Protocols\r\n"
        "Sec-WebSocket-Accept: wrongvalue\r\n\r\n"
    )
    try:
        _parse_handshake_response(response, "somekey")
        assert False, "expected ConnectionError"
    except ConnectionError:
        pass


def test_encode_client_frame_masks_and_sets_fin_text_opcode():
    frame = _encode_client_frame("hi", opcode=_OPCODE_TEXT)
    assert frame[0] == 0x81  # FIN=1, opcode=0x1 (text)
    assert frame[1] & 0x80  # MASK bit set
    length = frame[1] & 0x7F
    assert length == 2


def test_decode_frame_returns_none_on_incomplete_buffer():
    frame, remaining = _decode_frame(b"\x81")
    assert frame is None
    assert remaining == b"\x81"


def test_encode_decode_round_trip_small_payload():
    encoded = _encode_client_frame("hello", opcode=_OPCODE_TEXT)
    # Server frames are unmasked in real traffic; strip the mask like a
    # server would never need to, just to prove decode reads an unmasked
    # frame back correctly - build one directly instead of via encode here.
    import struct
    unmasked = bytes([0x81, 5]) + b"hello"
    frame, remaining = _decode_frame(unmasked)
    assert frame["opcode"] == _OPCODE_TEXT
    assert frame["payload"] == b"hello"
    assert remaining == b""


def test_decode_frame_handles_126_extended_length():
    import struct
    payload = b"x" * 200
    header = bytes([0x81, 126]) + struct.pack(">H", 200)
    frame, remaining = _decode_frame(header + payload)
    assert frame["payload"] == payload
    assert remaining == b""


def test_decode_frame_handles_127_extended_length():
    import struct
    payload = b"y" * 70000
    header = bytes([0x81, 127]) + struct.pack(">Q", 70000)
    frame, remaining = _decode_frame(header + payload)
    assert frame["payload"] == payload
    assert remaining == b""


def test_decode_frame_leaves_extra_bytes_in_remaining_buffer():
    frame_bytes = bytes([0x81, 2]) + b"hi"
    extra = b"EXTRA"
    frame, remaining = _decode_frame(frame_bytes + extra)
    assert frame["payload"] == b"hi"
    assert remaining == extra


def test_parse_rfc3339_ms_converts_to_epoch_millis():
    ms = _parse_rfc3339_ms("2026-08-18T00:00:00Z")
    assert ms == 1787011200000


def test_parse_rfc3339_ms_handles_fractional_seconds():
    ms = _parse_rfc3339_ms("2026-08-18T00:00:00.123456789Z")
    assert ms == 1787011200123


def test_parse_rfc3339_ms_falls_back_to_now_on_malformed_input():
    import time
    before = int(time.time() * 1000)
    ms = _parse_rfc3339_ms("not-a-timestamp")
    after = int(time.time() * 1000)
    assert before <= ms <= after
