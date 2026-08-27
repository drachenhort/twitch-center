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

EMOTE_IMAGE_URL_TEMPLATE = "https://static-cdn.jtvnw.net/emoticons/v2/{id}/static/dark/1.0"
_MAX_EMOTES_PER_MESSAGE = 6


def _extract_emotes(fragments):
    """Return up to _MAX_EMOTES_PER_MESSAGE {"id", "text", "url"} dicts, one per "emote"-type
    fragment in Twitch's channel.chat.message event.message.fragments list, in order. Never
    raises: a missing/non-list fragments value, or an individual fragment missing "type"/"id"/
    "emote", is treated as contributing no emote (skipped, not fatal)."""
    if not isinstance(fragments, list):
        return []
    emotes = []
    for fragment in fragments:
        if len(emotes) >= _MAX_EMOTES_PER_MESSAGE:
            break
        if not isinstance(fragment, dict) or fragment.get("type") != "emote":
            continue
        emote = fragment.get("emote")
        if not isinstance(emote, dict):
            continue
        emote_id = emote.get("id")
        if not emote_id:
            continue
        emotes.append({
            "id": emote_id,
            "text": fragment.get("text", ""),
            "url": EMOTE_IMAGE_URL_TEMPLATE.format(id=emote_id),
        })
    return emotes


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
            except Exception as exc:
                last_error = repr(exc)
                self._enqueue({
                    "type": "error",
                    "message": "Chat connection failed: " + str(exc),
                })
            else:
                last_error = None
            finally:
                if self._sock is not None:
                    try:
                        self._sock.close()
                    except OSError:
                        pass
                    self._sock = None

            if self._cancel_event.wait(_DISCONNECT_GRACE):
                break

            status_event = {"type": "status", "state": "disconnected"}
            if last_error is not None:
                status_event["error"] = last_error
            self._enqueue(status_event)
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
            if frame["opcode"] == _OPCODE_PING:
                self._sock.sendall(_encode_client_frame(frame["payload"], opcode=_OPCODE_PONG))
                continue
            if frame["opcode"] == _OPCODE_CLOSE:
                raise ConnectionError("EventSub server closed the connection")
            if frame["opcode"] != _OPCODE_TEXT:
                continue
            if not frame["fin"]:
                raise ConnectionError("EventSub: fragmented messages are not supported")
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
            if not frame["fin"]:
                raise ConnectionError("EventSub: fragmented messages are not supported")
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
                "emotes": _extract_emotes(event.get("message", {}).get("fragments")),
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


class LiveNotifyClient:
    """EventSub client for stream.online notifications across an arbitrary, changeable set of
    broadcasters - unlike ChatClient, which is scoped to one broadcaster and two fixed
    subscription types. See docs/superpowers/specs/2026-08-26-live-go-notifications-design.md."""

    def __init__(self, access_token, client_id, socket_factory=None, sleep_fn=None,
                 create_subscription_fn=None, delete_subscription_fn=None, time_fn=None):
        self._access_token = access_token
        self._client_id = client_id
        self._socket_factory = socket_factory or _default_socket_factory
        self._sleep_fn = sleep_fn or time.sleep
        self._create_subscription_fn = create_subscription_fn or api.create_eventsub_subscription
        self._delete_subscription_fn = delete_subscription_fn or api.delete_eventsub_subscription
        self._time_fn = time_fn or time.time
        self._queue = Queue(maxsize=_QUEUE_MAXSIZE)
        self._cancel_event = threading.Event()
        self._thread = None
        self._sock = None
        self._recv_buffer = b""
        self._keepalive_timeout = _REQUESTED_KEEPALIVE_SECONDS
        self._last_message_at = 0

        self._lock = threading.Lock()
        self._desired_ids = set()
        self._session_id = None
        self._active_subs = {}  # broadcaster_user_id -> subscription_id

    def connect(self):
        if self._thread is not None and self._thread.is_alive():
            return
        self._cancel_event.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def set_broadcasters(self, broadcaster_user_ids):
        new_ids = set(broadcaster_user_ids)
        with self._lock:
            self._desired_ids = new_ids
            session_id = self._session_id
            if session_id is None:
                return
            to_add = new_ids - set(self._active_subs)
            to_remove = set(self._active_subs) - new_ids

        self._diff_subscriptions(session_id, to_add, to_remove)

    def _diff_subscriptions(self, session_id, to_add, to_remove):
        """Applies one add/remove diff against `session_id`. A failure creating or deleting an
        individual broadcaster's subscription (Twitch's subscription cap, a 429, a deleted/banned
        channel returning 400/404, etc.) is isolated to that one broadcaster - logged via a queued
        "subscription_error" event - rather than aborting the rest of the diff."""
        for broadcaster_id in to_add:
            try:
                body = self._create_subscription_fn(
                    self._access_token, self._client_id, session_id, "stream.online",
                    {"broadcaster_user_id": broadcaster_id},
                )
            except Exception as exc:
                self._enqueue({
                    "type": "subscription_error",
                    "broadcaster_user_id": broadcaster_id,
                    "error": repr(exc),
                })
                continue
            with self._lock:
                if self._session_id == session_id:
                    self._active_subs[broadcaster_id] = body["data"][0]["id"]
        for broadcaster_id in to_remove:
            with self._lock:
                subscription_id = self._active_subs.pop(broadcaster_id, None)
            if subscription_id is not None:
                try:
                    self._delete_subscription_fn(self._access_token, self._client_id, subscription_id)
                except Exception as exc:
                    self._enqueue({
                        "type": "subscription_error",
                        "broadcaster_user_id": broadcaster_id,
                        "error": repr(exc),
                    })

    def read_events(self):
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
            with self._lock:
                self._session_id = None
                self._active_subs = {}
            try:
                self._sock = self._socket_factory()
                self._handshake_and_subscribe()
                connected_at = time.time()
                self._enqueue({"type": "status", "state": "connected"})
                self._read_loop()
            except Exception as exc:
                last_error = repr(exc)
            else:
                last_error = None
            finally:
                with self._lock:
                    self._session_id = None
                if self._sock is not None:
                    try:
                        self._sock.close()
                    except OSError:
                        pass
                    self._sock = None

            if self._cancel_event.wait(_DISCONNECT_GRACE):
                break

            status_event = {"type": "status", "state": "disconnected"}
            if last_error is not None:
                status_event["error"] = last_error
            self._enqueue(status_event)
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
            if frame["opcode"] == _OPCODE_PING:
                self._sock.sendall(_encode_client_frame(frame["payload"], opcode=_OPCODE_PONG))
                continue
            if frame["opcode"] == _OPCODE_CLOSE:
                raise ConnectionError("EventSub server closed the connection")
            if frame["opcode"] != _OPCODE_TEXT:
                continue
            if not frame["fin"]:
                raise ConnectionError("EventSub: fragmented messages are not supported")
            payload = json.loads(frame["payload"].decode("utf-8"))
            if payload["metadata"]["message_type"] == "session_welcome":
                session = payload["payload"]["session"]
                session_id = session["id"]
                self._keepalive_timeout = session.get(
                    "keepalive_timeout_seconds", _REQUESTED_KEEPALIVE_SECONDS
                )
                break

        with self._lock:
            desired_ids = set(self._desired_ids)
        active_subs = {}
        for broadcaster_id in desired_ids:
            try:
                body = self._create_subscription_fn(
                    self._access_token, self._client_id, session_id, "stream.online",
                    {"broadcaster_user_id": broadcaster_id},
                )
            except Exception as exc:
                self._enqueue({
                    "type": "subscription_error",
                    "broadcaster_user_id": broadcaster_id,
                    "error": repr(exc),
                })
                continue
            active_subs[broadcaster_id] = body["data"][0]["id"]
        with self._lock:
            self._session_id = session_id
            self._active_subs = active_subs
            # A set_broadcasters() call that landed while this loop was subscribing (after
            # desired_ids was snapshotted above, before _session_id/_active_subs were published
            # just now) saw _session_id as None, updated _desired_ids for "next time", and
            # returned early without subscribing anything - since _active_subs is about to be
            # (has just been) overwritten with this handshake's snapshot, that would silently
            # lose the new broadcaster until the next follow-refresh. Catch up here if
            # _desired_ids drifted from what we just subscribed.
            catchup_needed = self._desired_ids != desired_ids
            if catchup_needed:
                catchup_to_add = self._desired_ids - set(self._active_subs)
                catchup_to_remove = set(self._active_subs) - self._desired_ids
        if catchup_needed:
            self._diff_subscriptions(session_id, catchup_to_add, catchup_to_remove)
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
            if not frame["fin"]:
                raise ConnectionError("EventSub: fragmented messages are not supported")
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
        if subscription_type == "stream.online":
            self._enqueue({
                "type": "stream_online",
                "broadcaster_user_id": event["broadcaster_user_id"],
                "broadcaster_user_login": event["broadcaster_user_login"],
                "broadcaster_user_name": event["broadcaster_user_name"],
            })
        else:
            self._enqueue({"type": "raw", "line": json.dumps(payload)})
