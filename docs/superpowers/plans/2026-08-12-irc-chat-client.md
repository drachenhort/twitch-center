# IRC Chat Client Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the `NotImplementedError` stub in `lib/twitch/irc.py`'s `ChatClient` with a real
anonymous Twitch IRC connection that delivers parsed chat/raid events to a consumer via a
thread-safe queue, with automatic reconnect-with-backoff.

**Architecture:** A background `threading.Thread` (spawned by `connect()`, matching the shape
`LoginWindow` already uses for its device-code polling) owns a TLS socket to
`irc.chat.twitch.tv:6697`, sends Twitch's anonymous `justinfan` login + `JOIN`, then loops on
`recv()`, splitting buffered bytes into `\r\n`-terminated lines. Each line is parsed by a
standalone `parse_line()` function into an event dict and pushed onto a `queue.Queue`, which
`read_messages()` drains as a generator. `PING` is answered with `PONG` directly on the socket, not
queued. Socket errors trigger a backoff-and-retry loop instead of raising, until `disconnect()` is
called.

**Tech Stack:** Python stdlib only — `socket`, `ssl`, `threading`, `queue`, `random`, `time`. No new
dependencies. Kept `xbmc*`-import-free per `tests/test_architecture.py`'s static check.

## Global Constraints

- `lib/twitch/irc.py` must import zero `xbmc*` modules (enforced by
  `tests/test_architecture.py::test_lib_twitch_has_no_xbmc_imports`).
- Anonymous connection only (`justinfan<N>` login) — no OAuth token used.
- `connect()` is non-blocking (spawns a thread and returns immediately).
- `socket_factory` and `sleep_fn` constructor params make `ChatClient` fully testable without a
  real network connection or real time delays.
- No test in this plan hits Twitch's real IRC server.

Spec: `docs/superpowers/specs/2026-08-12-irc-chat-client-design.md`

---

### Task 1: Line parser — PRIVMSG and raw passthrough

**Files:**
- Modify: `lib/twitch/irc.py` (add `_parse_tags` and `parse_line` module-level functions, above the
  existing `ChatClient` stub)
- Test: `tests/twitch/test_irc.py` (new test functions; existing
  `test_chat_client_*_not_implemented` tests will be deleted in Task 3 when the stub is replaced —
  leave them alone for now)

**Interfaces:**
- Produces: `parse_line(line: str, now_ms: int | None = None) -> dict`. Returns `{"type":
  "message", "username": str, "display_name": str, "text": str, "timestamp": int}` for `PRIVMSG`,
  or `{"type": "raw", "line": str}` for anything unrecognized. `now_ms` is an injectable "current
  time in ms" for deterministic tests (defaults to `int(time.time() * 1000)`).

- [ ] **Step 1: Write the failing tests**

Add to `tests/twitch/test_irc.py` (create the file fresh — it currently only has the
`NotImplementedError` tests):

```python
from lib.twitch.irc import parse_line


def test_parse_line_privmsg_with_tags():
    line = (
        "@display-name=Bob;tmi-sent-ts=1000 "
        ":bob!bob@bob.tmi.twitch.tv PRIVMSG #somechannel :hello there"
    )
    event = parse_line(line)
    assert event == {
        "type": "message",
        "username": "bob",
        "display_name": "Bob",
        "text": "hello there",
        "timestamp": 1000,
    }


def test_parse_line_privmsg_without_display_name_tag_falls_back_to_username():
    line = ":carol!carol@carol.tmi.twitch.tv PRIVMSG #somechannel :hi"
    event = parse_line(line, now_ms=5000)
    assert event["username"] == "carol"
    assert event["display_name"] == "carol"
    assert event["timestamp"] == 5000


def test_parse_line_unrecognized_command_is_raw_passthrough():
    line = ":tmi.twitch.tv 001 justinfan12345 :Welcome, GLHF!"
    event = parse_line(line)
    assert event == {"type": "raw", "line": line}


def test_parse_line_join_is_raw_passthrough():
    line = ":justinfan12345!justinfan12345@justinfan12345.tmi.twitch.tv JOIN #somechannel"
    event = parse_line(line)
    assert event == {"type": "raw", "line": line}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/twitch/test_irc.py -v -k parse_line`
Expected: FAIL with `ImportError: cannot import name 'parse_line'` (it doesn't exist yet).

- [ ] **Step 3: Implement `_parse_tags` and `parse_line`**

At the top of `lib/twitch/irc.py`, above the existing `class ChatClient:`:

```python
"""IRC chat client for irc.chat.twitch.tv. No xbmc* imports - pure Python, pytest-testable."""
import time


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

    return {"type": "raw", "line": line}
```

Leave the existing `class ChatClient:` stub below this untouched for now — Task 3 replaces it.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/twitch/test_irc.py -v -k parse_line`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add lib/twitch/irc.py tests/twitch/test_irc.py
git commit -m "feat: parse PRIVMSG lines from Twitch IRC"
```

---

### Task 2: Line parser — raid events and malformed-tag fallback

**Files:**
- Modify: `lib/twitch/irc.py` (extend `parse_line`)
- Test: `tests/twitch/test_irc.py`

**Interfaces:**
- Consumes: `parse_line` from Task 1.
- Produces: `parse_line` now also returns `{"type": "raid", "from_channel": str, "display_name":
  str, "viewer_count": int, "timestamp": int}` for `USERNOTICE` with `msg-id=raid`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/twitch/test_irc.py`:

```python
def test_parse_line_usernotice_raid():
    line = (
        "@msg-id=raid;msg-param-displayName=CoolRaider;msg-param-login=coolraider;"
        "msg-param-viewerCount=42;tmi-sent-ts=2000 "
        ":tmi.twitch.tv USERNOTICE #somechannel :CoolRaider is raiding with 42 viewers!"
    )
    event = parse_line(line)
    assert event == {
        "type": "raid",
        "from_channel": "coolraider",
        "display_name": "CoolRaider",
        "viewer_count": 42,
        "timestamp": 2000,
    }


def test_parse_line_usernotice_non_raid_is_raw_passthrough():
    line = "@msg-id=sub;tmi-sent-ts=3000 :tmi.twitch.tv USERNOTICE #somechannel :Dave subscribed!"
    event = parse_line(line)
    assert event == {"type": "raw", "line": line}


def test_parse_line_raid_with_non_numeric_viewer_count_defaults_to_zero():
    line = (
        "@msg-id=raid;msg-param-displayName=CoolRaider;msg-param-login=coolraider;"
        "msg-param-viewerCount=not-a-number "
        ":tmi.twitch.tv USERNOTICE #somechannel :raiding!"
    )
    event = parse_line(line, now_ms=9000)
    assert event["type"] == "raid"
    assert event["viewer_count"] == 0
    assert event["timestamp"] == 9000
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/twitch/test_irc.py -v -k raid`
Expected: FAIL — `USERNOTICE`/raid lines currently fall through to `{"type": "raw", ...}` instead of
a raid event, so the first and third tests fail on the assertion.

- [ ] **Step 3: Extend `parse_line`**

In `lib/twitch/irc.py`, add the raid branch to `parse_line`, right after the existing `PRIVMSG`
branch and before the final `return {"type": "raw", "line": line}`:

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/twitch/test_irc.py -v`
Expected: all 7 tests so far pass.

- [ ] **Step 5: Commit**

```bash
git add lib/twitch/irc.py tests/twitch/test_irc.py
git commit -m "feat: parse raid USERNOTICE events from Twitch IRC"
```

---

### Task 3: `ChatClient` connect/handshake/disconnect scaffolding

**Files:**
- Modify: `lib/twitch/irc.py` (replace the stub `ChatClient` class entirely)
- Test: `tests/twitch/test_irc.py` (delete the 3 old `test_chat_client_*_not_implemented` tests —
  the methods they test no longer raise `NotImplementedError`)

**Interfaces:**
- Consumes: `parse_line` from Tasks 1-2 (not called yet in this task — wired in Task 4).
- Produces:
  - `ChatClient(channel: str, socket_factory: Callable[[], object] | None = None, sleep_fn:
    Callable[[float], None] | None = None)`
  - `ChatClient.connect() -> None` — spawns background thread, returns immediately.
  - `ChatClient.disconnect() -> None` — idempotent, stops the thread.
  - `ChatClient._sock` — internal attribute holding the current socket-like object, `None` when not
    connected (used by later tasks' tests to introspect).
  - Test-only `FakeSocket` class (in the test file) with `.sendall(bytes)`, `.recv(bufsize) ->
    bytes` (raises if given an `Exception` instance in its queue), `.close()` — later tasks reuse
    this.

- [ ] **Step 1: Write the failing test**

First, delete the 3 obsolete tests from `tests/twitch/test_irc.py`:

```python
def test_chat_client_connect_not_implemented():
    ...

def test_chat_client_read_messages_not_implemented():
    ...

def test_chat_client_disconnect_not_implemented():
    ...
```

(remove these 3 function definitions and the `import pytest` line if nothing else in the file uses
`pytest` after removing them — check before deleting the import).

Add the `FakeSocket` helper and a handshake test:

```python
import threading

from lib.twitch.irc import ChatClient


class FakeSocket:
    """Records sent bytes, replays queued recv() results. A queued item that
    is an Exception instance is raised instead of returned."""

    def __init__(self, recv_queue=None):
        self._recv_queue = list(recv_queue or [])
        self.sent = []
        self.closed = False

    def sendall(self, data):
        self.sent.append(data.decode("utf-8"))

    def recv(self, bufsize):
        if not self._recv_queue:
            return b""
        item = self._recv_queue.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    def close(self):
        self.closed = True


def test_connect_sends_anonymous_login_and_join():
    fake = FakeSocket()
    client = ChatClient("somechannel", socket_factory=lambda: fake, sleep_fn=lambda s: None)
    client.connect()
    try:
        # Handshake happens synchronously at the start of the background
        # thread, before it blocks on recv() - give it a moment to run.
        for _ in range(100):
            if len(fake.sent) >= 4:
                break
            threading.Event().wait(0.01)
    finally:
        client.disconnect()

    assert "CAP REQ :twitch.tv/tags twitch.tv/commands\r\n" in fake.sent
    assert "PASS SCHMOOPIIE\r\n" in fake.sent
    assert any(s.startswith("NICK justinfan") for s in fake.sent)
    assert "JOIN #somechannel\r\n" in fake.sent


def test_disconnect_is_safe_to_call_twice():
    fake = FakeSocket()
    client = ChatClient("somechannel", socket_factory=lambda: fake, sleep_fn=lambda s: None)
    client.connect()
    client.disconnect()
    client.disconnect()  # must not raise
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/twitch/test_irc.py -v -k "connect_sends or disconnect_is_safe"`
Expected: FAIL — `ChatClient.connect()`/`disconnect()` currently raise `NotImplementedError`.

- [ ] **Step 3: Replace the `ChatClient` stub**

Replace the entire existing `class ChatClient:` block in `lib/twitch/irc.py` with:

```python
import random
import socket as socket_module
import ssl
import threading
from queue import Empty, Queue

IRC_HOST = "irc.chat.twitch.tv"
IRC_PORT = 6697

_QUEUE_POLL_TIMEOUT = 0.5


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
        try:
            self._sock = self._socket_factory()
            self._handshake()
        except (OSError, ConnectionError):
            pass
        finally:
            if self._sock is not None:
                try:
                    self._sock.close()
                except OSError:
                    pass

    def _handshake(self):
        nick = "justinfan%d" % random.randint(10000, 99999)
        self._send("CAP REQ :twitch.tv/tags twitch.tv/commands")
        self._send("PASS SCHMOOPIIE")
        self._send("NICK " + nick)
        self._send("JOIN #" + self.channel)

    def _send(self, line):
        self._sock.sendall((line + "\r\n").encode("utf-8"))
```

Note: `_run` in this task only performs the handshake and then falls through to closing the
socket — the read loop and reconnect logic are added in Tasks 4 and 5. This keeps this task's
diff reviewable on its own: handshake behavior is independently testable before the read loop
exists.

Also add `import time` at the top of the file if it isn't already there from Task 1.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/twitch/test_irc.py -v`
Expected: all tests pass (parser tests from Tasks 1-2, plus the 2 new ones; the 3 old
`NotImplementedError` tests are gone).

- [ ] **Step 5: Commit**

```bash
git add lib/twitch/irc.py tests/twitch/test_irc.py
git commit -m "feat: ChatClient connects and sends anonymous Twitch IRC login"
```

---

### Task 4: Read loop — PING/PONG handling and message delivery

**Files:**
- Modify: `lib/twitch/irc.py` (`ChatClient._run`, add `_read_loop` and `_handle_line`)
- Test: `tests/twitch/test_irc.py`

**Interfaces:**
- Consumes: `parse_line` (Tasks 1-2), `FakeSocket` (Task 3), `ChatClient._sock`/`_queue` (Task 3).
- Produces: `ChatClient` now pushes `{"type": "status", "state": "connected"}` after a successful
  handshake, then parsed message/raid/raw events as lines arrive, and replies to `PING` without
  queuing it.

- [ ] **Step 1: Write the failing tests**

Add to `tests/twitch/test_irc.py`:

```python
def test_read_messages_yields_connected_status_then_privmsg():
    line = "@display-name=Bob;tmi-sent-ts=1000 :bob!bob@bob.tmi.twitch.tv PRIVMSG #chan :hello\r\n"
    fake = FakeSocket(recv_queue=[line.encode("utf-8")])
    client = ChatClient("chan", socket_factory=lambda: fake, sleep_fn=lambda s: None)
    client.connect()

    events = []
    for event in client.read_messages():
        events.append(event)
        if event["type"] == "message":
            break
    client.disconnect()

    assert events[0] == {"type": "status", "state": "connected"}
    assert events[1] == {
        "type": "message",
        "username": "bob",
        "display_name": "Bob",
        "text": "hello",
        "timestamp": 1000,
    }


def test_ping_is_answered_with_pong_and_not_queued():
    # Follow the PING with a real PRIVMSG so the test has a deterministic
    # stopping point after confirming PING was handled.
    privmsg = ":a!a@a PRIVMSG #chan :after ping\r\n"
    fake = FakeSocket(recv_queue=[b"PING :tmi.twitch.tv\r\n", privmsg.encode("utf-8")])
    client = ChatClient("chan", socket_factory=lambda: fake, sleep_fn=lambda s: None)
    client.connect()

    events = []
    for event in client.read_messages():
        events.append(event)
        if event["type"] == "message":
            break
    client.disconnect()

    assert [e["type"] for e in events] == ["status", "message"]
    assert "PONG :tmi.twitch.tv\r\n" in fake.sent
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/twitch/test_irc.py -v -k "read_messages_yields or ping_is_answered"`
Expected: FAIL — `read_messages()` currently yields nothing because `_run` never enters a read
loop or pushes a `"connected"` status.

- [ ] **Step 3: Implement the read loop**

In `lib/twitch/irc.py`, replace `_run` and add `_read_loop`/`_handle_line`:

```python
    def _run(self):
        try:
            self._sock = self._socket_factory()
            self._handshake()
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
```

Add `from lib.twitch.irc import parse_line` — no, `parse_line` is already in the same module from
Task 1, so just call it directly (no import needed within the same file).

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/twitch/test_irc.py -v`
Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add lib/twitch/irc.py tests/twitch/test_irc.py
git commit -m "feat: ChatClient reads and delivers parsed IRC messages"
```

---

### Task 5: Reconnect with backoff and status events

**Files:**
- Modify: `lib/twitch/irc.py` (`ChatClient._run`)
- Test: `tests/twitch/test_irc.py`

**Interfaces:**
- Consumes: everything from Tasks 1-4.
- Produces: on a socket error (not a clean `disconnect()`), `ChatClient` pushes `{"type":
  "status", "state": "disconnected"}`, calls `self._sleep_fn(backoff)`, then reconnects via
  `self._socket_factory()` again — repeating indefinitely until `disconnect()` is called. Backoff
  starts at 1s, doubles each consecutive failure, caps at 30s, and resets to 1s after a connection
  has stayed up longer than 30s.

- [ ] **Step 1: Write the failing test**

Add to `tests/twitch/test_irc.py`:

```python
def test_reconnects_with_backoff_after_socket_error():
    good_line = ":a!a@a PRIVMSG #chan :hi\r\n".encode("utf-8")
    sockets = [
        FakeSocket(recv_queue=[ConnectionError("boom")]),
        FakeSocket(recv_queue=[good_line]),
    ]
    factory_calls = iter(sockets)
    sleeps = []
    client = ChatClient(
        "chan",
        socket_factory=lambda: next(factory_calls),
        sleep_fn=lambda seconds: sleeps.append(seconds),
    )
    client.connect()

    events = []
    for event in client.read_messages():
        events.append(event)
        if event["type"] == "message":
            break
    client.disconnect()

    states = [e["state"] for e in events if e["type"] == "status"]
    assert states == ["connected", "disconnected", "connected"]
    assert events[-1]["type"] == "message"
    assert sleeps == [1]


def test_backoff_doubles_on_consecutive_failures():
    sockets = [
        FakeSocket(recv_queue=[ConnectionError("boom")]),
        FakeSocket(recv_queue=[ConnectionError("boom again")]),
        FakeSocket(recv_queue=[":a!a@a PRIVMSG #chan :hi\r\n".encode("utf-8")]),
    ]
    factory_calls = iter(sockets)
    sleeps = []
    client = ChatClient(
        "chan",
        socket_factory=lambda: next(factory_calls),
        sleep_fn=lambda seconds: sleeps.append(seconds),
    )
    client.connect()

    for event in client.read_messages():
        if event["type"] == "message":
            break
    client.disconnect()

    assert sleeps == [1, 2]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/twitch/test_irc.py -v -k "reconnects_with_backoff or backoff_doubles"`
Expected: FAIL — `_run` currently exits after one failed/completed attempt instead of retrying, so
`read_messages()` never yields a second `"connected"` status or the final `"message"` event (the
test hangs or fails depending on generator behavior — if it appears to hang, that itself confirms
the missing retry loop; interrupt with Ctrl-C and proceed to Step 3).

- [ ] **Step 3: Wrap `_run` in a reconnect loop**

Replace `_run` in `lib/twitch/irc.py`:

```python
_BACKOFF_START = 1
_BACKOFF_MAX = 30
_BACKOFF_RESET_AFTER = 30  # seconds a connection must stay up to reset backoff
```

(add these constants near the top, alongside `IRC_HOST`/`IRC_PORT`)

```python
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

            if self._cancel_event.is_set():
                break

            self._queue.put({"type": "status", "state": "disconnected"})
            if connected_at is not None and (time.time() - connected_at) > _BACKOFF_RESET_AFTER:
                backoff = _BACKOFF_START
            self._sleep_fn(backoff)
            backoff = min(backoff * 2, _BACKOFF_MAX)
```

This removes the old single-attempt `_run` body from Task 4 entirely (the `try`/`except`/`finally`
block is now inside the `while` loop instead of being the whole method).

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/twitch/test_irc.py -v`
Expected: all tests pass, including the two new reconnect tests, with no real time delay (thanks to
the injected `sleep_fn`).

- [ ] **Step 5: Commit**

```bash
git add lib/twitch/irc.py tests/twitch/test_irc.py
git commit -m "feat: ChatClient auto-reconnects with backoff on socket errors"
```

---

### Task 6: Full-suite verification and architecture check

**Files:**
- None modified — verification only.

**Interfaces:**
- Consumes: everything from Tasks 1-5.
- Produces: nothing new; confirms the finished `ChatClient` doesn't break any existing test or the
  project's `xbmc*`-import boundary.

- [ ] **Step 1: Run the full test suite**

Run: `python -m pytest tests/ -v`
Expected: all tests pass (the full existing suite plus every test added in Tasks 1-5), zero
failures, zero errors.

- [ ] **Step 2: Run the architecture boundary check specifically**

Run: `python -m pytest tests/test_architecture.py -v`
Expected: `test_lib_twitch_has_no_xbmc_imports` passes — confirms `lib/twitch/irc.py`'s new
`socket`/`ssl`/`threading`/`queue`/`random`/`time` imports didn't accidentally pull in anything
`xbmc*`.

- [ ] **Step 3: Manually verify no leftover references to the old stub behavior**

Run: `grep -rn "NotImplementedError" lib/twitch/irc.py`
Expected: no output (the stub's `raise NotImplementedError` lines are all gone, replaced by real
implementations in Tasks 1-5).

- [ ] **Step 4: Commit (only if Steps 1-3 required any fixes; otherwise skip — nothing to commit)**

```bash
git add -A
git commit -m "test: verify IRC chat client foundation against full suite"
```

## Out of scope (per the spec, not part of this plan)

- `ChatOverlay`/`ChatWindow` remain stubs — wiring them to `ChatClient` and building a chat skin XML
  is a separate follow-up plan.
- Acting on `"raid"` events (auto-switch playback, prompt) is a separate follow-up.
- Authenticated (OAuth) chat connections are not built — anonymous only.
- Emote/badge rendering is not built — chat text is delivered as plain text only.
