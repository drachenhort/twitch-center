# EventSub Chat Engine (Selectable) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a second chat transport (`lib/twitch/eventsub.py`, backed by Twitch's EventSub
WebSocket) selectable via a new `chat_engine` setting (`"irc"` default, `"eventsub"`), without
touching the existing IRC engine or `chat_overlay.py`'s rendering logic.

**Architecture:** `eventsub.ChatClient` hand-rolls a minimal RFC 6455 WebSocket client (opening
handshake + frame codec) over the same TLS-socket-plus-background-thread-plus-`queue.Queue` shape
`irc.ChatClient` already uses, and normalizes EventSub's `channel.chat.message`/`channel.raid`
notifications into the exact same event dicts IRC produces. `player.play_stream` resolves the
numeric IDs EventSub needs, then picks which `ChatClient` subclass to hand `chat_overlay.py` based
on `Settings.chat_engine` - `ChatOverlay` itself stays engine-agnostic.

**Tech Stack:** Python 3 (Kodi `xbmc.python` 3.0.0), `requests` (already a dependency), stdlib
`socket`/`ssl`/`threading`/`queue`/`json`/`struct`/`hashlib`/`base64` only - no new third-party
dependency.

**Spec:** `docs/superpowers/specs/2026-08-18-eventsub-chat-migration-design.md`

## Global Constraints

- `lib/twitch/*` files must never import `xbmc*` modules (enforced by
  `tests/test_architecture.py::test_lib_twitch_has_no_xbmc_imports`) - `eventsub.py` and the
  `api.py`/`auth.py` additions stay pure Python.
- No new addon dependency in `addon.xml` - no `websocket-client`/`websockets` package; WebSocket
  handshake and framing are hand-rolled, matching `irc.py`'s existing precedent for the IRC
  protocol.
- `lib/twitch/irc.py` and its existing tests are **not modified in behavior** - only its
  `ChatClient.__init__` signature gains unused, defaulted keyword params (see Task 6) so
  `chat_overlay.py` can construct either engine identically.
- Every new/changed public function needs a docstring in this codebase's existing style (see
  `irc.py`, `api.py` for tone/format) - copy that convention.
- Bump `addon.xml`'s `<addon version="...">` and prepend a `<news>` entry, and add a
  `CHANGELOG.md` `[Unreleased]`/new-version section, once the feature is functionally complete
  (Task 10) - per this repo's standing changelog-per-feature convention.

---

### Task 1: `api.py` - `get_user_by_login` and `create_eventsub_subscription`

**Files:**
- Modify: `lib/twitch/api.py`
- Test: `tests/twitch/test_api.py`

**Interfaces:**
- Produces: `api.get_user_by_login(access_token, client_id, login) -> dict | None`
- Produces: `api.create_eventsub_subscription(access_token, client_id, session_id, sub_type, condition, version="1") -> dict`

- [ ] **Step 1: Write the failing tests**

Add to `tests/twitch/test_api.py` (check the existing file first for its mocking style - it's
`requests`-mock based per the other functions in that module; match the pattern used for e.g.
`get_current_user`'s tests):

```python
import pytest
import requests

from lib.twitch import api


def test_get_user_by_login_returns_user_dict(requests_mock):
    requests_mock.get(
        "https://api.twitch.tv/helix/users",
        json={"data": [{"id": "123", "login": "somechannel", "display_name": "SomeChannel"}]},
    )
    result = api.get_user_by_login("token", "client123", "somechannel")
    assert result == {"id": "123", "login": "somechannel", "display_name": "SomeChannel"}


def test_get_user_by_login_returns_none_when_not_found(requests_mock):
    requests_mock.get("https://api.twitch.tv/helix/users", json={"data": []})
    result = api.get_user_by_login("token", "client123", "nosuchchannel")
    assert result is None


def test_create_eventsub_subscription_posts_expected_body(requests_mock):
    m = requests_mock.post(
        "https://api.twitch.tv/helix/eventsub/subscriptions",
        json={"data": [{"id": "sub1"}]},
        status_code=202,
    )
    api.create_eventsub_subscription(
        "token", "client123", "session1", "channel.chat.message",
        {"broadcaster_user_id": "1", "user_id": "2"},
    )
    body = m.last_request.json()
    assert body["type"] == "channel.chat.message"
    assert body["version"] == "1"
    assert body["condition"] == {"broadcaster_user_id": "1", "user_id": "2"}
    assert body["transport"] == {"method": "websocket", "session_id": "session1"}


def test_create_eventsub_subscription_raises_on_failure(requests_mock):
    requests_mock.post(
        "https://api.twitch.tv/helix/eventsub/subscriptions", status_code=400, json={}
    )
    with pytest.raises(requests.HTTPError):
        api.create_eventsub_subscription(
            "token", "client123", "session1", "channel.chat.message",
            {"broadcaster_user_id": "1", "user_id": "2"},
        )
```

If `tests/twitch/test_api.py` doesn't already use `requests_mock` (check for the fixture/library
in use first - it may instead use `unittest.mock.patch("lib.twitch.api.requests.get", ...)` style
like other files in this repo), rewrite these four tests to match whatever mocking convention the
existing tests in that file use instead. Don't introduce a second mocking style into the same file.

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/twitch/test_api.py -k "get_user_by_login or create_eventsub_subscription" -v`
Expected: FAIL with `AttributeError: module 'lib.twitch.api' has no attribute 'get_user_by_login'`

- [ ] **Step 3: Implement**

Add to `lib/twitch/api.py`:

```python
def get_user_by_login(access_token, client_id, login):
    """Return {"id", "login", "display_name"} for the given login name, or None if no such user -
    Twitch returns an empty data list rather than a 404 for an unknown login."""
    body = _get(HELIX_BASE + "/users", access_token, client_id, params={"login": login})
    users = body["data"]
    if not users:
        return None
    user = users[0]
    return {"id": user["id"], "login": user["login"], "display_name": user["display_name"]}


def create_eventsub_subscription(access_token, client_id, session_id, sub_type, condition, version="1"):
    """POST /helix/eventsub/subscriptions with transport {method: websocket, session_id}. Raises
    requests.HTTPError on failure - unlike this module's other best-effort-on-decoration functions,
    a failed chat subscription isn't decoration, so the caller (eventsub.ChatClient._run) needs to
    see the failure and go through its own backoff-retry path rather than getting an empty/None
    result it can't distinguish from "no subscription needed"."""
    response = requests.post(
        HELIX_BASE + "/eventsub/subscriptions",
        headers=_headers(access_token, client_id),
        json={
            "type": sub_type,
            "version": version,
            "condition": condition,
            "transport": {"method": "websocket", "session_id": session_id},
        },
        timeout=10,
    )
    response.raise_for_status()
    return response.json()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/twitch/test_api.py -k "get_user_by_login or create_eventsub_subscription" -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add lib/twitch/api.py tests/twitch/test_api.py
git commit -m "feat: add get_user_by_login and create_eventsub_subscription to Helix API client"
```

---

### Task 2: `auth.py` - add `user:read:chat` scope

**Files:**
- Modify: `lib/twitch/auth.py:10`
- Test: `tests/twitch/test_auth.py`

**Interfaces:**
- Produces: `auth.SCOPES == ["user:read:follows", "user:read:chat"]`

- [ ] **Step 1: Write the failing test**

Check `tests/twitch/test_auth.py` for whether `SCOPES` is asserted anywhere already (grep first:
`grep -n SCOPES tests/twitch/test_auth.py`). If it is, update that assertion. If not, add:

```python
from lib.twitch import auth


def test_scopes_include_chat_read():
    assert "user:read:chat" in auth.SCOPES
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/twitch/test_auth.py -k scopes_include_chat_read -v`
Expected: FAIL (`user:read:chat` not in `["user:read:follows"]`)

- [ ] **Step 3: Implement**

In `lib/twitch/auth.py:10`:

```python
SCOPES = ["user:read:follows", "user:read:chat"]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/twitch/test_auth.py -k scopes_include_chat_read -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add lib/twitch/auth.py tests/twitch/test_auth.py
git commit -m "feat: request user:read:chat scope at login for future EventSub chat use"
```

---

### Task 3: `eventsub.py` - WebSocket handshake and frame codec primitives

**Files:**
- Create: `lib/twitch/eventsub.py`
- Test: `tests/twitch/test_eventsub.py`

**Interfaces:**
- Produces: `_build_handshake_key() -> str`
- Produces: `_build_handshake_request(host, path, key) -> bytes`
- Produces: `_expected_accept(key) -> str`
- Produces: `_parse_handshake_response(raw_text, key) -> None` (raises `ConnectionError` on failure)
- Produces: `_encode_client_frame(payload, opcode=_OPCODE_TEXT) -> bytes`
- Produces: `_decode_frame(buffer) -> (dict | None, bytes)`
- Produces: `_parse_rfc3339_ms(ts_str) -> int`
- Produces: opcode constants `_OPCODE_CONTINUATION`, `_OPCODE_TEXT`, `_OPCODE_CLOSE`,
  `_OPCODE_PING`, `_OPCODE_PONG`

- [ ] **Step 1: Write the failing tests**

Create `tests/twitch/test_eventsub.py`:

```python
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
    assert ms == 1786060800000


def test_parse_rfc3339_ms_handles_fractional_seconds():
    ms = _parse_rfc3339_ms("2026-08-18T00:00:00.123456789Z")
    assert ms == 1786060800123


def test_parse_rfc3339_ms_falls_back_to_now_on_malformed_input():
    import time
    before = int(time.time() * 1000)
    ms = _parse_rfc3339_ms("not-a-timestamp")
    after = int(time.time() * 1000)
    assert before <= ms <= after
```

Verify `1786060800000` is in fact the correct epoch-ms for `2026-08-18T00:00:00Z` before pasting
this into the test (compute it, don't guess) - e.g. `python3 -c "import datetime;
print(int(datetime.datetime(2026,8,18,tzinfo=datetime.timezone.utc).timestamp()*1000))"`.

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/twitch/test_eventsub.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'lib.twitch.eventsub'`

- [ ] **Step 3: Implement**

Create `lib/twitch/eventsub.py`:

```python
"""EventSub WebSocket chat client for eventsub.wss.twitch.tv. No xbmc* imports - pure Python,
pytest-testable. Alternative chat engine to lib/twitch/irc.py - see
docs/superpowers/specs/2026-08-18-eventsub-chat-migration-design.md for why both exist."""
import base64
import datetime
import hashlib
import json
import os
import re
import socket as socket_module
import ssl
import struct
import threading
import time
from queue import Empty, Full, Queue

from lib.twitch import api

EVENTSUB_HOST = "eventsub.wss.twitch.tv"
EVENTSUB_PORT = 443
EVENTSUB_PATH = "/ws"

_WS_MAGIC = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"

_OPCODE_CONTINUATION = 0x0
_OPCODE_TEXT = 0x1
_OPCODE_CLOSE = 0x8
_OPCODE_PING = 0x9
_OPCODE_PONG = 0xA

_RFC3339_RE = re.compile(
    r"^(?P<date>\d{4}-\d{2}-\d{2})T(?P<time>\d{2}:\d{2}:\d{2})(\.(?P<frac>\d+))?Z$"
)


def _build_handshake_key():
    return base64.b64encode(os.urandom(16)).decode("ascii")


def _build_handshake_request(host, path, key):
    lines = [
        "GET %s HTTP/1.1" % path,
        "Host: %s" % host,
        "Upgrade: websocket",
        "Connection: Upgrade",
        "Sec-WebSocket-Key: %s" % key,
        "Sec-WebSocket-Version: 13",
        "",
        "",
    ]
    return "\r\n".join(lines).encode("ascii")


def _expected_accept(key):
    digest = hashlib.sha1((key + _WS_MAGIC).encode("ascii")).digest()
    return base64.b64encode(digest).decode("ascii")


def _parse_handshake_response(raw_text, key):
    """Raises ConnectionError with a diagnostic message if the response isn't a valid 101
    Switching Protocols upgrade with the expected Sec-WebSocket-Accept value."""
    lines = raw_text.split("\r\n")
    status_line = lines[0] if lines else ""
    if " 101 " not in (" " + status_line + " "):
        raise ConnectionError("EventSub handshake failed: unexpected status line %r" % status_line)
    headers = {}
    for line in lines[1:]:
        if not line or ":" not in line:
            continue
        name, _, value = line.partition(":")
        headers[name.strip().lower()] = value.strip()
    accept = headers.get("sec-websocket-accept")
    if accept != _expected_accept(key):
        raise ConnectionError("EventSub handshake failed: Sec-WebSocket-Accept mismatch")


def _encode_client_frame(payload, opcode=_OPCODE_TEXT):
    """Client->server frames MUST be masked per RFC 6455 5.1. This client only ever sends small
    payloads (pong replies), so no send-side fragmentation is implemented."""
    if isinstance(payload, str):
        payload = payload.encode("utf-8")
    header = bytes([0x80 | opcode])
    length = len(payload)
    if length <= 125:
        header += bytes([0x80 | length])
    elif length <= 0xFFFF:
        header += bytes([0x80 | 126]) + struct.pack(">H", length)
    else:
        header += bytes([0x80 | 127]) + struct.pack(">Q", length)
    mask_key = os.urandom(4)
    masked = bytes(b ^ mask_key[i % 4] for i, b in enumerate(payload))
    return header + mask_key + masked


def _decode_frame(buffer):
    """Attempts to decode one server->client (unmasked) WS frame from the front of buffer.
    Returns (frame_dict, remaining_buffer) on success, or (None, buffer) unchanged if buffer
    doesn't yet hold a complete frame - caller should read more bytes and retry, mirroring
    irc.py's \\r\\n-line buffering."""
    if len(buffer) < 2:
        return None, buffer
    first, second = buffer[0], buffer[1]
    fin = bool(first & 0x80)
    opcode = first & 0x0F
    length = second & 0x7F
    offset = 2
    if length == 126:
        if len(buffer) < offset + 2:
            return None, buffer
        length = struct.unpack(">H", buffer[offset:offset + 2])[0]
        offset += 2
    elif length == 127:
        if len(buffer) < offset + 8:
            return None, buffer
        length = struct.unpack(">Q", buffer[offset:offset + 8])[0]
        offset += 8
    if len(buffer) < offset + length:
        return None, buffer
    payload = buffer[offset:offset + length]
    remaining = buffer[offset + length:]
    return {"fin": fin, "opcode": opcode, "payload": payload}, remaining


def _parse_rfc3339_ms(ts_str):
    """Parses a Twitch EventSub RFC3339 timestamp (nanosecond-precision fractional seconds
    allowed) into an int ms epoch. Falls back to time.time()*1000 on anything unparseable,
    matching irc.py's tmi-sent-ts fallback behavior."""
    match = _RFC3339_RE.match(ts_str) if isinstance(ts_str, str) else None
    if not match:
        return int(time.time() * 1000)
    frac = match.group("frac") or "0"
    micros = int((frac + "000000")[:6])
    dt = datetime.datetime.strptime(
        match.group("date") + "T" + match.group("time"), "%Y-%m-%dT%H:%M:%S"
    ).replace(tzinfo=datetime.timezone.utc, microsecond=micros)
    return int(dt.timestamp() * 1000)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/twitch/test_eventsub.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add lib/twitch/eventsub.py tests/twitch/test_eventsub.py
git commit -m "feat: add WebSocket handshake and frame codec primitives for EventSub chat"
```

---

### Task 4: `eventsub.py` - `ChatClient` connect/handshake/subscribe/backoff loop

**Files:**
- Modify: `lib/twitch/eventsub.py`
- Test: `tests/twitch/test_eventsub.py`

**Interfaces:**
- Consumes: everything from Task 3 (`_build_handshake_key`, `_build_handshake_request`,
  `_parse_handshake_response`, `_encode_client_frame`, `_decode_frame`, `_parse_rfc3339_ms`,
  opcode constants), `api.create_eventsub_subscription` from Task 1.
- Produces: `class ChatClient` with `__init__(self, channel_login, access_token=None,
  client_id=None, broadcaster_user_id=None, user_id=None, socket_factory=None, sleep_fn=None,
  create_subscription_fn=None, time_fn=None)`, `.connect()`, `.read_messages()`, `.disconnect()` -
  this is the class Task 6/7 wire up as an alternative to `irc.ChatClient`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/twitch/test_eventsub.py`. This needs a fake socket that can serve a WS handshake
response followed by WS frames - build a small helper that encodes a JSON payload as a server
(unmasked) text frame, since tests need to construct realistic `recv()` byte chunks:

```python
import threading

from lib.twitch.eventsub import ChatClient, _expected_accept


def _server_text_frame(payload_dict):
    payload = json.dumps(payload_dict).encode("utf-8")
    header = bytes([0x81, len(payload)])  # small payloads only, fits in tests
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
        "timestamp": 1786060800000,
    }


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
        "timestamp": 1786060800000,
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
```

Note: `test_subscription_failure_triggers_disconnected_status_and_retry`'s stopping condition is
deliberately loose (`len(events) > 1`) - tighten it once the implementation exists and you can see
the actual event sequence in a debugger/print, rather than guessing exact indices blind.

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/twitch/test_eventsub.py -v`
Expected: FAIL - `ChatClient` doesn't exist yet.

- [ ] **Step 3: Implement**

Append to `lib/twitch/eventsub.py`:

```python
_QUEUE_POLL_TIMEOUT = 0.5
_BACKOFF_START = 1
_BACKOFF_MAX = 30
_BACKOFF_RESET_AFTER = 30
_QUEUE_MAXSIZE = 1000
_DISCONNECT_GRACE = 0.05
_SOCKET_RECV_TIMEOUT = 5
_REQUESTED_KEEPALIVE_SECONDS = 10


def _default_socket_factory():
    raw = socket_module.create_connection((EVENTSUB_HOST, EVENTSUB_PORT), timeout=10)
    context = ssl.create_default_context()
    wrapped = context.wrap_socket(raw, server_hostname=EVENTSUB_HOST)
    wrapped.settimeout(_SOCKET_RECV_TIMEOUT)
    return wrapped


class ChatClient:
    def __init__(self, channel_login, access_token=None, client_id=None, broadcaster_user_id=None,
                 user_id=None, socket_factory=None, sleep_fn=None, create_subscription_fn=None,
                 time_fn=None):
        self.channel_login = channel_login
        self._access_token = access_token
        self._client_id = client_id
        self._broadcaster_user_id = broadcaster_user_id
        self._user_id = user_id
        self._socket_factory = socket_factory or _default_socket_factory
        self._sleep_fn = sleep_fn or time.sleep
        self._create_subscription_fn = create_subscription_fn or api.create_eventsub_subscription
        self._time_fn = time_fn or time.time
        self._queue = Queue(maxsize=_QUEUE_MAXSIZE)
        self._cancel_event = threading.Event()
        self._thread = None
        self._sock = None
        self._recv_buffer = b""
        self._keepalive_timeout = _REQUESTED_KEEPALIVE_SECONDS
        self._last_message_at = 0

    def connect(self):
        """Spawns the background thread and returns immediately. Raises ValueError synchronously
        (before spawning anything) if required credentials are missing - a programmer error in the
        caller, not a runtime condition worth a reconnect loop."""
        if any(v is None for v in (self._access_token, self._client_id, self._broadcaster_user_id, self._user_id)):
            raise ValueError(
                "eventsub.ChatClient requires access_token, client_id, broadcaster_user_id, and "
                "user_id"
            )
        if self._thread is not None and self._thread.is_alive():
            return
        self._cancel_event.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def read_messages(self):
        while not (self._cancel_event.is_set() and self._queue.empty()):
            try:
                yield self._queue.get(timeout=_QUEUE_POLL_TIMEOUT)
            except Empty:
                continue

    def _enqueue(self, event):
        try:
            self._queue.put_nowait(event)
        except Full:
            try:
                self._queue.get_nowait()
            except Empty:
                pass
            self._queue.put_nowait(event)

    def disconnect(self):
        self._cancel_event.set()
        sock = self._sock
        if sock is not None:
            try:
                sock.close()
            except OSError:
                pass
        if self._thread is not None:
            self._thread.join(timeout=5)

    def _run(self):
        backoff = _BACKOFF_START
        while not self._cancel_event.is_set():
            connected_at = None
            self._recv_buffer = b""
            try:
                self._sock = self._socket_factory()
                self._handshake_and_subscribe()
                connected_at = time.time()
                self._enqueue({"type": "status", "state": "connected"})
                self._read_loop()
            except Exception:
                pass
            finally:
                if self._sock is not None:
                    try:
                        self._sock.close()
                    except OSError:
                        pass
                    self._sock = None

            if self._cancel_event.wait(_DISCONNECT_GRACE):
                break

            self._enqueue({"type": "status", "state": "disconnected"})
            if connected_at is not None and (time.time() - connected_at) > _BACKOFF_RESET_AFTER:
                backoff = _BACKOFF_START
            self._sleep_fn(backoff)
            backoff = min(backoff * 2, _BACKOFF_MAX)

    def _handshake_and_subscribe(self):
        key = _build_handshake_key()
        self._sock.sendall(_build_handshake_request(EVENTSUB_HOST, EVENTSUB_PATH, key))
        raw_response = self._read_handshake_response()
        _parse_handshake_response(raw_response, key)

        while True:
            frame = self._read_one_frame_blocking()
            payload = json.loads(frame["payload"].decode("utf-8"))
            if payload["metadata"]["message_type"] == "session_welcome":
                session = payload["payload"]["session"]
                session_id = session["id"]
                self._keepalive_timeout = session.get(
                    "keepalive_timeout_seconds", _REQUESTED_KEEPALIVE_SECONDS
                )
                break

        self._create_subscription_fn(
            self._access_token, self._client_id, session_id, "channel.chat.message",
            {"broadcaster_user_id": self._broadcaster_user_id, "user_id": self._user_id},
        )
        self._create_subscription_fn(
            self._access_token, self._client_id, session_id, "channel.raid",
            {"to_broadcaster_user_id": self._broadcaster_user_id},
        )
        self._last_message_at = self._time_fn()

    def _read_handshake_response(self):
        buffer = b""
        while b"\r\n\r\n" not in buffer:
            chunk = self._sock.recv(4096)
            if not chunk:
                raise ConnectionError("connection closed during handshake")
            buffer += chunk
        header_end = buffer.index(b"\r\n\r\n") + 4
        self._recv_buffer = buffer[header_end:]
        return buffer[:header_end].decode("iso-8859-1")

    def _recv_more(self):
        try:
            data = self._sock.recv(4096)
        except socket_module.timeout:
            if self._time_fn() - self._last_message_at > 2 * self._keepalive_timeout:
                raise ConnectionError("EventSub connection stalled: no messages received")
            return b""
        if not data:
            raise ConnectionError("connection closed by server")
        return data

    def _read_one_frame_blocking(self):
        while True:
            frame, self._recv_buffer = _decode_frame(self._recv_buffer)
            if frame is not None:
                return frame
            self._recv_buffer += self._recv_more()

    def _read_loop(self):
        while not self._cancel_event.is_set():
            frame = self._read_one_frame_blocking()
            self._last_message_at = self._time_fn()
            if frame["opcode"] == _OPCODE_PING:
                self._sock.sendall(_encode_client_frame(frame["payload"], opcode=_OPCODE_PONG))
                continue
            if frame["opcode"] == _OPCODE_CLOSE:
                raise ConnectionError("EventSub server closed the connection")
            if frame["opcode"] != _OPCODE_TEXT:
                continue
            payload = json.loads(frame["payload"].decode("utf-8"))
            self._handle_payload(payload)

    def _handle_payload(self, payload):
        message_type = payload["metadata"]["message_type"]
        if message_type == "session_keepalive":
            return
        if message_type == "session_reconnect":
            raise ConnectionError("EventSub requested reconnect")
        if message_type != "notification":
            self._enqueue({"type": "raw", "line": json.dumps(payload)})
            return

        subscription_type = payload["metadata"]["subscription_type"]
        event = payload["payload"]["event"]
        timestamp = _parse_rfc3339_ms(payload["metadata"]["message_timestamp"])

        if subscription_type == "channel.chat.message":
            self._enqueue({
                "type": "message",
                "username": event["chatter_user_login"],
                "display_name": event["chatter_user_name"],
                "text": event["message"]["text"],
                "timestamp": timestamp,
            })
        elif subscription_type == "channel.raid":
            self._enqueue({
                "type": "raid",
                "from_channel": event["from_broadcaster_user_login"],
                "display_name": event["from_broadcaster_user_name"],
                "viewer_count": event["viewers"],
                "timestamp": timestamp,
            })
        else:
            self._enqueue({"type": "raw", "line": json.dumps(payload)})
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/twitch/test_eventsub.py -v`
Expected: PASS. If `test_subscription_failure_triggers_disconnected_status_and_retry` or
`test_ping_frame_is_answered_with_masked_pong_and_not_queued` fail on exact event-sequence
assertions, adjust the test's stopping condition/assertions to match the real (correct) event
order rather than changing production behavior to fit a guessed sequence - re-derive the expected
order from reading `_run`/`_read_loop` rather than trial-and-error.

- [ ] **Step 5: Commit**

```bash
git add lib/twitch/eventsub.py tests/twitch/test_eventsub.py
git commit -m "feat: implement eventsub.ChatClient (WebSocket handshake, subscribe, reconnect loop)"
```

---

### Task 5: `settings.py` + `settings.xml` + `strings.po` - `chat_engine` setting

**Files:**
- Modify: `lib/settings.py`
- Modify: `resources/settings.xml`
- Modify: `resources/language/resource.language.en_gb/strings.po`
- Test: `tests/test_settings.py`

**Interfaces:**
- Produces: `settings.VALID_CHAT_ENGINES = ("irc", "eventsub")`, `settings.DEFAULT_CHAT_ENGINE = "irc"`,
  `Settings.chat_engine` property.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_settings.py`:

```python
def test_chat_engine_defaults_to_irc():
    settings = Settings()
    assert settings.chat_engine == "irc"


def test_chat_engine_reads_addon_setting():
    addon = xbmcaddon.Addon()
    addon.setSetting("chat_engine", "eventsub")
    settings = Settings(addon=addon)
    assert settings.chat_engine == "eventsub"


def test_chat_engine_falls_back_to_default_on_invalid_value():
    addon = xbmcaddon.Addon()
    addon.setSetting("chat_engine", "not-a-real-engine")
    settings = Settings(addon=addon)
    assert settings.chat_engine == "irc"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_settings.py -k chat_engine -v`
Expected: FAIL with `AttributeError: 'Settings' object has no attribute 'chat_engine'`

- [ ] **Step 3: Implement**

In `lib/settings.py`, add alongside the existing `VALID_CHAT_DISPLAY_MODES`/`DEFAULT_CHAT_DISPLAY_MODE`:

```python
VALID_CHAT_ENGINES = ("irc", "eventsub")
DEFAULT_CHAT_ENGINE = "irc"
```

And in `class Settings`, alongside `chat_display_mode`:

```python
    @property
    def chat_engine(self):
        value = self._addon.getSetting("chat_engine")
        if value in VALID_CHAT_ENGINES:
            return value
        return DEFAULT_CHAT_ENGINE
```

In `resources/settings.xml`, add a new `<setting>` inside the existing `<group id="1">`, right
after `chat_display_mode`'s block:

```xml
        <setting id="chat_engine" type="string" label="30014">
          <level>0</level>
          <default>irc</default>
          <constraints>
            <options>
              <option label="30015">irc</option>
              <option label="30016">eventsub</option>
            </options>
          </constraints>
          <control type="list" format="string"/>
        </setting>
```

In `resources/language/resource.language.en_gb/strings.po`, append after the existing `#30013`
entry:

```
msgctxt "#30014"
msgid "Chat engine"
msgstr ""

msgctxt "#30015"
msgid "IRC (anonymous, no login required)"
msgstr ""

msgctxt "#30016"
msgid "EventSub (requires login, official API)"
msgstr ""
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_settings.py -k chat_engine -v`
Expected: PASS

Also run the full settings suite to confirm nothing else broke:
Run: `pytest tests/test_settings.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add lib/settings.py resources/settings.xml resources/language/resource.language.en_gb/strings.po tests/test_settings.py
git commit -m "feat: add chat_engine setting (irc default, eventsub) to switch chat transports"
```

---

### Task 6: `irc.py` - accept (and ignore) the shared constructor keyword args

**Files:**
- Modify: `lib/twitch/irc.py:118-127` (`ChatClient.__init__`)
- Test: `tests/twitch/test_irc.py`

**Interfaces:**
- Produces: `irc.ChatClient.__init__(self, channel, access_token=None, client_id=None,
  broadcaster_user_id=None, user_id=None, socket_factory=None, sleep_fn=None)` - existing
  positional-`channel`-only call sites keep working unchanged since the new params are all
  keyword-defaulted.

- [ ] **Step 1: Write the failing test**

Add to `tests/twitch/test_irc.py`:

```python
def test_constructor_accepts_and_ignores_eventsub_style_kwargs():
    fake = FakeSocket()
    # Must not raise TypeError - chat_overlay.py constructs whichever engine is configured with
    # the same full kwarg set, and irc.ChatClient must tolerate the ones it doesn't use.
    client = ChatClient(
        "somechannel",
        access_token="tok",
        client_id="cid",
        broadcaster_user_id="1",
        user_id="2",
        socket_factory=lambda: fake,
        sleep_fn=lambda s: None,
    )
    assert client.channel == "somechannel"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/twitch/test_irc.py -k eventsub_style_kwargs -v`
Expected: FAIL with `TypeError: __init__() got an unexpected keyword argument 'access_token'`

- [ ] **Step 3: Implement**

In `lib/twitch/irc.py`, change:

```python
    def __init__(self, channel, socket_factory=None, sleep_fn=None):
        self.channel = channel
        self._socket_factory = socket_factory or _default_socket_factory
        self._sleep_fn = sleep_fn or time.sleep
```

to:

```python
    def __init__(self, channel, access_token=None, client_id=None, broadcaster_user_id=None,
                 user_id=None, socket_factory=None, sleep_fn=None):
        """access_token/client_id/broadcaster_user_id/user_id are accepted but unused - IRC stays
        anonymous. They exist only so callers can construct either chat engine (see
        lib/twitch/eventsub.py's ChatClient) through one shared keyword surface without an
        if engine == "eventsub" branch at the call site."""
        self.channel = channel
        self._socket_factory = socket_factory or _default_socket_factory
        self._sleep_fn = sleep_fn or time.sleep
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/twitch/test_irc.py -v`
Expected: PASS (full file, to confirm no existing test broke)

- [ ] **Step 5: Commit**

```bash
git add lib/twitch/irc.py tests/twitch/test_irc.py
git commit -m "feat: accept eventsub-style constructor kwargs on irc.ChatClient (unused, ignored)"
```

---

### Task 7: `chat_overlay.py` - forward engine-selection args to `chat_client_cls`

**Files:**
- Modify: `lib/windows/chat_overlay.py:50-65`
- Test: `tests/windows/test_chat_overlay.py`

**Interfaces:**
- Consumes: the shared `ChatClient` constructor shape from Tasks 4 & 6.
- Produces: `ChatOverlay.__init__(self, *args, channel, access_token=None, client_id=None,
  broadcaster_user_id=None, user_id=None, chat_client_cls=None, time_fn=None, **kwargs)`.

- [ ] **Step 1: Write the failing test**

Update `FakeChatClient` in `tests/windows/test_chat_overlay.py` to accept (and record) the new
kwargs, and add a test asserting they're forwarded:

```python
class FakeChatClient:
    instances = []

    def __init__(self, channel, access_token=None, client_id=None, broadcaster_user_id=None,
                 user_id=None):
        self.channel = channel
        self.access_token = access_token
        self.client_id = client_id
        self.broadcaster_user_id = broadcaster_user_id
        self.user_id = user_id
        self.connected = False
        self.disconnected = False
        self._events = []
        FakeChatClient.instances.append(self)

    def connect(self):
        self.connected = True

    def read_messages(self):
        return iter(self._events)

    def disconnect(self):
        self.disconnected = True
```

(Every other `FakeChatClient` subclass in this file - `ClientWithMessages`, `ExplodingClient`,
etc. - calls `super().__init__(channel)` positionally, which stays valid since the new params are
keyword-defaulted; no other test in this file needs changes for this reason alone.)

```python
def test_oninit_forwards_engine_credentials_to_chat_client_cls():
    FakeChatClient.instances.clear()
    win = ChatOverlay(
        "script-twitch-center-chat-overlay.xml",
        "/tmp",
        "Default",
        "1080i",
        channel="somechannel",
        access_token="tok",
        client_id="cid",
        broadcaster_user_id="123",
        user_id="456",
        chat_client_cls=FakeChatClient,
    )
    win.onInit()
    win._thread.join(timeout=1)

    client = FakeChatClient.instances[0]
    assert client.access_token == "tok"
    assert client.client_id == "cid"
    assert client.broadcaster_user_id == "123"
    assert client.user_id == "456"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/windows/test_chat_overlay.py -k forwards_engine_credentials -v`
Expected: FAIL with `TypeError: __init__() got an unexpected keyword argument 'access_token'`
(raised by `ChatOverlay.__init__`, since it doesn't accept these kwargs yet)

- [ ] **Step 3: Implement**

In `lib/windows/chat_overlay.py`, change `ChatOverlay.__init__` and `onInit`:

```python
    def __init__(self, *args, channel, access_token=None, client_id=None,
                 broadcaster_user_id=None, user_id=None, chat_client_cls=None, time_fn=None,
                 **kwargs):
        super().__init__(*args, **kwargs)
        self.channel = channel
        self._access_token = access_token
        self._client_id = client_id
        self._broadcaster_user_id = broadcaster_user_id
        self._user_id = user_id
        self._chat_client_cls = chat_client_cls or ChatClient
        self._time_fn = time_fn or time.time
        self._client = None
        self._messages = []
        self._cancel_event = threading.Event()
        self._thread = None
        self._last_render_at = None

    def onInit(self):
        self._client = self._chat_client_cls(
            self.channel,
            access_token=self._access_token,
            client_id=self._client_id,
            broadcaster_user_id=self._broadcaster_user_id,
            user_id=self._user_id,
        )
        self._client.connect()
        self._thread = threading.Thread(target=self._pump_messages, daemon=True)
        self._thread.start()
```

The default `from lib.twitch.irc import ChatClient` import stays as the fallback class when
`chat_client_cls` isn't passed - `player.py` (Task 8) is what actually decides `irc` vs `eventsub`
in production; `ChatOverlay`'s own default is just "keep working exactly as before if nobody tells
it otherwise."

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/windows/test_chat_overlay.py -v`
Expected: PASS (full file - confirms the `FakeChatClient` signature change didn't break any
existing test)

- [ ] **Step 5: Commit**

```bash
git add lib/windows/chat_overlay.py tests/windows/test_chat_overlay.py
git commit -m "feat: forward chat engine credentials from ChatOverlay to chat_client_cls"
```

---

### Task 8: `player.py` - pick the chat engine and resolve EventSub's numeric IDs

**Files:**
- Modify: `lib/windows/player.py`
- Test: `tests/windows/test_player.py`

**Interfaces:**
- Consumes: `Settings.chat_engine` (Task 5), `api.get_user_by_login` (Task 1),
  `eventsub.ChatClient` (Task 4), `irc.ChatClient` (unchanged).
- Produces: `play_stream(url, channel, settings=None, access_token=None, client_id=None,
  chat_overlay_cls=None, chat_client_cls=None)` - `chat_client_cls`, when explicitly passed
  (as every existing test does), still overrides engine selection entirely, so existing tests for
  the `irc`-equivalent behavior keep passing unchanged.

- [ ] **Step 1: Write the failing tests**

Add to `tests/windows/test_player.py`:

```python
from lib.twitch import eventsub as eventsub_module
from lib.twitch import irc as irc_module


class FakeSettingsWithEngine(FakeSettings):
    def __init__(self, chat_display_mode, chat_engine="irc"):
        super().__init__(chat_display_mode)
        self.chat_engine = chat_engine


def test_play_stream_uses_irc_engine_by_default():
    FakeChatOverlay.instances.clear()
    with patch("lib.windows.player.Helper") as mock_helper_cls, patch(
        "lib.windows.player.xbmc.Player"
    ), patch("lib.windows.player.PlaybackWatchdog", FakeWatchdog):
        mock_helper_cls.return_value.check_inputstream.return_value = True
        mock_helper_cls.return_value.inputstream_addon = "inputstream.adaptive"

        player.play_stream(
            "https://example.invalid/stream.m3u8",
            "somechannel",
            settings=FakeSettingsWithEngine("overlay", chat_engine="irc"),
            chat_overlay_cls=FakeChatOverlay,
        )

    overlay = FakeChatOverlay.instances[0]
    assert overlay._client_cls_used is irc_module.ChatClient


def test_play_stream_uses_eventsub_engine_and_resolves_broadcaster_id():
    FakeChatOverlay.instances.clear()
    with patch("lib.windows.player.Helper") as mock_helper_cls, patch(
        "lib.windows.player.xbmc.Player"
    ), patch("lib.windows.player.PlaybackWatchdog", FakeWatchdog), patch(
        "lib.windows.player.api.get_user_by_login",
        return_value={"id": "999", "login": "somechannel", "display_name": "SomeChannel"},
    ) as mock_get_user:
        mock_helper_cls.return_value.check_inputstream.return_value = True
        mock_helper_cls.return_value.inputstream_addon = "inputstream.adaptive"

        player.play_stream(
            "https://example.invalid/stream.m3u8",
            "somechannel",
            settings=FakeSettingsWithEngine("overlay", chat_engine="eventsub"),
            access_token="tok",
            client_id="cid",
            user_id="42",
            chat_overlay_cls=FakeChatOverlay,
        )

    mock_get_user.assert_called_once_with("tok", "cid", "somechannel")
    overlay = FakeChatOverlay.instances[0]
    assert overlay._client_cls_used is eventsub_module.ChatClient
    assert overlay.broadcaster_user_id == "999"
    assert overlay.access_token == "tok"
    assert overlay.client_id == "cid"
    assert overlay.user_id == "42"


def test_play_stream_falls_back_to_irc_when_broadcaster_id_resolution_fails():
    FakeChatOverlay.instances.clear()
    with patch("lib.windows.player.Helper") as mock_helper_cls, patch(
        "lib.windows.player.xbmc.Player"
    ), patch("lib.windows.player.PlaybackWatchdog", FakeWatchdog), patch(
        "lib.windows.player.api.get_user_by_login", return_value=None
    ), patch("lib.windows.player.xbmc.log") as mock_log:
        mock_helper_cls.return_value.check_inputstream.return_value = True
        mock_helper_cls.return_value.inputstream_addon = "inputstream.adaptive"

        result = player.play_stream(
            "https://example.invalid/stream.m3u8",
            "somechannel",
            settings=FakeSettingsWithEngine("overlay", chat_engine="eventsub"),
            access_token="tok",
            client_id="cid",
            user_id="42",
            chat_overlay_cls=FakeChatOverlay,
        )

    assert result is True
    overlay = FakeChatOverlay.instances[0]
    assert overlay._client_cls_used is irc_module.ChatClient
    mock_log.assert_called_once()
```

These need `FakeChatOverlay` (in the same test file) updated to record which class it was handed,
since production `ChatOverlay` doesn't expose that but the test needs to assert on it:

```python
class FakeChatOverlay:
    instances = []

    def __init__(self, xml_filename, script_path, default_skin, default_res, channel=None,
                 access_token=None, client_id=None, broadcaster_user_id=None, user_id=None,
                 chat_client_cls=None):
        self.channel = channel
        self.access_token = access_token
        self.client_id = client_id
        self.broadcaster_user_id = broadcaster_user_id
        self.user_id = user_id
        self._client_cls_used = chat_client_cls or FakeChatClient
        self._client = self._client_cls_used(channel)
        self.shown = False
        self.closed = False
        FakeChatOverlay.instances.append(self)

    def show(self):
        self.shown = True

    def close(self):
        if self._client is not None:
            self._client.disconnect()
        self.closed = True
```

(This changes `FakeChatOverlay`'s signature for every existing test in the file too - re-run the
full file in Step 4, not just the three new tests, since `FakeChatClient(channel)` is still called
positionally inside it and must keep working given Task 6's changes made that still valid.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/windows/test_player.py -k "engine or broadcaster_id" -v`
Expected: FAIL - `play_stream` doesn't accept `access_token`/`client_id`/`user_id` yet, and
`FakeSettings` has no `chat_engine` attribute in the old tests' plain `FakeSettings` (only the new
`FakeSettingsWithEngine` does) - existing tests using bare `FakeSettings` will need
`FakeSettings.chat_engine` to default to `"irc"` too, so `play_stream`'s new code path doesn't
blow up on `settings.chat_engine` for tests that don't care about this feature. Add that default
to the existing `FakeSettings.__init__` in the same file:

```python
class FakeSettings:
    def __init__(self, chat_display_mode, chat_engine="irc"):
        self.chat_display_mode = chat_display_mode
        self.chat_engine = chat_engine
```

(This is a one-line change to an existing fixture, not a new test - do it as part of Step 1 above,
then re-run.)

- [ ] **Step 3: Implement**

In `lib/windows/player.py`, add the import and a small engine-to-class map, then update
`play_stream`:

```python
from lib.twitch import api
from lib.twitch import eventsub
from lib.twitch import irc

_CHAT_CLIENT_CLS_BY_ENGINE = {"irc": irc.ChatClient, "eventsub": eventsub.ChatClient}


def play_stream(url, channel, settings=None, access_token=None, client_id=None, user_id=None,
                 chat_overlay_cls=None, chat_client_cls=None):
    """... (existing docstring, extend with:) access_token/client_id/user_id are the logged-in
    user's Helix credentials - required only when settings.chat_engine == "eventsub" (to resolve
    the channel's numeric id and subscribe); ignored for the default "irc" engine."""
    global _current_chat_watcher

    is_helper = Helper("hls")
    if not is_helper.check_inputstream():
        return False

    list_item = xbmcgui.ListItem(path=url)
    list_item.setProperty("inputstream", is_helper.inputstream_addon)
    list_item.setProperty("inputstream.adaptive.manifest_type", "hls")
    list_item.setMimeType("application/x-mpegURL")
    list_item.setContentLookup(False)
    xbmc.Player().play(url, list_item)

    settings = settings or Settings()
    if settings.chat_display_mode in ("overlay", "both"):
        try:
            if _current_chat_watcher is not None:
                _current_chat_watcher._teardown()
                _current_chat_watcher = None

            engine = settings.chat_engine
            broadcaster_user_id = None
            if chat_client_cls is None and engine == "eventsub":
                user = api.get_user_by_login(access_token, client_id, channel)
                if user is None:
                    xbmc.log(
                        "script.twitch.center: EventSub chat engine could not resolve "
                        "broadcaster id for %r, falling back to IRC" % channel,
                        xbmc.LOGWARNING,
                    )
                    engine = "irc"
                else:
                    broadcaster_user_id = user["id"]

            resolved_chat_client_cls = chat_client_cls or _CHAT_CLIENT_CLS_BY_ENGINE[engine]

            overlay_cls = chat_overlay_cls or ChatOverlay
            overlay = overlay_cls(
                "script-twitch-center-chat-overlay.xml",
                xbmcaddon.Addon().getAddonInfo("path"),
                "Default",
                "1080i",
                channel=channel,
                access_token=access_token,
                client_id=client_id,
                broadcaster_user_id=broadcaster_user_id,
                user_id=user_id,
                chat_client_cls=resolved_chat_client_cls,
            )
            overlay.show()
            website_token = _website_token_from_settings(settings)
            _current_chat_watcher = _ChatAwarePlayer(
                overlay, url=url, channel=channel, website_token=website_token
            )
        except Exception as exc:
            xbmc.log(
                "script.twitch.center: chat overlay failed to start: " + repr(exc),
                xbmc.LOGERROR,
            )

    return True
```

Note the `if chat_client_cls is None and engine == "eventsub":` guard: when a test (or future
caller) explicitly passes `chat_client_cls`, engine selection and ID resolution are skipped
entirely - this preserves every existing test in `test_player.py` that passes
`chat_client_cls=FakeChatClient` and expects no `api.get_user_by_login` call to happen.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/windows/test_player.py -v`
Expected: PASS (full file)

- [ ] **Step 5: Commit**

```bash
git add lib/windows/player.py tests/windows/test_player.py
git commit -m "feat: pick chat engine (irc/eventsub) in play_stream, resolving EventSub's broadcaster id"
```

---

### Task 9: Wire `token`/`client_id` through from the three `play_stream` call sites

**Files:**
- Modify: `lib/views/search_view.py:118`
- Modify: `lib/views/discover_view.py:275`
- Modify: `lib/views/live_streams_view.py:335`
- Test: `tests/views/test_search_view.py`, `tests/views/test_discover_view.py`,
  `tests/views/test_live_streams_view.py`

**Interfaces:**
- Consumes: `player.play_stream`'s new `access_token`/`client_id`/`user_id` params (Task 8).

- [ ] **Step 1: Read each call site's surrounding context first**

Before writing anything, read `lib/views/live_streams_view.py` around line 335 (and the
equivalent spots in the other two files) to confirm the exact local variable names holding the
token and client_id at that point in the method - this plan's earlier research found `token` and
`client_id` are both already in scope in each of these methods (used just above for their own
Helix calls), but the exact variable names must be confirmed by reading the real code, not assumed
from this plan.

- [ ] **Step 2: Write the failing tests**

In each of the three test files, find (or add, if none currently exists) a test that patches
`player.play_stream` and asserts on its call args - add assertions that `access_token`, `client_id`,
and `user_id` are passed through. Example shape for `tests/views/test_live_streams_view.py`
(adapt variable/fixture names to match what's actually in that file):

```python
def test_play_stream_receives_token_and_client_id(...):
    # ... existing setup that gets to the point of clicking a live channel ...
    with patch("lib.views.live_streams_view.player.play_stream") as mock_play_stream:
        # ... trigger the click/select action that calls play_stream ...
        pass
    call_kwargs = mock_play_stream.call_args.kwargs
    assert call_kwargs["access_token"] == token["access_token"]
    assert call_kwargs["client_id"] == client_id
    assert call_kwargs["user_id"] == token["user_id"]
```

Write the real version of this against each file's actual existing test setup/fixtures (login
token construction, mock addon, etc.) - don't invent a `token`/`client_id` shape that doesn't
match what that file's other tests already build.

- [ ] **Step 3: Run tests to verify they fail**

Run: `pytest tests/views/test_search_view.py tests/views/test_discover_view.py tests/views/test_live_streams_view.py -v`
Expected: FAIL on the new assertions (current calls don't pass `access_token`/`client_id`/`user_id`)

- [ ] **Step 4: Implement**

In each of the three call sites, change:

```python
player.play_stream(url, login)
```

(`search_view.py:118`) and the `broadcaster_login` equivalents in the other two files, to:

```python
player.play_stream(
    url, login, access_token=token["access_token"], client_id=client_id, user_id=token["user_id"]
)
```

using whatever the confirmed-in-Step-1 local variable names actually are at each site (they may
not literally be `token`/`client_id`/`login` in every file - use what Step 1 found).

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/views/test_search_view.py tests/views/test_discover_view.py tests/views/test_live_streams_view.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add lib/views/search_view.py lib/views/discover_view.py lib/views/live_streams_view.py tests/views/test_search_view.py tests/views/test_discover_view.py tests/views/test_live_streams_view.py
git commit -m "feat: pass token/client_id through to play_stream for EventSub chat engine support"
```

---

### Task 10: Full test suite, `addon.xml` version bump, `CHANGELOG.md`, `TODO.md`

**Files:**
- Modify: `addon.xml`
- Modify: `CHANGELOG.md`
- Modify: `TODO.md`

- [ ] **Step 1: Run the full test suite**

Run: `pytest -v`
Expected: PASS, all tests including `tests/test_architecture.py`.

- [ ] **Step 2: Bump `addon.xml` version and add a `<news>` entry**

Current version is `0.15.2` (per `addon.xml:2`) - bump to `0.16.0` (new feature, per semver-ish
convention this project's `<news>` history already follows - e.g. v0.10.0 for the original chat
overlay, v0.11.0 for a new setting). Update `<addon ... version="0.16.0" ...>` and prepend to
`<news>`:

```
      v0.16.0: New "Chat engine" setting (Settings > General) - choose between the existing
      anonymous IRC chat (default, no login needed) and Twitch's officially-supported EventSub
      chat API (requires being logged in; falls back to IRC automatically if the channel's id
      can't be resolved or the subscription fails, e.g. an old login without the new chat scope).
```

- [ ] **Step 3: Add a `CHANGELOG.md` entry**

Following the existing `## [x.y.z] - date` / `### Added` format at the top of the file:

```markdown
## [0.16.0] - 2026-08-18

### Added
- New "Chat engine" setting (Settings > General): choose between the existing anonymous IRC chat
  (default) and Twitch's EventSub chat API (requires login; falls back to IRC if id resolution or
  subscription fails).
```

- [ ] **Step 4: Update `TODO.md`'s existing backlog entry**

Find the "Migrate chat from IRC to EventSub" bullet (currently around line 43) and mark it done,
noting it landed as a selectable setting rather than a full migration:

```markdown
- ~~Migrate chat from IRC to EventSub~~ DONE (v0.16.0), as a selectable `chat_engine` setting
  rather than a full replacement - `lib/twitch/eventsub.py`'s `ChatClient` is available alongside
  `lib/twitch/irc.py`'s, chosen via Settings > General > "Chat engine" (default stays `irc`).
```

- [ ] **Step 5: Commit**

```bash
git add addon.xml CHANGELOG.md TODO.md
git commit -m "chore: bump version to 0.16.0, changelog and TODO for the EventSub chat engine setting"
```

---

## Self-review notes (for the plan author, not a task to execute)

- Spec coverage: settings (Task 5), auth scope (Task 2), Helix additions (Task 1), WS primitives +
  ChatClient (Tasks 3-4), shared constructor shape on both engines (Tasks 4 & 6), overlay wiring
  (Task 7), player engine selection + ID resolution + fallback (Task 8), call-site plumbing (Task
  9), versioning/docs (Task 10) - all covered.
- Every code step above contains real, complete code - no "add error handling" placeholders.
  Task 9 is the one exception-shaped step (exact variable names deferred to "read the file first")
  because this plan's author read the call sites' surrounding lines but not their full method
  bodies; Task 9 Step 1 explicitly requires confirming names against real code before writing
  anything, which is a legitimate plan pattern (not a placeholder) since the *shape* of the change
  and the exact new call signature are both fully specified.
- Removed a stray leftover constant (`IRC_LIKE_QUEUE_POLL_TIMEOUT`) from Task 4's code block during
  self-review - it was dead scratch text from drafting, not part of the intended implementation.
