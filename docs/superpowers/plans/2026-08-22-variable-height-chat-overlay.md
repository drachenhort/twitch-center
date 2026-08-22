# Variable-Height Chat Overlay Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an opt-in, EventSub-only chat overlay renderer (`VariableChatOverlay`) that sizes each
message's on-screen box to its actual wrapped line count, instead of `ChatOverlay`'s fixed 270px-tall
row sized for the worst case (5 lines).

**Architecture:** `VariableChatOverlay` subclasses `ChatOverlay`, reusing its chat-client connection
and pump-thread scaffolding (`__init__`/`onInit`/`_pump_messages`), and overrides only `_render()`
(plus extends `close()`) to build and position raw `xbmcgui.ControlLabel`/`ControlImage` controls by
hand instead of using Kodi's `<list>` control - which cannot vary row height per item (verified live;
see the spec). A new settings toggle, read in `lib/windows/player.py`, selects `VariableChatOverlay`
over `ChatOverlay` only when both it is enabled and the EventSub chat engine is in effect.

**Tech Stack:** Python 3, Kodi `xbmcgui` (`WindowXMLDialog`, `ControlLabel`, `ControlImage`),
`xbmcaddon` settings, pytest with this repo's `tests/kodi_stubs/` fake Kodi modules.

**Spec:** `docs/superpowers/specs/2026-08-22-variable-height-chat-overlay-design.md`

## Global Constraints

- EventSub only: `VariableChatOverlay` must never be selected when `chat_engine` resolves to `irc`
  (including the existing silent EventSub→IRC fallback in `player.py`), matching the spec's Settings
  section.
- Opt-in, default off: new `Settings.chat_overlay_variable_height` defaults to `False`.
- `ChatOverlay` itself must not change behavior - `VariableChatOverlay` is additive. All existing
  `tests/windows/test_chat_overlay.py` tests must keep passing unmodified.
- A message's controls are created once and only ever repositioned or removed, never destroyed and
  recreated while still on screen (carries over the emote-art-reload fix from v0.16.2 - see spec).
- Newest message pinned to the bottom of the 960px column; every visible block repositioned on each
  new message, not just on eviction (per spec's "Data flow" section).

---

### Task 1: Rename the ambiguous `ControlLabel` test stub to `FakeListControl`

**Why:** `tests/kodi_stubs/xbmcgui.py` currently has a class named `ControlLabel` that is actually a
generic fake *list*-control stand-in (used via `WindowXML.getControl()` for `ChatOverlay`'s message
list and reused verbatim in four view test files). Later tasks need a *real* `xbmcgui.ControlLabel`
stub matching Kodi's actual per-control constructor (`x, y, width, height, label, ...`). Freeing the
name requires renaming the existing one first - this is a pure rename, no behavior change.

**Files:**
- Modify: `tests/kodi_stubs/xbmcgui.py`
- Modify: `tests/views/test_discover_view.py:26`
- Modify: `tests/views/test_login_view.py:14`
- Modify: `tests/views/test_search_view.py:12`
- Modify: `tests/views/test_live_streams_view.py:21`

**Interfaces:**
- Produces: `FakeListControl` (same shape as the old `ControlLabel`: `setLabel`/`getLabel`,
  `setText`/`getText`, `addItems`, `reset`, `removeItem`, `size`, `getSelectedItem`, `selectItem`,
  `setVisible`/`isVisible`, `setEnabled`/`isEnabled`), used identically to before.

- [ ] **Step 1: Rename the class in the stub module**

In `tests/kodi_stubs/xbmcgui.py`, rename the class `ControlLabel` (currently at line 69) to
`FakeListControl`. Its body is unchanged - only the class name changes:

```python
class FakeListControl:
    def __init__(self):
        self._label = ""
        self._items = []
        self._visible = True
        self._selected_index = 0

    def setLabel(self, text):
        self._label = text

    def getLabel(self):
        return self._label

    def setText(self, text):
        self._label = text

    def getText(self):
        return self._label

    def addItems(self, items):
        self._items.extend(items)

    def reset(self):
        self._items = []
        self._selected_index = 0

    def removeItem(self, index):
        del self._items[index]

    def size(self):
        return len(self._items)

    def getSelectedItem(self):
        if not self._items:
            return None
        index = min(self._selected_index, len(self._items) - 1)
        return self._items[index]

    def selectItem(self, index):
        self._selected_index = index

    def setVisible(self, visible):
        self._visible = visible

    def isVisible(self):
        return self._visible

    def setEnabled(self, enabled):
        self._enabled = enabled

    def isEnabled(self):
        return getattr(self, "_enabled", True)
```

- [ ] **Step 2: Update `WindowXML.getControl()`'s instantiation**

In the same file, in `class WindowXML`, change:

```python
    def getControl(self, control_id):
        if control_id not in self._controls:
            self._controls[control_id] = ControlLabel()
        return self._controls[control_id]
```

to:

```python
    def getControl(self, control_id):
        if control_id not in self._controls:
            self._controls[control_id] = FakeListControl()
        return self._controls[control_id]
```

- [ ] **Step 3: Update the four view test files' local imports**

In each of `tests/views/test_discover_view.py`, `tests/views/test_login_view.py`,
`tests/views/test_search_view.py`, `tests/views/test_live_streams_view.py`, find:

```python
    def getControl(self, control_id):
        from xbmcgui import ControlLabel

        if control_id not in self._controls:
            self._controls[control_id] = ControlLabel()
        return self._controls[control_id]
```

and change both the import and instantiation to `FakeListControl`:

```python
    def getControl(self, control_id):
        from xbmcgui import FakeListControl

        if control_id not in self._controls:
            self._controls[control_id] = FakeListControl()
        return self._controls[control_id]
```

- [ ] **Step 4: Run the full test suite to confirm the rename is behavior-preserving**

Run: `python -m pytest -q`
Expected: PASS, same pass count as before this task (301 passed).

- [ ] **Step 5: Commit**

```bash
git add tests/kodi_stubs/xbmcgui.py tests/views/test_discover_view.py tests/views/test_login_view.py tests/views/test_search_view.py tests/views/test_live_streams_view.py
git commit -m "test: rename fake list-control stub to FakeListControl

Frees the ControlLabel name for a real per-control stub the variable-height
chat overlay work needs next - this stub was actually standing in for a
list control, not a label."
```

---

### Task 2: Extract `_wrap_message_lines()` in `chat_overlay.py`

**Why:** Both `ChatOverlay` and the new `VariableChatOverlay` need the same wrap-and-truncate logic
(`textwrap.wrap` to `_MESSAGE_WRAP_WIDTH`, capped and ellipsized at `_MAX_MESSAGE_LINES`). Extracting
it as a standalone function avoids duplicating it in the new module. Pure refactor - no behavior
change, verified by the existing test suite.

**Files:**
- Modify: `lib/windows/chat_overlay.py:42-58`
- Test: `tests/windows/test_chat_overlay.py`

**Interfaces:**
- Produces: `_wrap_message_lines(text)` in `lib/windows/chat_overlay.py`, returning a `list[str]` of
  at most `_MAX_MESSAGE_LINES` lines, each at most `_MESSAGE_WRAP_WIDTH` characters, with the last
  line ending in `"..."` if the message was truncated. Used by both `_build_message_item` (unchanged
  behavior) and `lib/windows/variable_chat_overlay.py` (Task 4).

- [ ] **Step 1: Write the failing test**

Add to `tests/windows/test_chat_overlay.py`:

```python
from lib.windows.chat_overlay import _wrap_message_lines


def test_wrap_message_lines_returns_single_line_for_short_text():
    assert _wrap_message_lines("hello") == ["hello"]


def test_wrap_message_lines_truncates_and_ellipsizes_past_five_lines():
    long_text = (
        "which upcoming games are you looking forward to for the rest of this year, "
        "modz? asking because I want to plan my backlog around the big releases"
    )
    lines = _wrap_message_lines(long_text)
    assert len(lines) == 5
    assert lines[-1].endswith("...")
    assert all(len(line) <= 26 for line in lines)
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m pytest tests/windows/test_chat_overlay.py -k wrap_message_lines -v`
Expected: FAIL with `ImportError: cannot import name '_wrap_message_lines'`

- [ ] **Step 3: Extract the function and use it in `_build_message_item`**

In `lib/windows/chat_overlay.py`, replace:

```python
def _build_message_item(event):
    item = xbmcgui.ListItem(event["display_name"])
    lines = textwrap.wrap(event["text"], _MESSAGE_WRAP_WIDTH)
    if len(lines) > _MAX_MESSAGE_LINES:
        lines = lines[:_MAX_MESSAGE_LINES]
        lines[-1] = lines[-1][: max(0, _MESSAGE_WRAP_WIDTH - 3)].rstrip() + "..."
    item.setLabel2("\n".join(lines))
```

with:

```python
def _wrap_message_lines(text):
    lines = textwrap.wrap(text, _MESSAGE_WRAP_WIDTH)
    if len(lines) > _MAX_MESSAGE_LINES:
        lines = lines[:_MAX_MESSAGE_LINES]
        lines[-1] = lines[-1][: max(0, _MESSAGE_WRAP_WIDTH - 3)].rstrip() + "..."
    return lines


def _build_message_item(event):
    item = xbmcgui.ListItem(event["display_name"])
    lines = _wrap_message_lines(event["text"])
    item.setLabel2("\n".join(lines))
```

(the rest of `_build_message_item` - emote art handling - is unchanged)

- [ ] **Step 4: Run the new test to verify it passes**

Run: `python -m pytest tests/windows/test_chat_overlay.py -k wrap_message_lines -v`
Expected: PASS

- [ ] **Step 5: Run the full chat_overlay test file to confirm no regression**

Run: `python -m pytest tests/windows/test_chat_overlay.py -v`
Expected: PASS, all tests (including the pre-existing wrap/truncate tests) still pass.

- [ ] **Step 6: Commit**

```bash
git add lib/windows/chat_overlay.py tests/windows/test_chat_overlay.py
git commit -m "refactor: extract _wrap_message_lines from ChatOverlay

VariableChatOverlay (next) needs the same wrap-and-truncate logic;
extracting it as a standalone function avoids duplicating it."
```

---

### Task 3: Add `ControlLabel`/`ControlImage`/`addControl`/`removeControl` stubs

**Why:** `VariableChatOverlay` (Task 4/5) calls `xbmcgui.ControlLabel(...)`, `xbmcgui.ControlImage(...)`,
`self.addControl(...)`, and `self.removeControl(...)`. The test stub module has no fakes for these yet
(only the just-renamed `FakeListControl`, used for skin-declared `<list>`/`<label>` controls fetched
via `getControl`). This task adds them; the next task's tests are what exercises and verifies them.

**Files:**
- Modify: `tests/kodi_stubs/xbmcgui.py`

**Interfaces:**
- Produces: `xbmcgui.ControlLabel(x, y, width, height, label, font=None, textColor=None)` with
  `.getLabel()`, `.setPosition(x, y)`, `.getPosition() -> (x, y)`.
- Produces: `xbmcgui.ControlImage(x, y, width, height, filename, aspectRatio=0)` with
  `.getFileName()`, `.setPosition(x, y)`, `.getPosition() -> (x, y)`.
- Produces: `WindowXML.addControl(control)` / `WindowXML.removeControl(control)`, tracking a live
  set on `self._added_controls` (a `list`).

- [ ] **Step 1: Add the two new control stub classes**

In `tests/kodi_stubs/xbmcgui.py`, add after the `FakeListControl` class (before `class WindowXML:`):

```python
class ControlLabel:
    def __init__(self, x, y, width, height, label, font=None, textColor=None):
        self._x = x
        self._y = y
        self._width = width
        self._height = height
        self._label = label
        self._font = font
        self._text_color = textColor

    def getLabel(self):
        return self._label

    def setPosition(self, x, y):
        self._x = x
        self._y = y

    def getPosition(self):
        return (self._x, self._y)


class ControlImage:
    def __init__(self, x, y, width, height, filename, aspectRatio=0):
        self._x = x
        self._y = y
        self._width = width
        self._height = height
        self._filename = filename
        self._aspect_ratio = aspectRatio

    def getFileName(self):
        return self._filename

    def setPosition(self, x, y):
        self._x = x
        self._y = y

    def getPosition(self):
        return (self._x, self._y)
```

- [ ] **Step 2: Add `addControl`/`removeControl` to `WindowXML`**

In the same file, in `class WindowXML.__init__`, add a new tracking list:

```python
    def __init__(self, xml_filename, script_path, default_skin="Default", default_res="1080i"):
        self.xml_filename = xml_filename
        self.script_path = script_path
        self._controls = {}
        self._focus_id = None
        self._added_controls = []
```

and add two new methods to `class WindowXML` (near `getControl`):

```python
    def addControl(self, control):
        self._added_controls.append(control)

    def removeControl(self, control):
        self._added_controls.remove(control)
```

- [ ] **Step 3: Run the full test suite to confirm nothing broke**

Run: `python -m pytest -q`
Expected: PASS, same pass count as after Task 1 (these are pure additions, nothing references them
yet).

- [ ] **Step 4: Commit**

```bash
git add tests/kodi_stubs/xbmcgui.py
git commit -m "test: add ControlLabel/ControlImage/addControl/removeControl stubs

Infrastructure for VariableChatOverlay's tests (next task) - matches
Kodi's real xbmcgui.ControlLabel/ControlImage constructor shape."
```

---

### Task 4: `_block_height`/`_build_block` pure functions

**Why:** The height math and per-message control construction are pure functions with no window/
threading involved - testing them standalone (before wiring up the full render loop in Task 5) keeps
each task's test failures narrow and easy to diagnose.

**Files:**
- Create: `lib/windows/variable_chat_overlay.py`
- Test: `tests/windows/test_variable_chat_overlay.py`

**Interfaces:**
- Consumes: `_wrap_message_lines(text)` and `_MAX_EMOTE_SLOTS` from `lib.windows.chat_overlay`
  (Task 2).
- Produces: `_block_height(line_count, has_emotes) -> int`; `_build_block(event) -> {"items": [(control,
  x, rel_y), ...], "height": int}`; `_block_controls(block) -> list`; `_position_block(block, top_y)`.
  Later tasks (5, 7) rely on exactly these names and shapes.

- [ ] **Step 1: Write the failing tests**

Create `tests/windows/test_variable_chat_overlay.py`:

```python
from lib.windows.variable_chat_overlay import (
    _block_controls,
    _block_height,
    _build_block,
)


def test_block_height_one_line_no_emotes():
    assert _block_height(1, has_emotes=False) == 68


def test_block_height_three_lines_no_emotes():
    assert _block_height(3, has_emotes=False) == 152


def test_block_height_five_lines_with_emotes():
    assert _block_height(5, has_emotes=True) == 264


def test_build_block_short_message_has_username_and_message_controls():
    event = {"display_name": "Bob", "text": "hi", "emotes": []}
    block = _build_block(event)
    controls = _block_controls(block)
    assert len(controls) == 2
    username_label, message_label = controls
    assert username_label.getLabel() == "Bob"
    assert message_label.getLabel() == "hi"
    assert block["height"] == _block_height(1, has_emotes=False)


def test_build_block_includes_emote_images_positioned_below_message():
    event = {
        "display_name": "Bob",
        "text": "hi",
        "emotes": [{"id": "1", "text": "Kappa", "url": "https://example.invalid/1.png"}],
    }
    block = _build_block(event)
    controls = _block_controls(block)
    assert len(controls) == 3
    emote_control = controls[2]
    assert emote_control.getFileName() == "https://example.invalid/1.png"
    assert block["height"] == _block_height(1, has_emotes=True)


def test_build_block_skips_emotes_with_no_url():
    event = {
        "display_name": "Bob",
        "text": "hi",
        "emotes": [{"id": "1", "text": "Kappa", "url": None}],
    }
    block = _build_block(event)
    controls = _block_controls(block)
    assert len(controls) == 2
    assert block["height"] == _block_height(1, has_emotes=False)


def test_build_block_truncates_five_line_message_and_sizes_for_it():
    long_text = (
        "which upcoming games are you looking forward to for the rest of this year, "
        "modz? asking because I want to plan my backlog around the big releases"
    )
    event = {"display_name": "Bob", "text": long_text, "emotes": []}
    block = _build_block(event)
    controls = _block_controls(block)
    message_label = controls[1]
    lines = message_label.getLabel().split("\n")
    assert len(lines) == 5
    assert lines[-1].endswith("...")
    assert block["height"] == _block_height(5, has_emotes=False)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/windows/test_variable_chat_overlay.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'lib.windows.variable_chat_overlay'`

- [ ] **Step 3: Create `lib/windows/variable_chat_overlay.py` with the pure functions**

```python
"""Variable-height chat overlay: an opt-in, EventSub-only alternative to ChatOverlay.

ChatOverlay reserves the same fixed-height slot (skin <itemlayout>) for every message, sized
for the worst case (5 wrapped lines) - see chat_overlay.py's _MAX_MESSAGE_LINES and the
v0.16.4/v0.16.5 CHANGELOG entries. VariableChatOverlay instead sizes each message's on-screen
space to its actual wrapped line count, by placing xbmcgui controls directly rather than using
Kodi's <list> control (which can't vary row height per item - see
docs/superpowers/specs/2026-08-22-variable-height-chat-overlay-design.md for why)."""
import xbmcgui

from lib.windows.chat_overlay import _MAX_EMOTE_SLOTS, _wrap_message_lines

# Column geometry, matching resources/skins/Default/1080i/script-twitch-center-chat-overlay.xml's
# <list id="101"> position/size - this overlay doesn't use that control, but keeps the same
# on-screen footprint so it's a drop-in visual replacement.
_COLUMN_X = 1500
_COLUMN_Y = 60
_COLUMN_WIDTH = 380
_COLUMN_HEIGHT = 960

_FONT = "font13"
_USERNAME_HEIGHT = 24
_USERNAME_COLOR = "ff9146ff"
# Offset from a message block's top to its message-text row, matching the skin's label2 posy=26.
_USERNAME_ROW_HEIGHT = 26
# Skin px per wrapped message line - same value ChatOverlay's fixed label2 box is sized from
# (210px / 5 lines; see the v0.16.5 CHANGELOG entry for how it was measured against live
# rendering on a real Kodi build).
_LINE_PITCH = 42
_EMOTE_ROW_HEIGHT = 28
_EMOTE_SIZE = 28
_EMOTE_X_OFFSETS = (10, 40, 70, 100, 130, 160)


def _block_height(line_count, has_emotes):
    height = _USERNAME_ROW_HEIGHT + line_count * _LINE_PITCH
    if has_emotes:
        height += _EMOTE_ROW_HEIGHT
    return height


def _build_block(event):
    """Build one message's controls at a placeholder y=0 - _position_block() sets the real
    position once the block's place in the column is known."""
    lines = _wrap_message_lines(event["text"])
    emotes = [
        emote for emote in (event.get("emotes") or [])[:_MAX_EMOTE_SLOTS] if emote.get("url")
    ]
    message_height = len(lines) * _LINE_PITCH
    height = _block_height(len(lines), has_emotes=bool(emotes))

    items = []
    username_label = xbmcgui.ControlLabel(
        _COLUMN_X + 10, 0, _COLUMN_WIDTH - 20, _USERNAME_HEIGHT,
        event["display_name"], font=_FONT, textColor=_USERNAME_COLOR,
    )
    items.append((username_label, _COLUMN_X + 10, 0))

    message_label = xbmcgui.ControlLabel(
        _COLUMN_X + 10, 0, _COLUMN_WIDTH - 20, message_height,
        "\n".join(lines), font=_FONT,
    )
    items.append((message_label, _COLUMN_X + 10, _USERNAME_ROW_HEIGHT))

    emote_rel_y = _USERNAME_ROW_HEIGHT + message_height
    for i, emote in enumerate(emotes):
        image = xbmcgui.ControlImage(
            _COLUMN_X + _EMOTE_X_OFFSETS[i], 0, _EMOTE_SIZE, _EMOTE_SIZE, emote["url"],
            aspectRatio=2,
        )
        items.append((image, _COLUMN_X + _EMOTE_X_OFFSETS[i], emote_rel_y))

    return {"items": items, "height": height}


def _block_controls(block):
    return [control for control, _x, _rel_y in block["items"]]


def _position_block(block, top_y):
    for control, x, rel_y in block["items"]:
        control.setPosition(x, top_y + rel_y)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/windows/test_variable_chat_overlay.py -v`
Expected: PASS (7 tests)

- [ ] **Step 5: Commit**

```bash
git add lib/windows/variable_chat_overlay.py tests/windows/test_variable_chat_overlay.py
git commit -m "feat: add block-sizing/building functions for variable-height chat overlay

Pure functions only - no window/rendering wiring yet (next task)."
```

---

### Task 5: `VariableChatOverlay` class - positioning, eviction, control reuse, close

**Why:** This is the actual overlay class: a `ChatOverlay` subclass overriding `_render()` to use
Task 4's block functions, positioning the newest message at the bottom of the column and evicting
oldest blocks once the column overflows, while never recreating a still-visible message's controls.

**Files:**
- Modify: `lib/windows/variable_chat_overlay.py`
- Test: `tests/windows/test_variable_chat_overlay.py`

**Interfaces:**
- Consumes: `ChatOverlay` from `lib.windows.chat_overlay` (unmodified - `__init__`, `onInit`,
  `_pump_messages`, `_messages`, `_total_evicted`, `close`'s cancel/disconnect steps); `_block_height`,
  `_build_block`, `_block_controls`, `_position_block`, `_COLUMN_Y`, `_COLUMN_HEIGHT` (Task 4).
- Produces: `VariableChatOverlay` class, with `self._blocks` (ordered oldest-first list of Task 4
  block dicts) and `self._blocks_built` (int). Used by Task 7 (player.py wiring).

- [ ] **Step 1: Write the failing tests**

Add to `tests/windows/test_variable_chat_overlay.py`:

```python
from unittest.mock import patch

from lib.windows.variable_chat_overlay import (
    _COLUMN_HEIGHT,
    _COLUMN_Y,
    VariableChatOverlay,
)


class FakeChatClient:
    instances = []

    def __init__(self, channel, access_token=None, client_id=None, broadcaster_user_id=None,
                 user_id=None):
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


def _make_overlay(events):
    class ClientWithEvents(FakeChatClient):
        def __init__(self, channel, **kwargs):
            super().__init__(channel, **kwargs)
            self._events = events

    win = VariableChatOverlay(
        "script-twitch-center-chat-overlay.xml",
        "/tmp",
        "Default",
        "1080i",
        channel="somechannel",
        chat_client_cls=ClientWithEvents,
    )
    win.onInit()
    win._thread.join(timeout=1)
    assert not win._thread.is_alive()
    return win


def test_single_message_block_is_positioned_at_the_bottom_of_the_column():
    FakeChatClient.instances.clear()
    win = _make_overlay([_message_event("bob", "hi", 1)])

    assert len(win._blocks) == 1
    block = win._blocks[0]
    username_control = block["items"][0][0]
    expected_top = _COLUMN_Y + _COLUMN_HEIGHT - block["height"]
    assert username_control.getPosition()[1] == expected_top


def test_newer_message_is_positioned_above_older_message():
    FakeChatClient.instances.clear()
    win = _make_overlay([
        _message_event("bob", "hi", 1),
        _message_event("carol", "hello there", 2),
    ])

    assert len(win._blocks) == 2
    older_block, newer_block = win._blocks
    older_y = older_block["items"][0][0].getPosition()[1]
    newer_y = newer_block["items"][0][0].getPosition()[1]
    assert newer_y < older_y


def test_controls_from_earlier_render_are_repositioned_not_recreated():
    FakeChatClient.instances.clear()
    win = _make_overlay([
        _message_event("bob", "hi", 1),
        _message_event("carol", "hello there", 2),
    ])

    first_call_controls = win._blocks[0]["items"][0][0]
    win._render()
    second_call_controls = win._blocks[0]["items"][0][0]
    assert first_call_controls is second_call_controls


def test_old_blocks_are_evicted_once_total_height_exceeds_the_column():
    FakeChatClient.instances.clear()
    # Each of these wraps to 5 lines with no emotes - block height 26 + 5*42 = 236px. Five of
    # them (1180px) exceed the 960px column, so the oldest should be evicted.
    long_text = (
        "which upcoming games are you looking forward to for the rest of this year, "
        "modz? asking because I want to plan my backlog around the big releases"
    )
    events = [_message_event("user%d" % i, long_text, i) for i in range(5)]
    win = _make_overlay(events)

    assert len(win._blocks) == 4
    usernames = [block["items"][0][0].getLabel() for block in win._blocks]
    assert usernames == ["User1", "User2", "User3", "User4"]


def test_a_single_message_taller_than_the_column_is_still_shown():
    # With real constants, a single block (max 264px, 5 lines + emotes) can never exceed the
    # real 960px column - this patches the column height down so the overflow-safety branch
    # (newest block always kept, even if it alone doesn't fit) is actually exercised.
    FakeChatClient.instances.clear()
    with patch("lib.windows.variable_chat_overlay._COLUMN_HEIGHT", 50):
        win = _make_overlay([_message_event("bob", "hi", 1)])

    assert len(win._blocks) == 1
    assert win._blocks[0]["items"][0][0].getLabel() == "Bob"


def test_close_removes_all_remaining_controls():
    FakeChatClient.instances.clear()
    win = _make_overlay([_message_event("bob", "hi", 1)])
    controls = win._blocks[0]["items"]
    controls = [control for control, _x, _rel_y in controls]
    assert controls
    for control in controls:
        assert control in win._added_controls

    win.close()

    assert win._blocks == []
    for control in controls:
        assert control not in win._added_controls
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/windows/test_variable_chat_overlay.py -v`
Expected: FAIL with `ImportError: cannot import name 'VariableChatOverlay'`

- [ ] **Step 3: Implement `VariableChatOverlay`**

Add to `lib/windows/variable_chat_overlay.py` (after the Task 4 functions), including the
`ChatOverlay` import at the top:

```python
from lib.windows.chat_overlay import ChatOverlay, _MAX_EMOTE_SLOTS, _wrap_message_lines
```

(replaces the Task 4 `from lib.windows.chat_overlay import _MAX_EMOTE_SLOTS, _wrap_message_lines`
line - just adds `ChatOverlay` to the same import)

```python
class VariableChatOverlay(ChatOverlay):
    """Opt-in alternative renderer - see module docstring. Reuses ChatOverlay's chat-client
    connection and pump-thread scaffolding (__init__/onInit/_pump_messages, and close()'s
    cancel/disconnect steps), overriding only _render() (and extending close()) to place
    controls by hand instead of using the skin's <list> control."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._blocks = []
        self._blocks_built = 0

    def _render(self):
        # self._total_evicted + len(self._messages) is the total number of messages ever
        # appended (ChatOverlay._pump_messages trims self._messages to the last _MAX_MESSAGES,
        # tracking how many were dropped in _total_evicted) - comparing that running total
        # against how many we've already turned into blocks tells us what's new, without
        # re-scanning messages we've already built controls for.
        total_seen = self._total_evicted + len(self._messages)
        new_count = total_seen - self._blocks_built
        if new_count > 0:
            for event in self._messages[-new_count:]:
                block = _build_block(event)
                for control in _block_controls(block):
                    self.addControl(control)
                self._blocks.append(block)
            self._blocks_built = total_seen

        # Reposition every visible block newest-to-oldest, evicting once a block would fall
        # off the top of the column - except the newest block itself is always kept, even if
        # it alone is taller than the column (a pathological very-long message).
        cursor = _COLUMN_Y + _COLUMN_HEIGHT
        placed_newest = False
        keep_from = 0
        for i in range(len(self._blocks) - 1, -1, -1):
            block = self._blocks[i]
            new_cursor = cursor - block["height"]
            if new_cursor < _COLUMN_Y and placed_newest:
                keep_from = i + 1
                break
            _position_block(block, new_cursor)
            cursor = new_cursor
            placed_newest = True
            keep_from = i

        for evicted in self._blocks[:keep_from]:
            for control in _block_controls(evicted):
                self.removeControl(control)
        self._blocks = self._blocks[keep_from:]

    def close(self):
        for block in self._blocks:
            for control in _block_controls(block):
                self.removeControl(control)
        self._blocks = []
        super().close()
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/windows/test_variable_chat_overlay.py -v`
Expected: PASS (13 tests total: 7 from Task 4 + 6 new)

- [ ] **Step 5: Run the full suite to confirm no regressions**

Run: `python -m pytest -q`
Expected: PASS, previous count + 13 (Task 4's 7 + Task 5's 6).

- [ ] **Step 6: Commit**

```bash
git add lib/windows/variable_chat_overlay.py tests/windows/test_variable_chat_overlay.py
git commit -m "feat: add VariableChatOverlay class

Positions/evicts message blocks by actual height instead of a fixed
per-row slot. Not wired into player.py yet (later task)."
```

---

### Task 6: Settings plumbing

**Why:** New opt-in toggle, `chat_overlay_variable_height`, default off, following the existing
`show_offline_channels` boolean-setting pattern exactly.

**Files:**
- Modify: `lib/settings.py`
- Modify: `resources/settings.xml`
- Modify: `resources/language/resource.language.en_gb/strings.po`
- Test: `tests/test_settings.py`

**Interfaces:**
- Produces: `Settings.chat_overlay_variable_height` (bool property, default `False`). Used by
  Task 7 (player.py wiring).

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_settings.py`:

```python
def test_chat_overlay_variable_height_defaults_to_false():
    settings = Settings()
    assert settings.chat_overlay_variable_height is False


def test_chat_overlay_variable_height_reads_addon_setting():
    addon = xbmcaddon.Addon()
    addon.setSetting("chat_overlay_variable_height", True)
    settings = Settings(addon=addon)
    assert settings.chat_overlay_variable_height is True
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_settings.py -k variable_height -v`
Expected: FAIL with `AttributeError: 'Settings' object has no attribute 'chat_overlay_variable_height'`

- [ ] **Step 3: Add the property**

In `lib/settings.py`, add after `show_offline_channels`:

```python
    @property
    def chat_overlay_variable_height(self):
        return self._addon.getSettingBool("chat_overlay_variable_height")
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_settings.py -v`
Expected: PASS (all settings tests, including the two new ones)

- [ ] **Step 5: Add the settings.xml entry**

In `resources/settings.xml`, add after the `show_offline_channels` `<setting>` block (before
`client_id`):

```xml
        <setting id="chat_overlay_variable_height" type="boolean" label="30018" help="30019">
          <level>0</level>
          <default>false</default>
          <control type="toggle"/>
        </setting>
```

- [ ] **Step 6: Add the strings.po entries**

In `resources/language/resource.language.en_gb/strings.po`, add at the end of the file (after
`#30017`):

```
msgctxt "#30018"
msgid "Variable-size chat overlay (EventSub only)"
msgstr ""

msgctxt "#30019"
msgid "Sizes each chat overlay message's box to its actual length instead of a fixed maximum. Only takes effect when the EventSub chat engine is selected above."
msgstr ""
```

- [ ] **Step 7: Validate the settings.xml is well-formed**

Run: `python -c "import xml.dom.minidom as m; m.parse('resources/settings.xml'); print('xml OK')"`
Expected: `xml OK`

- [ ] **Step 8: Run the full suite to confirm no regressions**

Run: `python -m pytest -q`
Expected: PASS, previous count + 2.

- [ ] **Step 9: Commit**

```bash
git add lib/settings.py resources/settings.xml resources/language/resource.language.en_gb/strings.po tests/test_settings.py
git commit -m "feat: add chat_overlay_variable_height setting

Default off. Not wired into player.py's overlay-class selection yet
(next task)."
```

---

### Task 7: Wire `player.py`'s overlay-class selection

**Why:** This is the task that actually makes the setting do something: `play_stream` picks
`VariableChatOverlay` instead of `ChatOverlay` only when no explicit `chat_overlay_cls` override was
passed in, the resolved chat engine is `eventsub` (after the existing silent-fallback-to-IRC check),
and the new setting is enabled.

**Files:**
- Modify: `lib/windows/player.py:15,273`
- Test: `tests/windows/test_player.py`

**Interfaces:**
- Consumes: `VariableChatOverlay` from `lib.windows.variable_chat_overlay` (Task 5);
  `Settings.chat_overlay_variable_height` (Task 6).

- [ ] **Step 1: Write the failing tests**

Add to `tests/windows/test_player.py`, near the other engine-selection tests
(`test_play_stream_uses_irc_engine_by_default` etc.):

First, extend `FakeSettings` (near the top of the file) to accept the new field:

```python
class FakeSettings:
    def __init__(self, chat_display_mode, chat_engine="irc", chat_overlay_variable_height=False):
        self.chat_display_mode = chat_display_mode
        self.chat_engine = chat_engine
        self.chat_overlay_variable_height = chat_overlay_variable_height
```

Then add a fake variable overlay class and the new tests:

```python
class FakeVariableChatOverlay(FakeChatOverlay):
    pass


def test_play_stream_uses_variable_overlay_when_enabled_and_eventsub():
    FakeChatOverlay.instances.clear()
    with patch("lib.windows.player.Helper") as mock_helper_cls, patch(
        "lib.windows.player.xbmc.Player"
    ), patch("lib.windows.player.PlaybackWatchdog", FakeWatchdog), patch(
        "lib.windows.player.api.get_user_by_login",
        return_value={"id": "999", "login": "somechannel", "display_name": "SomeChannel"},
    ), patch(
        "lib.windows.player.VariableChatOverlay", FakeVariableChatOverlay
    ):
        mock_helper_cls.return_value.check_inputstream.return_value = True
        mock_helper_cls.return_value.inputstream_addon = "inputstream.adaptive"

        player.play_stream(
            "https://example.invalid/stream.m3u8",
            "somechannel",
            settings=FakeSettings(
                "overlay", chat_engine="eventsub", chat_overlay_variable_height=True
            ),
            access_token="tok",
            client_id="cid",
            user_id="42",
        )

    assert len(FakeVariableChatOverlay.instances) == 1


def test_play_stream_uses_default_overlay_when_variable_setting_disabled():
    FakeChatOverlay.instances.clear()
    with patch("lib.windows.player.Helper") as mock_helper_cls, patch(
        "lib.windows.player.xbmc.Player"
    ), patch("lib.windows.player.PlaybackWatchdog", FakeWatchdog), patch(
        "lib.windows.player.api.get_user_by_login",
        return_value={"id": "999", "login": "somechannel", "display_name": "SomeChannel"},
    ), patch(
        "lib.windows.player.ChatOverlay", FakeChatOverlay
    ), patch(
        "lib.windows.player.VariableChatOverlay", FakeVariableChatOverlay
    ):
        mock_helper_cls.return_value.check_inputstream.return_value = True
        mock_helper_cls.return_value.inputstream_addon = "inputstream.adaptive"

        player.play_stream(
            "https://example.invalid/stream.m3u8",
            "somechannel",
            settings=FakeSettings(
                "overlay", chat_engine="eventsub", chat_overlay_variable_height=False
            ),
            access_token="tok",
            client_id="cid",
            user_id="42",
        )

    assert len(FakeChatOverlay.instances) == 1
    assert FakeVariableChatOverlay.instances == []


def test_play_stream_uses_default_overlay_when_variable_setting_enabled_but_irc_engine():
    FakeChatOverlay.instances.clear()
    with patch("lib.windows.player.Helper") as mock_helper_cls, patch(
        "lib.windows.player.xbmc.Player"
    ), patch("lib.windows.player.PlaybackWatchdog", FakeWatchdog), patch(
        "lib.windows.player.ChatOverlay", FakeChatOverlay
    ), patch(
        "lib.windows.player.VariableChatOverlay", FakeVariableChatOverlay
    ):
        mock_helper_cls.return_value.check_inputstream.return_value = True
        mock_helper_cls.return_value.inputstream_addon = "inputstream.adaptive"

        player.play_stream(
            "https://example.invalid/stream.m3u8",
            "somechannel",
            settings=FakeSettings(
                "overlay", chat_engine="irc", chat_overlay_variable_height=True
            ),
        )

    assert len(FakeChatOverlay.instances) == 1
    assert FakeVariableChatOverlay.instances == []


def test_play_stream_uses_default_overlay_when_eventsub_falls_back_to_irc():
    FakeChatOverlay.instances.clear()
    with patch("lib.windows.player.Helper") as mock_helper_cls, patch(
        "lib.windows.player.xbmc.Player"
    ), patch("lib.windows.player.PlaybackWatchdog", FakeWatchdog), patch(
        "lib.windows.player.api.get_user_by_login", return_value=None
    ), patch(
        "lib.windows.player.ChatOverlay", FakeChatOverlay
    ), patch(
        "lib.windows.player.VariableChatOverlay", FakeVariableChatOverlay
    ):
        mock_helper_cls.return_value.check_inputstream.return_value = True
        mock_helper_cls.return_value.inputstream_addon = "inputstream.adaptive"

        player.play_stream(
            "https://example.invalid/stream.m3u8",
            "somechannel",
            settings=FakeSettings(
                "overlay", chat_engine="eventsub", chat_overlay_variable_height=True
            ),
            access_token="tok",
            client_id="cid",
            user_id="42",
        )

    assert len(FakeChatOverlay.instances) == 1
    assert FakeVariableChatOverlay.instances == []
```

Note: the existing tests (`test_play_stream_uses_irc_engine_by_default` and friends) all pass
`chat_overlay_cls=FakeChatOverlay` explicitly - that must keep forcing `FakeChatOverlay` regardless
of the new setting, which the Step 3 implementation preserves (explicit override always wins).

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/windows/test_player.py -k variable_overlay -v`
Expected: FAIL (either `ImportError`-adjacent from the `patch(...)` target not existing yet, since
`lib.windows.player.VariableChatOverlay` isn't imported, or `AttributeError` on `FakeSettings` before
Step 1's `FakeSettings` edit takes effect - both resolve once Step 3 below is done)

- [ ] **Step 3: Wire the selection in `player.py`**

In `lib/windows/player.py`, add the import (near the existing `from lib.windows.chat_overlay import
ChatOverlay`):

```python
from lib.windows.chat_overlay import ChatOverlay
from lib.windows.variable_chat_overlay import VariableChatOverlay
```

Then replace:

```python
            overlay_cls = chat_overlay_cls or ChatOverlay
```

with:

```python
            if chat_overlay_cls is not None:
                overlay_cls = chat_overlay_cls
            elif engine == "eventsub" and settings.chat_overlay_variable_height:
                overlay_cls = VariableChatOverlay
            else:
                overlay_cls = ChatOverlay
```

(this sits after the `engine = "irc"` fallback reassignment earlier in the same `try` block, so a
silent EventSub→IRC fallback already has `engine == "irc"` by this point and correctly falls through
to `ChatOverlay`)

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/windows/test_player.py -v`
Expected: PASS, all player tests including the 4 new ones.

- [ ] **Step 5: Run the full suite to confirm no regressions**

Run: `python -m pytest -q`
Expected: PASS, previous count + 4.

- [ ] **Step 6: Commit**

```bash
git add lib/windows/player.py tests/windows/test_player.py
git commit -m "feat: wire VariableChatOverlay into player.py's overlay selection

Selected only when chat_overlay_variable_height is enabled and the
resolved chat engine is eventsub (post-fallback) - explicit
chat_overlay_cls callers (all existing tests) are unaffected."
```

---

### Task 8: Version bump, changelog, and live verification

**Why:** Project convention (established this session) is a `CHANGELOG.md` entry and `addon.xml`
version bump per shipped feature. This also needs a real on-device check - control positioning math
has already once been wrong in a way unit tests couldn't catch (the v0.16.4/v0.16.5 fixes), so a live
render check against a real EventSub channel is part of "done," not optional polish.

**Files:**
- Modify: `addon.xml`
- Modify: `CHANGELOG.md`

**Interfaces:** None - this is the final, non-code task.

- [ ] **Step 1: Bump the version**

New feature (not fix-only) - minor version bump. In `addon.xml`, change the `version` attribute from
whatever it currently is (check `addon.xml` - should be `0.16.5` unless other work has landed since)
to the next minor version, e.g. `0.17.0`.

- [ ] **Step 2: Add the `<news>` entry**

In `addon.xml`, add a new entry at the top of `<news>`:

```
      v0.17.0: New "Variable-size chat overlay" setting (Settings > General, EventSub only) -
      sizes each chat overlay message's box to its actual length instead of always reserving
      space for the maximum 5-line message. Off by default; the existing fixed-box overlay
      stays the default for both chat engines.
```

- [ ] **Step 3: Add the CHANGELOG.md entry**

In `CHANGELOG.md`, add a new section at the top:

```markdown
## [0.17.0] - <today's date, YYYY-MM-DD>

### Added
- New "Variable-size chat overlay" setting (Settings > General), off by default. When enabled and
  the EventSub chat engine is selected, chat messages size their on-screen box to their actual
  wrapped line count instead of the fixed-box overlay's 270px slot reserved for the worst-case
  5-line message. Built by placing Kodi controls directly rather than through the skin's `<list>`
  control, which can't vary row height per item - see
  `docs/superpowers/specs/2026-08-22-variable-height-chat-overlay-design.md`.
```

- [ ] **Step 4: Run the full test suite one more time**

Run: `python -m pytest -q`
Expected: PASS, full count.

- [ ] **Step 5: Deploy to the local dev Kodi instance and verify live**

This repeats the procedure already used earlier this session (DatModz channel, local Kodi 21.3
instance, JSON-RPC screenshot verification):

1. Enable the new setting and EventSub engine via the addon's Settings screen (or by writing
   `chat_overlay_variable_height=true` and `chat_engine=eventsub` directly into the deployed addon's
   `settings.xml` if faster).
2. Deploy the working tree to `~/.kodi/addons/script.twitch.center/` (same rsync/tar approach used
   earlier this session).
3. Launch Kodi (`kodi --standalone`), start playback on a live EventSub-capable channel (e.g.
   DatModz), and let chat accumulate for ~20-30 seconds.
4. Take a screenshot via `Input.ExecuteAction` (`action: "screenshot"`) over JSON-RPC, same as
   earlier in this session.
5. Visually confirm: short (1-2 line) messages take noticeably less vertical space than long (4-5
   line) ones, newest message is at the bottom, no overlapping text between messages, no crash.
6. Stop the local Kodi instance (`pkill -9 -f "kodi.bin --standalone"`) when done.

If anything looks wrong, fix it and re-run the relevant unit tests plus this live check before
proceeding - do not skip straight to committing based on unit tests alone, per this task's rationale.

- [ ] **Step 6: Commit**

```bash
git add addon.xml CHANGELOG.md
git commit -m "chore: bump version to 0.17.0 for variable-height chat overlay setting"
```

- [ ] **Step 7: Push and redeploy to kodi.local**

Only after the user confirms they want this pushed/deployed (matches this session's established
pattern of asking before `git push` and before restarting the `kodi` service on `kodi.local`, since
that interrupts live playback there).
