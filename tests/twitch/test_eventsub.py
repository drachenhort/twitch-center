import base64
import json
import socket

from lib.twitch.eventsub import (
    _OPCODE_TEXT,
    ChatClient,
    _build_handshake_key,
    _build_handshake_request,
    _decode_frame,
    _encode_client_frame,
    _expected_accept,
    _extract_emotes,
    _parse_handshake_response,
    _parse_rfc3339_ms,
    EMOTE_IMAGE_URL_TEMPLATE,
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


def test_encode_client_frame_round_trips_through_manual_unmask():
    # _decode_frame only handles unmasked server->client frames (see its docstring), so it can't
    # be used to decode _encode_client_frame's (masked) output directly. Unmask it by hand here
    # instead, to prove the masking _encode_client_frame applies is actually reversible.
    encoded = _encode_client_frame("hello", opcode=_OPCODE_TEXT)
    assert encoded[0] == 0x80 | _OPCODE_TEXT
    length = encoded[1] & 0x7F
    assert length == 5
    mask_key = encoded[2:6]
    masked_payload = encoded[6:6 + length]
    unmasked_payload = bytes(b ^ mask_key[i % 4] for i, b in enumerate(masked_payload))
    assert unmasked_payload == b"hello"


def test_decode_frame_reads_short_unmasked_text_frame():
    # Real server->client traffic is unmasked; build one directly to prove decode reads it back
    # correctly.
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


def test_extract_emotes_returns_one_entry_for_single_emote_fragment():
    fragments = [{"type": "emote", "text": "Kappa", "emote": {"id": "25"}}]
    assert _extract_emotes(fragments) == [
        {"id": "25", "text": "Kappa", "url": EMOTE_IMAGE_URL_TEMPLATE.format(id="25")}
    ]


def test_extract_emotes_returns_empty_list_for_text_only_message():
    fragments = [{"type": "text", "text": "hello there"}]
    assert _extract_emotes(fragments) == []


def test_extract_emotes_skips_non_emote_fragment_types_in_order():
    fragments = [
        {"type": "text", "text": "hi "},
        {"type": "cheermote", "text": "Cheer100", "cheermote": {"prefix": "Cheer", "bits": 100, "tier": 1}},
        {"type": "emote", "text": "Kappa", "emote": {"id": "25"}},
        {"type": "mention", "text": "@bob", "mention": {"user_id": "1", "user_login": "bob", "user_name": "Bob"}},
        {"type": "emote", "text": "PogChamp", "emote": {"id": "88"}},
    ]
    assert _extract_emotes(fragments) == [
        {"id": "25", "text": "Kappa", "url": EMOTE_IMAGE_URL_TEMPLATE.format(id="25")},
        {"id": "88", "text": "PogChamp", "url": EMOTE_IMAGE_URL_TEMPLATE.format(id="88")},
    ]


def test_extract_emotes_caps_at_six():
    fragments = [
        {"type": "emote", "text": "E%d" % i, "emote": {"id": str(i)}} for i in range(8)
    ]
    result = _extract_emotes(fragments)
    assert len(result) == 6
    assert [e["id"] for e in result] == ["0", "1", "2", "3", "4", "5"]


def test_extract_emotes_skips_fragment_missing_emote_key():
    fragments = [{"type": "emote", "text": "broken"}]
    assert _extract_emotes(fragments) == []


def test_extract_emotes_skips_emote_with_missing_id():
    fragments = [{"type": "emote", "text": "broken", "emote": {}}]
    assert _extract_emotes(fragments) == []


def test_extract_emotes_returns_empty_list_when_fragments_not_a_list():
    assert _extract_emotes(None) == []
    assert _extract_emotes("not a list") == []
    assert _extract_emotes({}) == []


def _server_text_frame(payload_dict):
    payload = json.dumps(payload_dict).encode("utf-8")
    length = len(payload)
    # The brief's original helper assumed length <= 125 always fits in the single length byte,
    # but _WELCOME's JSON serializes to 126 bytes - over that limit. A raw `bytes([0x81, length])`
    # with length=126 collides with the MASK bit range, so the decoder misreads it as a
    # zero-length frame and desyncs the whole stream. Emit the real WS extended-length (126) form
    # for anything over 125 bytes, matching _encode_client_frame's own length encoding.
    if length <= 125:
        header = bytes([0x81, length])
    else:
        import struct
        header = bytes([0x81, 126]) + struct.pack(">H", length)
    return header + payload


def _handshake_response_bytes(key):
    accept = _expected_accept(key)
    return (
        "HTTP/1.1 101 Switching Protocols\r\n"
        "Upgrade: websocket\r\n"
        "Connection: Upgrade\r\n"
        "Sec-WebSocket-Accept: " + accept + "\r\n\r\n"
    ).encode("ascii")


_WELCOME = {
    "metadata": {"message_type": "session_welcome"},
    "payload": {"session": {"id": "session1", "keepalive_timeout_seconds": 10}},
}


class FakeSocket:
    """Records sent bytes, replays queued recv() results. A queued item that is an Exception
    instance is raised instead of returned. The handshake response bytes must be queued as the
    *first* recv() chunk(s) by the test, since the client reads the raw HTTP response itself
    (there's no separate "handshake socket")."""

    def __init__(self, recv_queue=None):
        self._recv_queue = list(recv_queue or [])
        self.sent = []
        self.closed = False

    def sendall(self, data):
        self.sent.append(data)

    def recv(self, bufsize):
        if not self._recv_queue:
            return b""
        item = self._recv_queue.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    def close(self):
        self.closed = True


def _client_kwargs(**overrides):
    kwargs = dict(
        channel_login="somechannel",
        access_token="tok",
        client_id="cid",
        broadcaster_user_id="1",
        user_id="2",
        sleep_fn=lambda s: None,
        # Default to a no-op so tests that don't care about subscription behavior stay hermetic -
        # without this, ChatClient falls back to the real api.create_eventsub_subscription and
        # makes a live HTTPS call to Twitch on every test that doesn't override it explicitly.
        create_subscription_fn=lambda *args, **kwargs: None,
    )
    kwargs.update(overrides)
    return kwargs


def test_connect_performs_handshake_then_subscribes_before_connected_status():
    # The client generates its own Sec-WebSocket-Key, so the fake handshake response must accept
    # whatever key it sends - capture it via a factory closure instead of hardcoding one.
    responses = []

    def socket_factory():
        fake = FakeSocket()

        def sendall(data):
            fake.sent.append(data)
            if data.startswith(b"GET "):
                text = data.decode("ascii")
                key_line = [l for l in text.split("\r\n") if l.startswith("Sec-WebSocket-Key:")][0]
                key = key_line.split(":", 1)[1].strip()
                fake._recv_queue.insert(0, _server_text_frame(_WELCOME))
                fake._recv_queue.insert(0, _handshake_response_bytes(key))

        fake.sendall = sendall
        responses.append(fake)
        return fake

    subscribe_calls = []

    def create_subscription_fn(access_token, client_id, session_id, sub_type, condition):
        subscribe_calls.append((access_token, client_id, session_id, sub_type, condition))

    client = ChatClient(
        **_client_kwargs(
            socket_factory=socket_factory, create_subscription_fn=create_subscription_fn
        )
    )
    client.connect()

    events = []
    for event in client.read_messages():
        events.append(event)
        break  # first event must be "connected", proving subscribe happened before it
    client.disconnect()

    assert events[0] == {"type": "status", "state": "connected"}
    assert len(subscribe_calls) == 2
    types = {call[3] for call in subscribe_calls}
    assert types == {"channel.chat.message", "channel.raid"}
    chat_call = next(c for c in subscribe_calls if c[3] == "channel.chat.message")
    assert chat_call[4] == {"broadcaster_user_id": "1", "user_id": "2"}
    raid_call = next(c for c in subscribe_calls if c[3] == "channel.raid")
    assert raid_call[4] == {"to_broadcaster_user_id": "1"}


def _connected_fake_socket(extra_frames=b""):
    """Builds a FakeSocket pre-loaded to complete a handshake with whatever key the client sends,
    then serve extra_frames (raw bytes) after the welcome frame."""
    fake = FakeSocket()

    def sendall(data):
        fake.sent.append(data)
        if data.startswith(b"GET "):
            text = data.decode("ascii")
            key_line = [l for l in text.split("\r\n") if l.startswith("Sec-WebSocket-Key:")][0]
            key = key_line.split(":", 1)[1].strip()
            if extra_frames:
                fake._recv_queue.insert(0, extra_frames)
            fake._recv_queue.insert(0, _server_text_frame(_WELCOME))
            fake._recv_queue.insert(0, _handshake_response_bytes(key))

    fake.sendall = sendall
    return fake


def test_chat_message_notification_yields_message_event():
    notification = {
        "metadata": {
            "message_type": "notification",
            "subscription_type": "channel.chat.message",
            "message_timestamp": "2026-08-18T00:00:00Z",
        },
        "payload": {
            "event": {
                "chatter_user_login": "bob",
                "chatter_user_name": "Bob",
                "message": {"text": "hello"},
            }
        },
    }
    fake = _connected_fake_socket(_server_text_frame(notification))
    client = ChatClient(**_client_kwargs(socket_factory=lambda: fake))
    client.connect()

    events = []
    for event in client.read_messages():
        events.append(event)
        if event["type"] == "message":
            break
    client.disconnect()

    assert events[-1] == {
        "type": "message",
        "username": "bob",
        "display_name": "Bob",
        "text": "hello",
        "timestamp": 1787011200000,
        "emotes": [],
    }


def test_chat_message_notification_extracts_emotes_from_fragments():
    notification = {
        "metadata": {
            "message_type": "notification",
            "subscription_type": "channel.chat.message",
            "message_timestamp": "2026-08-18T00:00:00Z",
        },
        "payload": {
            "event": {
                "chatter_user_login": "bob",
                "chatter_user_name": "Bob",
                "message": {
                    "text": "hello Kappa",
                    "fragments": [
                        {"type": "text", "text": "hello "},
                        {"type": "emote", "text": "Kappa", "emote": {"id": "25"}},
                    ],
                },
            }
        },
    }
    fake = _connected_fake_socket(_server_text_frame(notification))
    client = ChatClient(**_client_kwargs(socket_factory=lambda: fake))
    client.connect()

    events = []
    for event in client.read_messages():
        events.append(event)
        if event["type"] == "message":
            break
    client.disconnect()

    assert events[-1]["emotes"] == [
        {"id": "25", "text": "Kappa", "url": "https://static-cdn.jtvnw.net/emoticons/v2/25/static/dark/1.0"}
    ]


def test_raid_notification_yields_raid_event():
    notification = {
        "metadata": {
            "message_type": "notification",
            "subscription_type": "channel.raid",
            "message_timestamp": "2026-08-18T00:00:00Z",
        },
        "payload": {
            "event": {
                "from_broadcaster_user_login": "coolraider",
                "from_broadcaster_user_name": "CoolRaider",
                "viewers": 42,
            }
        },
    }
    fake = _connected_fake_socket(_server_text_frame(notification))
    client = ChatClient(**_client_kwargs(socket_factory=lambda: fake))
    client.connect()

    events = []
    for event in client.read_messages():
        events.append(event)
        if event["type"] == "raid":
            break
    client.disconnect()

    assert events[-1] == {
        "type": "raid",
        "from_channel": "coolraider",
        "display_name": "CoolRaider",
        "viewer_count": 42,
        "timestamp": 1787011200000,
    }


def test_ping_frame_is_answered_with_masked_pong_and_not_queued():
    chat_notification = {
        "metadata": {
            "message_type": "notification",
            "subscription_type": "channel.chat.message",
            "message_timestamp": "2026-08-18T00:00:00Z",
        },
        "payload": {
            "event": {
                "chatter_user_login": "a",
                "chatter_user_name": "A",
                "message": {"text": "after ping"},
            }
        },
    }
    ping_frame = bytes([0x89, 0])  # opcode 0x9, empty payload
    fake = _connected_fake_socket(ping_frame + _server_text_frame(chat_notification))
    client = ChatClient(**_client_kwargs(socket_factory=lambda: fake))
    client.connect()

    events = []
    for event in client.read_messages():
        events.append(event)
        if event["type"] == "message":
            break
    client.disconnect()

    assert [e["type"] for e in events] == ["status", "message"]
    pong_sent = [d for d in fake.sent if len(d) >= 1 and (d[0] & 0x0F) == 0xA]
    assert len(pong_sent) == 1


def test_subscription_failure_triggers_disconnected_status_and_retry():
    good_fake = _connected_fake_socket()
    call_count = [0]

    def create_subscription_fn(*args, **kwargs):
        call_count[0] += 1
        if call_count[0] == 1:
            raise RuntimeError("subscribe failed")

    sockets = iter([_connected_fake_socket(), good_fake])
    sleeps = []
    client = ChatClient(
        **_client_kwargs(
            socket_factory=lambda: next(sockets),
            create_subscription_fn=create_subscription_fn,
            sleep_fn=lambda s: sleeps.append(s),
        )
    )
    client.connect()

    events = []
    for event in client.read_messages():
        events.append(event)
        if event["type"] == "status" and event["state"] == "connected" and len(events) > 1:
            break
    client.disconnect()

    states = [e["state"] for e in events if e["type"] == "status"]
    assert states == ["disconnected", "connected"]
    assert sleeps == [1]


def test_session_reconnect_message_triggers_reconnect_cycle():
    # A session_reconnect message (Twitch asking the client to open a fresh connection and
    # re-subscribe) must trigger a reconnect cycle - not be swallowed as an unrecognized message
    # and not propagate as an exception out to the consumer.
    reconnect_message = {
        "metadata": {"message_type": "session_reconnect"},
        "payload": {
            "session": {"id": "session1", "reconnect_url": "wss://eventsub.wss.twitch.tv/ws"}
        },
    }
    first_fake = _connected_fake_socket(_server_text_frame(reconnect_message))
    second_fake = _connected_fake_socket()
    sockets = iter([first_fake, second_fake])

    client = ChatClient(
        **_client_kwargs(socket_factory=lambda: next(sockets))
    )
    client.connect()

    events = []
    for event in client.read_messages():
        events.append(event)
        if event["type"] == "status" and event["state"] == "connected" and len(events) > 1:
            break
    client.disconnect()

    states = [e["state"] for e in events if e["type"] == "status"]
    assert states == ["connected", "disconnected", "connected"]


def test_stalled_connection_triggers_reconnect_after_double_keepalive_timeout():
    # No frames arrive after the welcome (a real socket.recv() times out repeatedly). The stall
    # threshold is 2 * keepalive_timeout_seconds from _WELCOME (10s), i.e. 20. Drive it with an
    # injectable time_fn instead of real sleeping: three calls happen before the stall fires -
    # one to set _last_message_at at the end of the handshake, then two inside _recv_more's
    # timeout handler (an under-threshold check that returns b"" and loops, then an
    # over-threshold check that raises).
    def _socket_that_always_times_out(fake):
        def recv_with_timeout(bufsize):
            data = fake_recv(bufsize)
            if data == b"":
                raise socket.timeout()
            return data

        fake_recv = fake.recv
        fake.recv = recv_with_timeout
        return fake

    first_fake = _socket_that_always_times_out(_connected_fake_socket())
    second_fake = _connected_fake_socket()
    sockets = iter([first_fake, second_fake])

    times = iter([0, 5, 25])

    def time_fn():
        try:
            return next(times)
        except StopIteration:
            return 1000

    client = ChatClient(
        **_client_kwargs(socket_factory=lambda: next(sockets), time_fn=time_fn)
    )
    client.connect()

    events = []
    for event in client.read_messages():
        events.append(event)
        if event["type"] == "status" and event["state"] == "connected" and len(events) > 1:
            break
    client.disconnect()

    states = [e["state"] for e in events if e["type"] == "status"]
    assert states == ["connected", "disconnected", "connected"]


def test_disconnect_is_safe_to_call_twice():
    fake = _connected_fake_socket()
    client = ChatClient(**_client_kwargs(socket_factory=lambda: fake))
    client.connect()
    client.disconnect()
    client.disconnect()  # must not raise


def test_connect_raises_value_error_when_required_credentials_missing():
    client = ChatClient(channel_login="somechannel")  # no access_token/client_id/broadcaster_user_id/user_id
    try:
        client.connect()
        assert False, "expected ValueError"
    except ValueError:
        pass

