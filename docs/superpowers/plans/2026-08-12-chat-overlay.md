# Chat Overlay Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wire the real `ChatClient` (from `lib/twitch/irc.py`) to a visible right-side chat overlay
that appears automatically over fullscreen video playback and closes when the stream stops.

**Architecture:** `player.play_stream(url, channel)` starts playback as before, then — if
`chat_display_mode` includes `"overlay"` — constructs a `ChatOverlay` (a `WindowXMLDialog`) and
shows it. `ChatOverlay.onInit` creates its own `ChatClient(channel)`, connects it, and runs a
background thread pumping `read_messages()` into a capped, rebuilt list control (same
`reset()`+`addItems()` pattern already used in `home.py`/`discover.py`). A small `xbmc.Player`
subclass, `_ChatAwarePlayer`, is kept alive at module level and closes the overlay + disconnects
its client when the stream stops or ends.

**Tech Stack:** Same as the rest of this codebase — Python stdlib (`threading`) plus `xbmcgui`.
No new dependencies.

## Global Constraints

- `player.play_stream`'s signature changes from `play_stream(url)` to `play_stream(url, channel)` —
  both existing call sites (`home.py:330`, `discover.py:284`) and both existing tests in
  `tests/windows/test_player.py` must be updated to match.
- Overlay only — no standalone chat window, no toggle/keymap, no PiP windowed-video layout. Those
  stay out of scope per the design spec.
- Only `"message"` events from `ChatClient.read_messages()` are rendered; `"status"`/`"raid"`
  events are ignored by the overlay.
- The overlay's message list caps at 50 items, dropping the oldest.
- All new constructor dependencies (`settings`, `chat_overlay_cls`, `chat_client_cls`) are
  injectable with real defaults, matching this codebase's existing DI convention
  (`addon=None` params, `monitor_cls` in `main.run`).
- No test hits Twitch's real IRC server, a real socket, or Kodi's real player/window manager.

Spec: `docs/superpowers/specs/2026-08-12-chat-overlay-design.md`

---

### Task 1: `play_stream` signature change — add `channel` parameter

**Files:**
- Modify: `lib/windows/player.py`
- Modify: `lib/windows/home.py:330`
- Modify: `lib/windows/discover.py:284`
- Modify: `tests/windows/test_player.py`

**Interfaces:**
- Produces: `play_stream(url, channel) -> bool` — same return-value contract as before
  (`True`/`False` for playback started/declined); `channel` is accepted but not yet used by
  anything in this task (later tasks add the chat-overlay behavior that consumes it).

- [ ] **Step 1: Write the failing tests**

Update the two existing tests in `tests/windows/test_player.py` to call `play_stream` with a
channel argument:

```python
def test_play_stream_returns_true_and_plays_when_inputstream_available():
    with patch("lib.windows.player.Helper") as mock_helper_cls, patch(
        "lib.windows.player.xbmc.Player"
    ) as mock_player_cls:
        mock_helper_cls.return_value.check_inputstream.return_value = True
        mock_helper_cls.return_value.inputstream_addon = "inputstream.adaptive"

        result = player.play_stream("https://example.invalid/stream.m3u8", "somechannel")

    assert result is True
    mock_helper_cls.assert_called_once_with("hls")
    mock_player_cls.return_value.play.assert_called_once()
    call_args = mock_player_cls.return_value.play.call_args
    assert call_args[0][0] == "https://example.invalid/stream.m3u8"
    list_item = call_args[0][1]
    assert list_item.getProperty("inputstream") == "inputstream.adaptive"
    assert list_item.getProperty("inputstream.adaptive.manifest_type") == "hls"
    assert list_item.getMimeType() == "application/x-mpegURL"
    assert list_item.getContentLookup() is False
    assert list_item.getPath() == "https://example.invalid/stream.m3u8"


def test_play_stream_returns_false_when_inputstream_declined():
    with patch("lib.windows.player.Helper") as mock_helper_cls, patch(
        "lib.windows.player.xbmc.Player"
    ) as mock_player_cls:
        mock_helper_cls.return_value.check_inputstream.return_value = False

        result = player.play_stream("https://example.invalid/stream.m3u8", "somechannel")

    assert result is False
    mock_player_cls.return_value.play.assert_not_called()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/windows/test_player.py -v`
Expected: FAIL with `TypeError: play_stream() takes 1 positional argument but 2 were given`.

- [ ] **Step 3: Update `play_stream`'s signature**

In `lib/windows/player.py`, change:

```python
def play_stream(url):
```

to:

```python
def play_stream(url, channel):
```

Don't use `channel` for anything yet in this task — it's a required parameter now, but the chat
overlay behavior that consumes it is added in Task 4.

- [ ] **Step 4: Update the two call sites**

In `lib/windows/home.py`, line 330, change:

```python
        if player.play_stream(url):
```

to:

```python
        if player.play_stream(url, broadcaster_login):
```

In `lib/windows/discover.py`, line 284, change:

```python
        if player.play_stream(url):
```

to:

```python
        if player.play_stream(url, broadcaster_login):
```

(`broadcaster_login` is already a local variable at both call sites — read a few lines earlier in
each `_play_channel` method — so this is a one-line change at each, not a new lookup.)

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/windows/test_player.py tests/windows/test_home_window.py tests/windows/test_discover_window.py -v`
Expected: all pass. (The Home/Discover click-to-play tests mock `player.play_stream` wholesale and
don't assert on its call arguments, so they aren't affected by the signature change — but run them
anyway to confirm nothing else broke.)

- [ ] **Step 6: Commit**

```bash
git add lib/windows/player.py lib/windows/home.py lib/windows/discover.py tests/windows/test_player.py
git commit -m "feat: add channel parameter to play_stream for upcoming chat overlay"
```

---

### Task 2: `ChatOverlay` — connects, pumps messages, caps the list

**Files:**
- Modify: `lib/windows/chat_overlay.py` (replaces the `pass` stub)
- Test: `tests/windows/test_chat_overlay.py` (new)

**Interfaces:**
- Consumes: `lib.twitch.irc.ChatClient`'s interface (`__init__(channel)`, `connect()`,
  `read_messages()` generator, `disconnect()`) — not the real class in tests, an injected fake with
  the same shape.
- Produces:
  - `ChatOverlay(xml_filename, script_path, default_skin, default_res, channel, chat_client_cls=None)`
    — `channel` is keyword-only and required (matches `LoginWindow`/`DiscoverWindow`'s existing
    `closed_event` convention of accepting extra state as keyword args after `*args`).
  - `ChatOverlay.MESSAGE_LIST_ID = 101`, `ChatOverlay._MAX_MESSAGES = 50` (class attributes, used by
    Task 3's skin XML and Task 5's manifest test).
  - `ChatOverlay.close()` — idempotent, disconnects the client and stops the pump thread.

- [ ] **Step 1: Write the failing tests**

Create `tests/windows/test_chat_overlay.py`:

```python
from lib.windows.chat_overlay import ChatOverlay


class FakeChatClient:
    instances = []

    def __init__(self, channel):
        self.channel = channel
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


def _message_event(username, text, index=0):
    return {
        "type": "message",
        "username": username,
        "display_name": username.capitalize(),
        "text": text,
        "timestamp": index,
    }


def test_oninit_constructs_client_lazily_and_connects_it():
    FakeChatClient.instances.clear()
    win = ChatOverlay(
        "script-twitch-center-chat-overlay.xml",
        "/tmp",
        "Default",
        "1080i",
        channel="somechannel",
        chat_client_cls=FakeChatClient,
    )
    # The client isn't constructed until onInit runs (matches every other
    # window in this codebase - construction happens in onInit, not __init__).
    assert FakeChatClient.instances == []

    win.onInit()
    win._thread.join(timeout=1)

    assert len(FakeChatClient.instances) == 1
    client = FakeChatClient.instances[0]
    assert client.channel == "somechannel"
    assert client.connected is True


def test_pump_renders_messages_and_ignores_status_and_raid_events():
    FakeChatClient.instances.clear()

    class ClientWithMessages(FakeChatClient):
        def __init__(self, channel):
            super().__init__(channel)
            self._events = [
                _message_event("bob", "hello", 1),
                {"type": "status", "state": "connected"},
                _message_event("carol", "hi there", 2),
                {"type": "raid", "from_channel": "x", "display_name": "X", "viewer_count": 5, "timestamp": 3},
            ]

    win = ChatOverlay(
        "script-twitch-center-chat-overlay.xml",
        "/tmp",
        "Default",
        "1080i",
        channel="somechannel",
        chat_client_cls=ClientWithMessages,
    )
    win.onInit()
    win._thread.join(timeout=1)

    control = win.getControl(ChatOverlay.MESSAGE_LIST_ID)
    assert control.size() == 2
    assert control._items[0].getLabel() == "Bob"
    assert control._items[0].getLabel2() == "hello"
    assert control._items[1].getLabel() == "Carol"
    assert control._items[1].getLabel2() == "hi there"


def test_pump_caps_message_list_at_fifty_dropping_oldest():
    FakeChatClient.instances.clear()

    class ClientWithManyMessages(FakeChatClient):
        def __init__(self, channel):
            super().__init__(channel)
            self._events = [_message_event("user", "msg%d" % i, i) for i in range(60)]

    win = ChatOverlay(
        "script-twitch-center-chat-overlay.xml",
        "/tmp",
        "Default",
        "1080i",
        channel="somechannel",
        chat_client_cls=ClientWithManyMessages,
    )
    win.onInit()
    win._thread.join(timeout=1)

    control = win.getControl(ChatOverlay.MESSAGE_LIST_ID)
    assert control.size() == 50
    assert control._items[0].getLabel2() == "msg10"
    assert control._items[-1].getLabel2() == "msg59"


def test_close_disconnects_client_and_is_idempotent():
    FakeChatClient.instances.clear()
    win = ChatOverlay(
        "script-twitch-center-chat-overlay.xml",
        "/tmp",
        "Default",
        "1080i",
        channel="somechannel",
        chat_client_cls=FakeChatClient,
    )
    win.onInit()
    win._thread.join(timeout=1)

    win.close()
    win.close()  # must not raise

    client = FakeChatClient.instances[0]
    assert client.disconnected is True
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/windows/test_chat_overlay.py -v`
Expected: FAIL — `ChatOverlay.__init__` currently doesn't accept `channel`/`chat_client_cls`, and
`onInit` is just `pass`.

- [ ] **Step 3: Implement `ChatOverlay`**

Replace the entire contents of `lib/windows/chat_overlay.py`:

```python
"""Non-modal chat overlay shown during playback."""
import threading

import xbmcgui

from lib.twitch.irc import ChatClient


def _build_message_item(event):
    item = xbmcgui.ListItem(event["display_name"])
    item.setLabel2(event["text"])
    return item


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
            control.addItems([_build_message_item(event) for event in self._messages])

    def _safe_control(self, control_id):
        try:
            return self.getControl(control_id)
        except Exception:
            return None

    def close(self):
        self._cancel_event.set()
        if self._client is not None:
            self._client.disconnect()
        super().close()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/windows/test_chat_overlay.py -v`
Expected: all 4 pass.

- [ ] **Step 5: Commit**

```bash
git add lib/windows/chat_overlay.py tests/windows/test_chat_overlay.py
git commit -m "feat: implement ChatOverlay - connects ChatClient and renders messages"
```

---

### Task 3: Chat overlay skin XML

**Files:**
- Create: `resources/skins/Default/1080i/script-twitch-center-chat-overlay.xml`
- Modify: `tests/test_addon_manifest.py`

**Interfaces:**
- Consumes: `ChatOverlay.MESSAGE_LIST_ID` (101) from Task 2.
- Produces: nothing new consumed by later tasks — this is the skin file real Kodi loads by
  filename string (`"script-twitch-center-chat-overlay.xml"`), matching how `HomeWindow`/
  `DiscoverWindow`/`LoginWindow` are already constructed with their skin filenames as a plain
  string in `home.py`/`discover.py`/`login.py`/`main.py`.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_addon_manifest.py`, near the top alongside the other skin path constants:

```python
CHAT_OVERLAY_SKIN_XML = (
    Path(__file__).resolve().parent.parent
    / "resources"
    / "skins"
    / "Default"
    / "1080i"
    / "script-twitch-center-chat-overlay.xml"
)
```

And a new test function, anywhere after the existing skin tests:

```python
def test_chat_overlay_skin_xml_declares_message_list_control_id():
    tree = ET.parse(CHAT_OVERLAY_SKIN_XML)
    root = tree.getroot()
    control_ids = {
        int(control.attrib["id"])
        for control in root.iter("control")
        if "id" in control.attrib
    }
    assert 101 in control_ids
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_addon_manifest.py -v -k chat_overlay`
Expected: FAIL — `FileNotFoundError` (the skin file doesn't exist yet).

- [ ] **Step 3: Create the skin file**

Create `resources/skins/Default/1080i/script-twitch-center-chat-overlay.xml`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<window>
  <controls>
    <control type="list" id="101">
      <description>Chat messages</description>
      <posx>1500</posx>
      <posy>60</posy>
      <width>380</width>
      <height>960</height>
      <itemlayout width="380" height="70">
        <control type="label">
          <posx>10</posx>
          <posy>0</posy>
          <width>360</width>
          <height>24</height>
          <font>font13</font>
          <textcolor>ff9146ff</textcolor>
          <label>$INFO[ListItem.Label]</label>
        </control>
        <control type="label">
          <posx>10</posx>
          <posy>26</posy>
          <width>360</width>
          <height>40</height>
          <font>font12</font>
          <wrapmultiline>true</wrapmultiline>
          <label>$INFO[ListItem.Label2]</label>
        </control>
      </itemlayout>
      <focusedlayout width="380" height="70">
        <control type="label">
          <posx>10</posx>
          <posy>0</posy>
          <width>360</width>
          <height>24</height>
          <font>font13</font>
          <textcolor>ff9146ff</textcolor>
          <label>$INFO[ListItem.Label]</label>
        </control>
        <control type="label">
          <posx>10</posx>
          <posy>26</posy>
          <width>360</width>
          <height>40</height>
          <font>font12</font>
          <wrapmultiline>true</wrapmultiline>
          <label>$INFO[ListItem.Label2]</label>
        </control>
      </focusedlayout>
    </control>
  </controls>
</window>
```

No `<defaultcontrol>` — this window never receives keyboard/remote focus or navigation, per the
design spec (it's a passive display surface only). No background texture, so the video underneath
shows through around the list.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_addon_manifest.py -v -k chat_overlay`
Expected: 1 passed.

- [ ] **Step 5: Commit**

```bash
git add resources/skins/Default/1080i/script-twitch-center-chat-overlay.xml tests/test_addon_manifest.py
git commit -m "feat: add chat overlay skin (right-side message strip)"
```

---

### Task 4: Wire chat overlay creation into `play_stream`

**Files:**
- Modify: `lib/windows/player.py`
- Modify: `tests/windows/test_player.py`

**Interfaces:**
- Consumes: `ChatOverlay` (Task 2, imported as the default `chat_overlay_cls`), `ChatClient` (via
  `ChatOverlay`'s own default), `lib.settings.Settings` (existing, for `chat_display_mode`).
- Produces:
  - `play_stream(url, channel, settings=None, chat_overlay_cls=None, chat_client_cls=None) -> bool`
    — same return contract as Task 1, now with chat-overlay side effects when applicable.
  - `_ChatAwarePlayer(overlay, chat_client)` — module-level class in `player.py`, with
    `onPlaybackStopped`/`onPlaybackEnded` methods that close the overlay and disconnect the client.

- [ ] **Step 1: Write the failing tests, and guard the two pre-existing tests against real chat side effects**

Once this task's `play_stream` change lands, calling it with no `settings`/`chat_overlay_cls`
resolves to the *real* `Settings()` and `ChatOverlay` — and `Settings().chat_display_mode` defaults
to `"both"` when unset (`lib/settings.py`'s `DEFAULT_CHAT_DISPLAY_MODE`), which would make the two
pre-existing tests from Task 1 (`test_play_stream_returns_true_and_plays_when_inputstream_available`,
`test_play_stream_returns_false_when_inputstream_declined`) construct a *real* `ChatOverlay`, which
constructs a *real* `ChatClient` in `onInit` and opens a real network socket — inside a unit test.
Fix this now, in this task, by passing an explicit `settings=FakeSettings("standalone")` to both of
those pre-existing tests' `play_stream(...)` calls, so they keep exercising only the pre-existing
playback path with zero chat side effects, matching their original intent from Task 1 (which
predates chat entirely). Update both calls:

```python
        result = player.play_stream(
            "https://example.invalid/stream.m3u8", "somechannel", settings=FakeSettings("standalone")
        )
```

(one call per test — the rest of each test body is unchanged). `FakeSettings` is defined below in
this same task, so define it before these two edited tests appear in the file, or anywhere else in
the file above their use — placement within the file doesn't matter for pytest, only that the name
is defined at module level before test collection runs, which it will be either way.

Add to `tests/windows/test_player.py`:

```python
from lib.windows import player


class FakeSettings:
    def __init__(self, chat_display_mode):
        self.chat_display_mode = chat_display_mode


class FakeChatClient:
    instances = []

    def __init__(self, channel):
        self.channel = channel
        self.disconnected = False
        FakeChatClient.instances.append(self)

    def disconnect(self):
        self.disconnected = True


class FakeChatOverlay:
    instances = []

    def __init__(self, xml_filename, script_path, default_skin, default_res, channel=None, chat_client_cls=None):
        self.channel = channel
        self._client = (chat_client_cls or FakeChatClient)(channel)
        self.shown = False
        self.closed = False
        FakeChatOverlay.instances.append(self)

    def show(self):
        self.shown = True

    def close(self):
        self.closed = True


def _patch_playable():
    return patch("lib.windows.player.Helper"), patch("lib.windows.player.xbmc.Player")


def test_play_stream_creates_and_shows_overlay_when_mode_is_overlay():
    FakeChatOverlay.instances.clear()
    with patch("lib.windows.player.Helper") as mock_helper_cls, patch(
        "lib.windows.player.xbmc.Player"
    ) as mock_player_cls:
        mock_helper_cls.return_value.check_inputstream.return_value = True
        mock_helper_cls.return_value.inputstream_addon = "inputstream.adaptive"

        result = player.play_stream(
            "https://example.invalid/stream.m3u8",
            "somechannel",
            settings=FakeSettings("overlay"),
            chat_overlay_cls=FakeChatOverlay,
            chat_client_cls=FakeChatClient,
        )

    assert result is True
    assert len(FakeChatOverlay.instances) == 1
    overlay = FakeChatOverlay.instances[0]
    assert overlay.channel == "somechannel"
    assert overlay.shown is True


def test_play_stream_creates_overlay_when_mode_is_both():
    FakeChatOverlay.instances.clear()
    with patch("lib.windows.player.Helper") as mock_helper_cls, patch(
        "lib.windows.player.xbmc.Player"
    ) as mock_player_cls:
        mock_helper_cls.return_value.check_inputstream.return_value = True
        mock_helper_cls.return_value.inputstream_addon = "inputstream.adaptive"

        player.play_stream(
            "https://example.invalid/stream.m3u8",
            "somechannel",
            settings=FakeSettings("both"),
            chat_overlay_cls=FakeChatOverlay,
            chat_client_cls=FakeChatClient,
        )

    assert len(FakeChatOverlay.instances) == 1


def test_play_stream_skips_overlay_when_mode_is_standalone():
    FakeChatOverlay.instances.clear()
    with patch("lib.windows.player.Helper") as mock_helper_cls, patch(
        "lib.windows.player.xbmc.Player"
    ) as mock_player_cls:
        mock_helper_cls.return_value.check_inputstream.return_value = True
        mock_helper_cls.return_value.inputstream_addon = "inputstream.adaptive"

        player.play_stream(
            "https://example.invalid/stream.m3u8",
            "somechannel",
            settings=FakeSettings("standalone"),
            chat_overlay_cls=FakeChatOverlay,
            chat_client_cls=FakeChatClient,
        )

    assert len(FakeChatOverlay.instances) == 0


def test_play_stream_skips_overlay_when_inputstream_declined():
    FakeChatOverlay.instances.clear()
    with patch("lib.windows.player.Helper") as mock_helper_cls, patch(
        "lib.windows.player.xbmc.Player"
    ) as mock_player_cls:
        mock_helper_cls.return_value.check_inputstream.return_value = False

        result = player.play_stream(
            "https://example.invalid/stream.m3u8",
            "somechannel",
            settings=FakeSettings("overlay"),
            chat_overlay_cls=FakeChatOverlay,
            chat_client_cls=FakeChatClient,
        )

    assert result is False
    assert len(FakeChatOverlay.instances) == 0


def test_chat_aware_player_teardown_closes_overlay_and_disconnects_client_on_stop():
    FakeChatOverlay.instances.clear()
    overlay = FakeChatOverlay(
        "x.xml", "/tmp", "Default", "1080i", channel="c", chat_client_cls=FakeChatClient
    )
    watcher = player._ChatAwarePlayer(overlay, overlay._client)

    watcher.onPlaybackStopped()

    assert overlay.closed is True
    assert overlay._client.disconnected is True


def test_chat_aware_player_teardown_closes_overlay_and_disconnects_client_on_end():
    FakeChatOverlay.instances.clear()
    overlay = FakeChatOverlay(
        "x.xml", "/tmp", "Default", "1080i", channel="c", chat_client_cls=FakeChatClient
    )
    watcher = player._ChatAwarePlayer(overlay, overlay._client)

    watcher.onPlaybackEnded()

    assert overlay.closed is True
    assert overlay._client.disconnected is True
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/windows/test_player.py -v -k "overlay or chat_aware"`
Expected: FAIL — `play_stream` doesn't accept `settings`/`chat_overlay_cls`/`chat_client_cls` yet,
and `player._ChatAwarePlayer` doesn't exist.

- [ ] **Step 3: Implement the wiring**

In `lib/windows/player.py`, add the imports and the new class, and extend `play_stream`:

```python
"""Launches Kodi's native player for a resolved Twitch stream URL."""
import xbmc
import xbmcaddon
import xbmcgui
from inputstreamhelper import Helper

from lib.settings import Settings
from lib.windows.chat_overlay import ChatOverlay

_current_chat_watcher = None


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


def play_stream(url, channel, settings=None, chat_overlay_cls=None, chat_client_cls=None):
    """Hand the resolved HLS URL to Kodi's player via inputstream.adaptive,
    which handles proper adaptive-bitrate switching for live multi-quality
    HLS (unlike Kodi's native demuxer playing the URL directly). Returns
    True if playback was started, False if inputstream.adaptive isn't
    available and the user declined installing it (Helper.check_inputstream
    handles that install-prompt UI itself).

    If playback started and chat_display_mode includes "overlay", also
    creates and shows a ChatOverlay for `channel`, and keeps a
    _ChatAwarePlayer alive at module level so its onPlaybackStopped/
    onPlaybackEnded callbacks close the overlay and disconnect its chat
    client when this stream ends - a locally-scoped instance would be
    garbage-collected and stop receiving Kodi's callbacks."""
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
        overlay_cls = chat_overlay_cls or ChatOverlay
        overlay = overlay_cls(
            "script-twitch-center-chat-overlay.xml",
            xbmcaddon.Addon().getAddonInfo("path"),
            "Default",
            "1080i",
            channel=channel,
            chat_client_cls=chat_client_cls,
        )
        overlay.show()
        _current_chat_watcher = _ChatAwarePlayer(overlay, overlay._client)

    return True
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/windows/test_player.py -v`
Expected: all pass, including the two pre-existing tests from Task 1 (now passing
`settings=FakeSettings("standalone")` per Step 1 above, so they exercise only the playback path
with no chat side effects).

- [ ] **Step 5: Commit**

```bash
git add lib/windows/player.py tests/windows/test_player.py
git commit -m "feat: wire ChatOverlay creation into play_stream based on chat_display_mode"
```

---

### Task 5: Full-suite verification

**Files:**
- None modified — verification only.

**Interfaces:**
- Consumes: everything from Tasks 1-4.
- Produces: nothing new; confirms the finished chat overlay doesn't break any existing test.

- [ ] **Step 1: Run the full test suite**

Run: `python -m pytest tests/ -v`
Expected: all tests pass, zero failures, zero errors.

- [ ] **Step 2: Run the architecture boundary check specifically**

Run: `python -m pytest tests/test_architecture.py -v`
Expected: passes — `lib/twitch/irc.py` is untouched by this plan, and `lib/windows/chat_overlay.py`/
`lib/windows/player.py` were never subject to that constraint (only `lib/twitch/*` is).

- [ ] **Step 3: Manually verify no leftover stub behavior**

Run: `grep -n "pass$" lib/windows/chat_overlay.py`
Expected: no output, or only output from lines that are legitimately empty method bodies elsewhere
(there shouldn't be any left — `onInit` now has real content).

- [ ] **Step 4: Commit (only if Steps 1-3 required any fixes; otherwise skip)**

```bash
git add -A
git commit -m "test: verify chat overlay against full suite"
```

## Out of scope (per the spec, not part of this plan)

- `lib/windows/chat_window.py` (standalone full-screen chat) stays a stub.
- The PiP-style windowed-video + chat-list layout from `TODO.md`.
- Any hide/show toggle or keymap for the overlay.
- Rendering `"raid"` events or any raid-following behavior.
- Emote/badge rendering.
