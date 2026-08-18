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
