# Twitch IRC Chat Client (Foundation): Design

Date: 2026-08-12

## What this is

The foundation for chat support: a real implementation of `lib/twitch/irc.py`'s `ChatClient`
(currently a pure `NotImplementedError` stub), connecting to Twitch's IRC-based chat service and
delivering parsed chat/raid events to a consumer via a thread-safe queue.

This is deliberately scoped to the client only. It does **not** wire up `lib/windows/chat_overlay.py`
or `lib/windows/chat_window.py` (both still `onInit: pass` stubs), does not build a chat skin XML,
and does not implement raid-following behavior — those are separate follow-up specs once this
foundation exists. See `TODO.md` for the full chat/PiP/raid backlog this splits off from.

## Why this shape

Twitch chat is exposed as a standard IRC server (`irc.chat.twitch.tv`) with Twitch-specific
extensions (tag-based metadata via IRCv3 capabilities, `USERNOTICE` events for raids/subs/etc.).
Kodi addons are synchronous/thread-based throughout this codebase (`LoginWindow` already runs a
background `threading.Thread` with a `threading.Event` for cancellation to poll Twitch's
device-code endpoint without blocking the GUI thread) — `ChatClient` follows that same shape rather
than introducing asyncio or a third-party IRC library, keeping the dependency footprint and
threading model consistent with the rest of the addon.

## Scope decisions (from brainstorming)

- **Auth**: anonymous (`justinfan<N>` login). No OAuth token needed — matches this addon's read-only
  chat-viewing design (per `CLAUDE.md`: "not designed for communicating back to the streamer").
- **Delivery model**: background thread + `queue.Queue`. `connect()` is non-blocking; a consumer
  (chat window) calls it in `onInit`, drains `read_messages()` on a timer/poll, and calls
  `disconnect()` on close.
- **Message scope**: parses `PRIVMSG` (chat messages) and `USERNOTICE` with `msg-id=raid` (raid
  events) into structured dicts now, since raid-following is already on the TODO list and reusing
  this same parser avoids touching the socket loop again later. Everything else passes through as a
  generic raw event so nothing is silently dropped.
- **Reconnect**: automatic, with backoff, retried indefinitely until the consumer calls
  `disconnect()`.

## Components

### `lib/twitch/irc.py` (replaces the stub)

Stays pure Python — **no `xbmc*` imports** (per the file's existing header comment and
`tests/test_architecture.py`'s static check, unchanged by this task).

```python
class ChatClient:
    def __init__(self, channel, socket_factory=None, sleep_fn=None):
        """channel: Twitch channel login name (no leading '#').
        socket_factory: callable() -> object with connect/recv/sendall/close,
          defaults to a real TLS-wrapped socket.socket. Injectable for tests.
        sleep_fn: callable(seconds), defaults to time.sleep. Injectable so
          reconnect-backoff tests don't block in real time."""

    def connect(self):
        """Spawns the background thread and returns immediately."""

    def read_messages(self):
        """Generator: pops events off the internal queue.Queue and yields
        them, blocking with a short timeout between checks so it notices
        cancellation/thread death promptly rather than hanging forever on an
        empty queue. Stops when disconnect() has been called and the queue is
        drained."""

    def disconnect(self):
        """Sets the internal cancel_event, closes the socket, joins the
        background thread."""
```

Internal background-thread loop (`_run`):
1. Open a TLS connection to `irc.chat.twitch.tv:6697` via `socket_factory()`.
2. Send `CAP REQ :twitch.tv/tags twitch.tv/commands`, `PASS SCHMOOPIIE`,
   `NICK justinfan<random 5-digit number>`, `JOIN #<channel>`.
3. Push `{"type": "status", "state": "connected"}` onto the queue.
4. Loop: `recv()` bytes, buffer, split on `\r\n` into complete lines, parse each line
   (see Message parsing below):
   - `PING` → reply `PONG :tmi.twitch.tv` directly on the socket, not surfaced to the queue.
   - Everything else → push the parsed event dict onto the queue.
5. On any socket error/EOF (and the loop isn't cancelled): push
   `{"type": "status", "state": "disconnected"}`, sleep via `sleep_fn(backoff)`, increase backoff
   (1s → 2s → 4s → 8s → capped at 30s), go back to step 1. Backoff resets to 1s once a connection
   has stayed open for >30s.
6. Loop exits only when `cancel_event.is_set()` (set by `disconnect()`).

### Message parsing (`_parse_line`, module-level function)

Splits a raw IRC line (`@tags :prefix COMMAND params :trailing`) into `(tags, prefix, command,
params, trailing)`, then maps to one of:

- `PRIVMSG` → `{"type": "message", "username": <from prefix>, "display_name": <tags["display-name"]>,
  "text": <trailing>, "timestamp": <tags["tmi-sent-ts"], ms epoch, int, falls back to
  time.time()*1000 if absent>}`
- `USERNOTICE` with `tags["msg-id"] == "raid"` → `{"type": "raid", "from_channel":
  <tags["msg-param-login"]>, "display_name": <tags["msg-param-displayName"]>, "viewer_count":
  <int(tags["msg-param-viewerCount"])>, "timestamp": <tmi-sent-ts, same fallback>}`
- Anything else (including other `USERNOTICE` subtypes, `JOIN`, `NOTICE`, etc.) →
  `{"type": "raw", "line": <original line, unparsed>}`

`PING` is intercepted by the caller (`_run`) before reaching `_parse_line`, since it needs a direct
socket reply, not a queue event.

`_parse_line` is a standalone function (not a method) so it's testable with zero setup — no socket,
no thread, no `ChatClient` instance required.

## Data flow

```
consumer.connect()
  -> spawns background thread
     -> TLS connect, CAP/PASS/NICK/JOIN
     -> queue: {"type": "status", "state": "connected"}
     -> loop: recv -> split lines -> _parse_line each
          PING -> reply PONG directly (not queued)
          PRIVMSG -> queue: {"type": "message", ...}
          USERNOTICE msg-id=raid -> queue: {"type": "raid", ...}
          other -> queue: {"type": "raw", "line": ...}
        on socket error -> queue: {"type": "status", "state": "disconnected"}
                         -> backoff sleep -> reconnect (repeat until cancelled)
consumer.read_messages()  # generator, drains the queue
consumer.disconnect()  # cancel_event.set(), close socket, join thread
```

## Error handling

- Transient socket errors (connection reset, timeout, EOF) are treated as recoverable: caught in
  `_run`, trigger the backoff-reconnect sequence, never raised to the consumer.
- `disconnect()` is idempotent — calling it when not connected, or twice, does not raise.
- Malformed IRC lines (fail to parse cleanly) fall through to the `"raw"` passthrough case rather
  than raising, so one weird line from Twitch can't kill the read loop.
- No maximum retry count — the client keeps trying to reconnect until explicitly told to stop, since
  a chat view should survive a network blip transparently rather than silently going dead.

## Testing

`tests/twitch/test_irc.py` (rewritten from the current NotImplementedError-only tests):

- **`_parse_line` unit tests** (no threading, no sockets): realistic raw lines in, asserts the
  correct dict out — one case each for `PRIVMSG`, `USERNOTICE`/raid, an unrelated `USERNOTICE`
  subtype (→ raw), `JOIN` (→ raw), and a line missing expected tags (falls back sanely, does not
  raise).
- **`ChatClient` threaded-loop tests** via an injected fake socket (`socket_factory` returns a fake
  object queued with canned `recv()` byte chunks, and recording everything passed to `sendall()`):
  - connecting sends `PASS`/`NICK`/`JOIN` in order.
  - a `PING` line results in `PONG` being sent and is not yielded from `read_messages()`.
  - a `PRIVMSG` line results in the right `"message"` event from `read_messages()`.
  - a `USERNOTICE`/raid line results in the right `"raid"` event.
  - simulating a `recv()` raising `ConnectionError` mid-stream results in a `"disconnected"` status
    event, followed (once the fake socket "reconnects") by a `"connected"` status event and chat
    resuming — with `sleep_fn` injected as a no-op/recording fake so the test doesn't block in real
    time and can assert the backoff sequence.
  - `disconnect()` stops the background thread (asserted via `Thread.join()` completing promptly)
    and is safe to call twice.
- `tests/test_architecture.py`: no changes needed — `irc.py` still imports no `xbmc*` modules.
- No test hits Twitch's real IRC server.

## Out of scope for this task

- `ChatOverlay`/`ChatWindow` — still stubs; a follow-up spec wires them to `ChatClient` and adds the
  chat skin XML (see `TODO.md`'s picture-in-picture entry for the intended small-video-box +
  chat-list layout).
- Raid-*following* behavior (auto-switching playback, prompting the user) — this task only makes
  `"raid"` events available on the queue; acting on them is a separate follow-up.
- Authenticated chat connections (OAuth token instead of anonymous) — not needed for a read-only
  viewer; revisit only if a future feature requires posting or higher rate limits.
- Emote/badge rendering — chat text is delivered as plain text; any emote-image lookup is a Home/
  Discover-style follow-up, not part of the client.
