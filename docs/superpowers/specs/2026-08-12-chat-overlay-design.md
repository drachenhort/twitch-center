# Chat Overlay: Design

Date: 2026-08-12

## What this is

Wires the real `ChatClient` (built in `docs/superpowers/specs/2026-08-12-irc-chat-client-design.md`)
to a visible chat window for the first time: when a live stream starts playing, a chat overlay
automatically appears on top of the fullscreen video, showing incoming messages as they arrive.

This replaces `lib/windows/chat_overlay.py`'s `pass` stub with a real implementation. It does
**not** touch `lib/windows/chat_window.py` (the standalone full-screen chat view stays a stub —
separate follow-up) and does not build the picture-in-picture windowed-video layout from `TODO.md`
— both are explicitly deferred, per the brainstorming session's scope decisions below.

## Scope decisions (from brainstorming)

- **Playback stays fullscreen**, unchanged from `docs/superpowers/specs/2026-08-11-stream-playback-design.md`.
  The PiP-style small-video-box + chat-list layout from `TODO.md` needs a `<control
  type="videowindow">`-based custom window instead of `xbmc.Player().play()`'s native fullscreen
  playback — a much larger change, deferred to a separate design.
- **Overlay only** — `chat_display_mode`'s `"standalone"` value (full-screen chat, no video) is not
  built this round; `lib/windows/chat_window.py` stays a stub.
- **Shows automatically** when playback starts, if `chat_display_mode` includes `"overlay"` (i.e.
  `"overlay"` or `"both"`). No manual trigger.
- **Read-only, no toggle** — the overlay has no hide/show hotkey and no keymap file. It appears when
  playback starts and closes when playback stops. (A toggle key was discussed and dropped: "we just
  want to read the chat, no need to interact, yet.")
- **Right-side vertical strip** layout: a scrolling list along the right edge, transparent background
  so the video shows through around it.
- **Lifecycle tied to playback via an `xbmc.Player` subclass** watching for playback stop/end, not to
  a window's Back-button handler — covers the case where a stream ends on its own (goes offline)
  without requiring the user to press Back.
- Only `"message"` events are rendered. `"status"`/`"raid"` events (already available on
  `ChatClient`'s queue) are ignored by this overlay — not in scope.

## Components

### `lib/windows/player.py` (extended)

**Interface change** (breaking, both call sites updated — see below): `play_stream(url)` becomes
`play_stream(url, channel)`. `channel` is the broadcaster's login/slug (already available at both
existing call sites as `broadcaster_login`), needed to construct a `ChatClient(channel)`.

```python
def play_stream(url, channel, settings=None, chat_overlay_cls=None, chat_client_cls=None):
    """Unchanged: check inputstream.adaptive, build the ListItem, start playback via
    xbmc.Player().play(url, list_item). Returns False immediately if the user
    declined the inputstream install prompt, same as before - no chat overlay
    is created in that case, since there's nothing playing to pair it with.

    New: if playback started and settings.chat_display_mode includes "overlay",
    creates a ChatOverlay for `channel`, shows it, and registers a _ChatAwarePlayer
    (see below) so the overlay/client are torn down when this specific
    stream stops. Returns True either way once playback itself has started -
    the chat overlay's own success/failure doesn't affect the return value,
    since a chat problem must never look like a playback failure to the caller."""
```

`settings`/`chat_overlay_cls`/`chat_client_cls` are constructor-injectable (defaulting to
`lib.settings.Settings()`, `ChatOverlay`, and `ChatClient` respectively) — same dependency-injection
convention used throughout this codebase (`addon=None` params, `monitor_cls` in `main.run`) —
purely so tests never need a real Kodi player, window, or socket.

**New: `_ChatAwarePlayer(xbmc.Player)`** — a small subclass, instantiated fresh per `play_stream`
call (not a long-lived singleton, since each stream gets its own overlay/client pairing):

```python
class _ChatAwarePlayer(xbmc.Player):
    def __init__(self, overlay, chat_client):
        super().__init__()
        self._overlay = overlay
        self._chat_client = chat_client

    def onPlaybackStopped(self):
        self._teardown()

    def onPlaybackEnded(self):
        self._teardown()

    def _teardown(self):
        self._chat_client.disconnect()
        self._overlay.close()
```

`play_stream` keeps a module-level reference to the most recently created `_ChatAwarePlayer`
instance for the lifetime of that stream (Kodi's `xbmc.Player` callback subclasses must stay alive
— a locally-scoped instance would be garbage-collected and stop receiving callbacks, the same
class of bug the IRC client's design spec flagged for `WindowXML` instances). The reference is
replaced (not appended-to) on each new `play_stream` call, since only one stream plays at a time in
this addon's design — a new call implicitly means the previous stream, if any, has already ended.

### `lib/windows/chat_overlay.py` (replaces the stub)

```python
class ChatOverlay(xbmcgui.WindowXMLDialog):
    MESSAGE_LIST_ID = 101
    _MAX_MESSAGES = 50

    def __init__(self, *args, channel, chat_client_cls=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.channel = channel
        self._chat_client_cls = chat_client_cls or ChatClient
        self._client = None
        self._messages = []
        self._cancel_event = threading.Event()
        self._thread = None

    def onInit(self):
        self._client = self._chat_client_cls(self.channel)
        self._client.connect()
        self._thread = threading.Thread(target=self._pump_messages, daemon=True)
        self._thread.start()

    def _pump_messages(self):
        for event in self._client.read_messages():
            if self._cancel_event.is_set():
                break
            if event["type"] != "message":
                continue
            self._messages.append(event)
            del self._messages[:-self._MAX_MESSAGES]
            self._render()

    def _render(self):
        control = self._safe_control(self.MESSAGE_LIST_ID)
        if control:
            control.reset()
            control.addItems([_build_message_item(m) for m in self._messages])

    def close(self):
        self._cancel_event.set()
        if self._client is not None:
            self._client.disconnect()
        super().close()
```

`_build_message_item` (module-level, mirrors `_build_list_item`/`_build_stream_item` in
`home.py`/`discover.py`): builds an `xbmcgui.ListItem` with the display name as the label and the
message text as label2, matching this codebase's existing two-line list-item convention.

`_safe_control` follows the same try/`getControl`/except-`None` pattern already duplicated across
`HomeWindow`/`DiscoverWindow` — not extracted to a shared base class in this task (YAGNI; a third
copy doesn't yet justify a refactor, and the existing two copies weren't touched by the IRC client
task either).

`close()` is idempotent by construction: `self._cancel_event.set()` and `self._client.disconnect()`
are both already-idempotent per the IRC client's own design (`disconnect()` is safe to call twice,
even before `connect()`), so `_ChatAwarePlayer` calling `close()` and Kodi later calling it again
(e.g. on script teardown) can't raise.

### `resources/skins/Default/1080i/script-twitch-center-chat-overlay.xml` (new)

A `WindowXMLDialog` layout: no background texture (transparent — video shows through), one list
control (`id="101"`) positioned along the right edge (e.g. `posx=1500 posy=60 width=380
height=960`), vertical orientation, item layout with two stacked labels (display name, styled with
a distinct color; message text below it, wrapping). No `defaultcontrol` — this window never
receives keyboard/remote focus or navigation, it's purely a passive display surface.

### `lib/windows/home.py` / `lib/windows/discover.py` (extended)

Both `_play_channel` methods' single call site changes from `player.play_stream(url)` to
`player.play_stream(url, broadcaster_login)` — `broadcaster_login` is already a local variable at
both call sites (read from the selected list item's property before this call), so this is a
one-line change at each of the two existing call sites, not a new lookup.

## Data flow

There is exactly one `ChatClient` per stream, owned by the `ChatOverlay` itself (constructed inside
`onInit`) — `play_stream` never constructs its own. Window construction is synchronous and
`onInit` runs as part of `overlay.show()` returning (matching how every other window in this
codebase already behaves), so by the time `play_stream` needs to hand a client to
`_ChatAwarePlayer`, `overlay._client` already exists:

```
User selects a live channel (Home or Discover)
  -> _play_channel(broadcaster_login)
  -> stream.resolve_stream_url(...) -> url
  -> player.play_stream(url, broadcaster_login)
       -> inputstream.adaptive check -> xbmc.Player().play(url, list_item)
       -> if chat_display_mode includes "overlay":
            overlay_cls = chat_overlay_cls or ChatOverlay
            overlay = overlay_cls(..., channel=broadcaster_login, chat_client_cls=chat_client_cls)
            overlay.show()  # -> onInit() creates self._client = ChatClient(channel),
                             #    calls self._client.connect(), starts the pump thread
            _ChatAwarePlayer(overlay, overlay._client)  # kept alive at module level -
                                                          # see below
       -> return True (playback started; chat setup failures don't affect this)

Background thread inside ChatOverlay (started by onInit, runs for the overlay's lifetime):
  for event in self._client.read_messages():
       "message" -> append (capped at 50) -> rebuild list control
       anything else -> ignored

Stream stops/ends (user backs out, or the streamer goes offline)
  -> _ChatAwarePlayer.onPlaybackStopped/onPlaybackEnded
  -> overlay._client.disconnect(); overlay.close()
```

## Error handling

- `ChatClient` fails to connect (channel has chat disabled, network blip): overlay stays visibly
  empty (no error message) — matches the scope decision that this is a low-stakes, secondary
  feature; a chat failure must never look like or cause a playback failure.
- Any exception inside `_pump_messages` (should be rare — `ChatClient.read_messages()` itself
  already never raises, per its own design, but this is defensive): caught, logged via `xbmc.log`,
  thread exits cleanly rather than crashing or leaving the overlay in a half-updated state.
- `player.play_stream` returning `False` (inputstream declined): no `ChatOverlay` is created at
  all — nothing to tear down.
- `chat_display_mode` is `"standalone"` only: `play_stream` skips overlay creation entirely, no
  wasted `ChatClient` connection.

## Testing

- `lib/windows/chat_overlay.py`: `ChatOverlay` tested with an injected fake `chat_client_cls` (a
  test double whose `connect()` is a no-op and whose `read_messages()` is a canned generator, same
  style as this codebase's existing `FakeSocket` pattern) — asserts the message list control ends
  up populated with the right display names/text, caps at 50 items (feed 60, assert the oldest 10
  are gone), and ignores `"status"`/`"raid"` events entirely (feed a mix, assert only `"message"`
  events appear in the list).
- `lib/windows/player.py`: `play_stream` tested with injected fake `chat_overlay_cls`/
  `chat_client_cls`/`settings` — asserts the overlay is constructed and shown only when
  `chat_display_mode` includes `"overlay"` (three cases: `"overlay"`, `"both"`, `"standalone"`), and
  that a fake `_ChatAwarePlayer`'s `onPlaybackStopped`/`onPlaybackEnded` (called directly in the
  test, no real Kodi player needed) close the overlay and disconnect its client.
- `lib/windows/home.py` / `lib/windows/discover.py`: existing click-to-play tests updated for the
  new `play_stream(url, channel)` signature (their mocked `player.play_stream` assertions gain the
  channel argument) — no new behavioral tests needed here, since chat is entirely `player.py`'s
  concern per this design.
- No test hits Twitch's real IRC server or Kodi's real player/window manager.

## Out of scope for this task

- `lib/windows/chat_window.py` (standalone full-screen chat, `chat_display_mode: "standalone"`) —
  stays a stub, separate follow-up.
- The PiP-style windowed-video + chat-list layout from `TODO.md` — needs a `videowindow`-control
  custom skin replacing fullscreen playback entirely; separate, larger design.
- Any hide/show toggle for the overlay, and the keymap-installation machinery that would require —
  explicitly dropped per the brainstorming session.
- Rendering `"raid"` events in the overlay, or any raid-following behavior (auto-switch playback) —
  separate follow-up per `TODO.md`.
- Emote/badge rendering — message text stays plain text.
- Multiple simultaneous chat overlays / multi-stream playback — this addon plays one stream at a
  time by design.
