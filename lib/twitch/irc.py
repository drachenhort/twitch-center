"""IRC chat client for irc.chat.twitch.tv. No xbmc* imports - pure Python, pytest-testable."""
import random
import socket as socket_module
import ssl
import threading
import time
from queue import Empty, Queue


def _parse_tags(tag_str):
    tags = {}
    for pair in tag_str.split(";"):
        if not pair:
            continue
        key, _, value = pair.partition("=")
        tags[key] = value
    return tags


def parse_line(line, now_ms=None):
    """Parse one raw Twitch IRC line into an event dict.

    Returns one of:
      {"type": "message", "username", "display_name", "text", "timestamp"}
      {"type": "raid", "from_channel", "display_name", "viewer_count", "timestamp"}
      {"type": "raw", "line"}
    PING is deliberately not handled here - the caller must check for it
    before calling parse_line, since it requires a direct socket reply
    rather than a queue event."""
    if now_ms is None:
        now_ms = int(time.time() * 1000)

    rest = line
    tags = {}
    if rest.startswith("@"):
        tag_part, _, rest = rest.partition(" ")
        tags = _parse_tags(tag_part[1:])

    prefix = ""
    if rest.startswith(":"):
        prefix_part, _, rest = rest.partition(" ")
        prefix = prefix_part[1:]

    if " :" in rest:
        head, _, trailing = rest.partition(" :")
    else:
        head, trailing = rest, ""

    command = head.split()[0] if head.split() else ""
    timestamp = int(tags["tmi-sent-ts"]) if "tmi-sent-ts" in tags else now_ms

    if command == "PRIVMSG":
        username = prefix.split("!")[0] if "!" in prefix else prefix
        return {
            "type": "message",
            "username": username,
            "display_name": tags.get("display-name", username),
            "text": trailing,
            "timestamp": timestamp,
        }

    if command == "USERNOTICE" and tags.get("msg-id") == "raid":
        try:
            viewer_count = int(tags.get("msg-param-viewerCount", "0"))
        except ValueError:
            viewer_count = 0
        return {
            "type": "raid",
            "from_channel": tags.get("msg-param-login", ""),
            "display_name": tags.get("msg-param-displayName", ""),
            "viewer_count": viewer_count,
            "timestamp": timestamp,
        }

    return {"type": "raw", "line": line}


IRC_HOST = "irc.chat.twitch.tv"
IRC_PORT = 6697

_QUEUE_POLL_TIMEOUT = 0.5

_BACKOFF_START = 1
_BACKOFF_MAX = 30
_BACKOFF_RESET_AFTER = 30  # seconds a connection must stay up to reset backoff


def _default_socket_factory():
    raw = socket_module.create_connection((IRC_HOST, IRC_PORT), timeout=10)
    context = ssl.create_default_context()
    return context.wrap_socket(raw, server_hostname=IRC_HOST)


class ChatClient:
    def __init__(self, channel, socket_factory=None, sleep_fn=None):
        self.channel = channel
        self._socket_factory = socket_factory or _default_socket_factory
        self._sleep_fn = sleep_fn or time.sleep
        self._queue = Queue()
        self._cancel_event = threading.Event()
        self._thread = None
        self._sock = None

    def connect(self):
        """Opens the IRC socket connection and authenticates, on a
        background thread. Returns immediately."""
        self._cancel_event.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def read_messages(self):
        """Yield chat message dicts (at least: username, message, timestamp) as they arrive."""
        while not (self._cancel_event.is_set() and self._queue.empty()):
            try:
                yield self._queue.get(timeout=_QUEUE_POLL_TIMEOUT)
            except Empty:
                continue

    def disconnect(self):
        """Close the IRC socket connection."""
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
            try:
                self._sock = self._socket_factory()
                self._handshake()
                connected_at = time.time()
                self._queue.put({"type": "status", "state": "connected"})
                self._read_loop()
            except (OSError, ConnectionError):
                pass
            finally:
                if self._sock is not None:
                    try:
                        self._sock.close()
                    except OSError:
                        pass
                    self._sock = None

            # Give a concurrent disconnect() a brief window to set the
            # cancel event before we treat this as a failure needing a
            # backoff/retry cycle - closes the race between a just-closed
            # connection and an in-flight disconnect() call.
            if self._cancel_event.wait(0.05):
                break

            self._queue.put({"type": "status", "state": "disconnected"})
            if connected_at is not None and (time.time() - connected_at) > _BACKOFF_RESET_AFTER:
                backoff = _BACKOFF_START
            self._sleep_fn(backoff)
            backoff = min(backoff * 2, _BACKOFF_MAX)

    def _read_loop(self):
        buffer = ""
        while not self._cancel_event.is_set():
            data = self._sock.recv(4096)
            if not data:
                raise ConnectionError("connection closed by server")
            buffer += data.decode("utf-8", errors="replace")
            while "\r\n" in buffer:
                line, buffer = buffer.split("\r\n", 1)
                if line:
                    self._handle_line(line)

    def _handle_line(self, line):
        if line.startswith("PING"):
            self._send("PONG :tmi.twitch.tv")
            return
        self._queue.put(parse_line(line))

    def _handshake(self):
        nick = "justinfan%d" % random.randint(10000, 99999)
        self._send("CAP REQ :twitch.tv/tags twitch.tv/commands")
        self._send("PASS SCHMOOPIIE")
        self._send("NICK " + nick)
        self._send("JOIN #" + self.channel)

    def _send(self, line):
        self._sock.sendall((line + "\r\n").encode("utf-8"))
