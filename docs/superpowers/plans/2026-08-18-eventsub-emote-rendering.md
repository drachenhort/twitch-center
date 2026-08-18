# EventSub Emote Rendering Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Render EventSub chat messages' emote fragments as a strip of real emote images below the message text, EventSub engine only.

**Architecture:** `lib/twitch/eventsub.py` gains a pure-function emote extractor that turns Twitch's `fragments` list into capped `{id, text, url}` dicts and attaches them to the `"message"` event as `"emotes"`. `lib/windows/chat_overlay.py`'s `_build_message_item` reads that key (defaulting to `[]` for IRC, which never sets it) and calls `setArt` with `emote_0..emote_5` slots. The skin's chat-overlay XML grows each message row with 6 fixed image controls bound to those art keys, hidden when empty.

**Tech Stack:** Python (pytest), Kodi `xbmcgui`/skin XML (no new dependencies).

**Spec:** `docs/superpowers/specs/2026-08-18-eventsub-emote-rendering-design.md`

## Global Constraints

- EventSub only. `lib/twitch/irc.py` and its rendering behavior must not change at all.
- Emote CDN URL template: `https://static-cdn.jtvnw.net/emoticons/v2/{id}/static/dark/1.0`.
- Cap at 6 emotes per message, enforced independently in both `eventsub.py` (`_extract_emotes`) and `chat_overlay.py` (`_build_message_item`) — each must not assume the other enforced it.
- No image caching/fetching code — Kodi's texture manager handles remote art URLs, same as existing thumbnail usage elsewhere in this codebase.
- Malformed/missing emote data never raises — always degrades to `[]` / plain text.
- Slots beyond the message's actual emote count get no art set at all (never explicitly cleared to `""`).

---

### Task 1: `_extract_emotes` in `lib/twitch/eventsub.py`

**Files:**
- Modify: `lib/twitch/eventsub.py` (add near top-level constants, after `_RFC3339_RE` at line 33, and before `_handle_payload` at line 337)
- Test: `tests/twitch/test_eventsub.py`

**Interfaces:**
- Produces: `EMOTE_IMAGE_URL_TEMPLATE` (module constant, str), `_MAX_EMOTES_PER_MESSAGE = 6` (module constant, int), `_extract_emotes(fragments) -> list[dict]` where each dict is `{"id": str, "text": str, "url": str}`. Never raises.

- [ ] **Step 1: Write the failing tests**

Add to `tests/twitch/test_eventsub.py` (near the other standalone-function tests around line 132, alongside `_parse_rfc3339_ms` tests):

```python
from lib.twitch.eventsub import _extract_emotes, EMOTE_IMAGE_URL_TEMPLATE


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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/twitch/test_eventsub.py -k extract_emotes -v`
Expected: FAIL with `ImportError: cannot import name '_extract_emotes'`

- [ ] **Step 3: Write the implementation**

In `lib/twitch/eventsub.py`, insert after the `_RFC3339_RE` block (line 33) and before `_build_handshake_key` (line 36):

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/twitch/test_eventsub.py -k extract_emotes -v`
Expected: PASS (7 tests)

- [ ] **Step 5: Commit**

```bash
git add lib/twitch/eventsub.py tests/twitch/test_eventsub.py
git commit -m "feat: add _extract_emotes to parse EventSub chat fragments into emote image data"
```

---

### Task 2: Wire `_extract_emotes` into `_handle_payload`'s message event

**Files:**
- Modify: `lib/twitch/eventsub.py:351-358` (the `channel.chat.message` branch of `_handle_payload`)
- Modify: `tests/twitch/test_eventsub.py:294-327` (`test_chat_message_notification_yields_message_event`, currently asserts an exact dict without `"emotes"` — must be updated, not left to fail)

**Interfaces:**
- Consumes: `_extract_emotes` from Task 1.
- Produces: the `"message"` event dict now always includes an `"emotes"` key (list, possibly empty).

- [ ] **Step 1: Update the existing test to expect the new key, and add a fragments-carrying case**

Replace `test_chat_message_notification_yields_message_event` in `tests/twitch/test_eventsub.py` with:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/twitch/test_eventsub.py -k chat_message_notification -v`
Expected: FAIL — first test fails on missing `"emotes"` key in actual dict, second fails with `KeyError: 'emotes'`.

- [ ] **Step 3: Write the implementation**

In `lib/twitch/eventsub.py`, change the `channel.chat.message` branch (currently lines 351-358):

```python
        if subscription_type == "channel.chat.message":
            self._enqueue({
                "type": "message",
                "username": event["chatter_user_login"],
                "display_name": event["chatter_user_name"],
                "text": event["message"]["text"],
                "timestamp": timestamp,
                "emotes": _extract_emotes(event.get("message", {}).get("fragments")),
            })
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/twitch/test_eventsub.py -v`
Expected: PASS (all tests, including the full existing suite — this confirms nothing else in `eventsub.py` broke)

- [ ] **Step 5: Commit**

```bash
git add lib/twitch/eventsub.py tests/twitch/test_eventsub.py
git commit -m "feat: attach extracted emotes to EventSub channel.chat.message events"
```

---

### Task 3: `_build_message_item` sets emote art in `lib/windows/chat_overlay.py`

**Files:**
- Modify: `lib/windows/chat_overlay.py:25-43` (add `_MAX_EMOTE_SLOTS` constant near `_MAX_MESSAGE_LINES`, update `_build_message_item`)
- Test: `tests/windows/test_chat_overlay.py`

**Interfaces:**
- Consumes: event dicts with an optional `"emotes"` key (list of `{"id", "text", "url"}` dicts), as produced by Task 2. IRC's `ChatClient` events never have this key.
- Produces: `_build_message_item(event)` now also calls `item.setArt({"emote_0": url, ...})` when the event has emotes.

- [ ] **Step 1: Write the failing tests**

Add to `tests/windows/test_chat_overlay.py`, near the other `_build_message_item`-exercising tests (after `test_pump_truncates_messages_that_would_wrap_past_the_label_height`, before `test_pump_caps_message_list_at_fifty_dropping_oldest`):

```python
def _message_event_with_emotes(username, text, emotes, index=0):
    event = _message_event(username, text, index)
    event["emotes"] = emotes
    return event


def test_pump_sets_no_art_when_event_has_no_emotes_key():
    FakeChatClient.instances.clear()

    class ClientWithMessage(FakeChatClient):
        def __init__(self, channel, **kwargs):
            super().__init__(channel, **kwargs)
            self._events = [_message_event("bob", "hello", 1)]

    win = ChatOverlay(
        "script-twitch-center-chat-overlay.xml",
        "/tmp",
        "Default",
        "1080i",
        channel="somechannel",
        chat_client_cls=ClientWithMessage,
    )
    win.onInit()
    win._thread.join(timeout=1)

    control = win.getControl(ChatOverlay.MESSAGE_LIST_ID)
    assert control._items[0].getArt("emote_0") == ""


def test_pump_sets_art_for_one_emote():
    FakeChatClient.instances.clear()
    emotes = [{"id": "25", "text": "Kappa", "url": "https://example.test/25.png"}]

    class ClientWithEmote(FakeChatClient):
        def __init__(self, channel, **kwargs):
            super().__init__(channel, **kwargs)
            self._events = [_message_event_with_emotes("bob", "Kappa", emotes, 1)]

    win = ChatOverlay(
        "script-twitch-center-chat-overlay.xml",
        "/tmp",
        "Default",
        "1080i",
        channel="somechannel",
        chat_client_cls=ClientWithEmote,
    )
    win.onInit()
    win._thread.join(timeout=1)

    control = win.getControl(ChatOverlay.MESSAGE_LIST_ID)
    item = control._items[0]
    assert item.getArt("emote_0") == "https://example.test/25.png"
    assert item.getArt("emote_1") == ""


def test_pump_sets_art_for_six_emotes():
    FakeChatClient.instances.clear()
    emotes = [{"id": str(i), "text": "E%d" % i, "url": "https://example.test/%d.png" % i} for i in range(6)]

    class ClientWithSixEmotes(FakeChatClient):
        def __init__(self, channel, **kwargs):
            super().__init__(channel, **kwargs)
            self._events = [_message_event_with_emotes("bob", "many emotes", emotes, 1)]

    win = ChatOverlay(
        "script-twitch-center-chat-overlay.xml",
        "/tmp",
        "Default",
        "1080i",
        channel="somechannel",
        chat_client_cls=ClientWithSixEmotes,
    )
    win.onInit()
    win._thread.join(timeout=1)

    control = win.getControl(ChatOverlay.MESSAGE_LIST_ID)
    item = control._items[0]
    for i in range(6):
        assert item.getArt("emote_%d" % i) == "https://example.test/%d.png" % i


def test_pump_caps_art_at_six_slots_even_with_more_emotes_in_event():
    FakeChatClient.instances.clear()
    emotes = [{"id": str(i), "text": "E%d" % i, "url": "https://example.test/%d.png" % i} for i in range(8)]

    class ClientWithEightEmotes(FakeChatClient):
        def __init__(self, channel, **kwargs):
            super().__init__(channel, **kwargs)
            self._events = [_message_event_with_emotes("bob", "too many emotes", emotes, 1)]

    win = ChatOverlay(
        "script-twitch-center-chat-overlay.xml",
        "/tmp",
        "Default",
        "1080i",
        channel="somechannel",
        chat_client_cls=ClientWithEightEmotes,
    )
    win.onInit()
    win._thread.join(timeout=1)

    control = win.getControl(ChatOverlay.MESSAGE_LIST_ID)
    item = control._items[0]
    for i in range(6):
        assert item.getArt("emote_%d" % i) == "https://example.test/%d.png" % i
    assert item.getArt("emote_6") == ""
    assert item.getArt("emote_7") == ""
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/windows/test_chat_overlay.py -k "emote" -v`
Expected: FAIL — `test_pump_sets_art_for_one_emote` etc. fail because `getArt("emote_0")` is `""` (no art ever set).

- [ ] **Step 3: Write the implementation**

In `lib/windows/chat_overlay.py`, add the constant after `_MAX_MESSAGE_LINES = 5` (line 33) and update `_build_message_item` (lines 36-43):

```python
# Fixed number of emote image-control slots in the skin's per-item layout
# (ids 110-115, see resources/skins/Default/1080i/script-twitch-center-chat-overlay.xml).
# Re-capped here independently of eventsub.py's own _MAX_EMOTES_PER_MESSAGE cap - this
# function must not assume its caller already enforced the limit.
_MAX_EMOTE_SLOTS = 6


def _build_message_item(event):
    item = xbmcgui.ListItem(event["display_name"])
    lines = textwrap.wrap(event["text"], _MESSAGE_WRAP_WIDTH)
    if len(lines) > _MAX_MESSAGE_LINES:
        lines = lines[:_MAX_MESSAGE_LINES]
        lines[-1] = lines[-1][: max(0, _MESSAGE_WRAP_WIDTH - 3)].rstrip() + "..."
    item.setLabel2("\n".join(lines))
    emotes = event.get("emotes", [])[:_MAX_EMOTE_SLOTS]
    if emotes:
        item.setArt({"emote_%d" % i: emote["url"] for i, emote in enumerate(emotes)})
    return item
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/windows/test_chat_overlay.py -v`
Expected: PASS (full file — confirms IRC-shaped events without `"emotes"` still render correctly)

- [ ] **Step 5: Commit**

```bash
git add lib/windows/chat_overlay.py tests/windows/test_chat_overlay.py
git commit -m "feat: render EventSub emote art slots in chat overlay message items"
```

---

### Task 4: Add emote image controls to the chat-overlay skin XML

**Files:**
- Modify: `resources/skins/Default/1080i/script-twitch-center-chat-overlay.xml` (both `itemlayout` and `focusedlayout` blocks under control id `101`)
- Test: `tests/test_addon_manifest.py`

**Interfaces:**
- Consumes: `ListItem.Art(emote_0)`..`ListItem.Art(emote_5)`, as set by Task 3's `_build_message_item`.
- Produces: control ids `110`-`115` (image type) in both layouts, each visible only when its `emote_N` art key is non-empty. No Python-facing interface — skin-only change verified by XML structure tests plus live testing.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_addon_manifest.py`, after `test_chat_overlay_skin_xml_declares_message_list_control_id` (line 137):

```python
def test_chat_overlay_skin_xml_declares_six_emote_image_slots_per_layout():
    tree = ET.parse(CHAT_OVERLAY_SKIN_XML)
    root = tree.getroot()
    expected_ids = {110, 111, 112, 113, 114, 115}

    for layout_tag in ("itemlayout", "focusedlayout"):
        layout = root.find(f".//control[@id='101']/{layout_tag}")
        assert layout is not None, f"{layout_tag} not found under control id 101"

        image_controls = [c for c in layout.findall("control") if c.attrib.get("type") == "image"]
        found_ids = {int(c.attrib["id"]) for c in image_controls}
        assert found_ids == expected_ids, f"{layout_tag}: expected {expected_ids}, got {found_ids}"

        for control in image_controls:
            index = int(control.attrib["id"]) - 110
            texture = control.find("texture").text
            visible = control.find("visible").text
            assert texture == f"$INFO[ListItem.Art(emote_{index})]"
            assert visible == f"!String.IsEmpty(ListItem.Art(emote_{index}))"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_addon_manifest.py -k six_emote_image_slots -v`
Expected: FAIL — `found_ids == set()`, assertion mismatch against `{110, ..., 115}`.

- [ ] **Step 3: Write the implementation**

Replace the full contents of `resources/skins/Default/1080i/script-twitch-center-chat-overlay.xml` with (item/focused layout height grows 165 -> 197, each gets 6 new image controls at posy 168, posx 10/40/70/100/130/160):

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
      <itemlayout width="380" height="197">
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
          <height>140</height>
          <font>font13</font>
          <wrapmultiline>true</wrapmultiline>
          <label>$INFO[ListItem.Label2]</label>
        </control>
        <control type="image" id="110">
          <posx>10</posx>
          <posy>168</posy>
          <width>28</width>
          <height>28</height>
          <aspectratio>keep</aspectratio>
          <texture>$INFO[ListItem.Art(emote_0)]</texture>
          <visible>!String.IsEmpty(ListItem.Art(emote_0))</visible>
        </control>
        <control type="image" id="111">
          <posx>40</posx>
          <posy>168</posy>
          <width>28</width>
          <height>28</height>
          <aspectratio>keep</aspectratio>
          <texture>$INFO[ListItem.Art(emote_1)]</texture>
          <visible>!String.IsEmpty(ListItem.Art(emote_1))</visible>
        </control>
        <control type="image" id="112">
          <posx>70</posx>
          <posy>168</posy>
          <width>28</width>
          <height>28</height>
          <aspectratio>keep</aspectratio>
          <texture>$INFO[ListItem.Art(emote_2)]</texture>
          <visible>!String.IsEmpty(ListItem.Art(emote_2))</visible>
        </control>
        <control type="image" id="113">
          <posx>100</posx>
          <posy>168</posy>
          <width>28</width>
          <height>28</height>
          <aspectratio>keep</aspectratio>
          <texture>$INFO[ListItem.Art(emote_3)]</texture>
          <visible>!String.IsEmpty(ListItem.Art(emote_3))</visible>
        </control>
        <control type="image" id="114">
          <posx>130</posx>
          <posy>168</posy>
          <width>28</width>
          <height>28</height>
          <aspectratio>keep</aspectratio>
          <texture>$INFO[ListItem.Art(emote_4)]</texture>
          <visible>!String.IsEmpty(ListItem.Art(emote_4))</visible>
        </control>
        <control type="image" id="115">
          <posx>160</posx>
          <posy>168</posy>
          <width>28</width>
          <height>28</height>
          <aspectratio>keep</aspectratio>
          <texture>$INFO[ListItem.Art(emote_5)]</texture>
          <visible>!String.IsEmpty(ListItem.Art(emote_5))</visible>
        </control>
      </itemlayout>
      <focusedlayout width="380" height="197">
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
          <height>140</height>
          <font>font13</font>
          <wrapmultiline>true</wrapmultiline>
          <label>$INFO[ListItem.Label2]</label>
        </control>
        <control type="image" id="110">
          <posx>10</posx>
          <posy>168</posy>
          <width>28</width>
          <height>28</height>
          <aspectratio>keep</aspectratio>
          <texture>$INFO[ListItem.Art(emote_0)]</texture>
          <visible>!String.IsEmpty(ListItem.Art(emote_0))</visible>
        </control>
        <control type="image" id="111">
          <posx>40</posx>
          <posy>168</posy>
          <width>28</width>
          <height>28</height>
          <aspectratio>keep</aspectratio>
          <texture>$INFO[ListItem.Art(emote_1)]</texture>
          <visible>!String.IsEmpty(ListItem.Art(emote_1))</visible>
        </control>
        <control type="image" id="112">
          <posx>70</posx>
          <posy>168</posy>
          <width>28</width>
          <height>28</height>
          <aspectratio>keep</aspectratio>
          <texture>$INFO[ListItem.Art(emote_2)]</texture>
          <visible>!String.IsEmpty(ListItem.Art(emote_2))</visible>
        </control>
        <control type="image" id="113">
          <posx>100</posx>
          <posy>168</posy>
          <width>28</width>
          <height>28</height>
          <aspectratio>keep</aspectratio>
          <texture>$INFO[ListItem.Art(emote_3)]</texture>
          <visible>!String.IsEmpty(ListItem.Art(emote_3))</visible>
        </control>
        <control type="image" id="114">
          <posx>130</posx>
          <posy>168</posy>
          <width>28</width>
          <height>28</height>
          <aspectratio>keep</aspectratio>
          <texture>$INFO[ListItem.Art(emote_4)]</texture>
          <visible>!String.IsEmpty(ListItem.Art(emote_4))</visible>
        </control>
        <control type="image" id="115">
          <posx>160</posx>
          <posy>168</posy>
          <width>28</width>
          <height>28</height>
          <aspectratio>keep</aspectratio>
          <texture>$INFO[ListItem.Art(emote_5)]</texture>
          <visible>!String.IsEmpty(ListItem.Art(emote_5))</visible>
        </control>
      </focusedlayout>
    </control>
  </controls>
</window>
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_addon_manifest.py -v`
Expected: PASS (full file — confirms the existing `test_chat_overlay_skin_xml_declares_message_list_control_id` and any global control-id-uniqueness checks still pass with the new ids added)

- [ ] **Step 5: Commit**

```bash
git add resources/skins/Default/1080i/script-twitch-center-chat-overlay.xml tests/test_addon_manifest.py
git commit -m "feat: add 6 emote image control slots to chat overlay skin layout"
```

---

### Task 5: Full suite run, changelog/version bump, live-test note

**Files:**
- Modify: `CHANGELOG.md` (new entry)
- Modify: `addon.xml` (version bump, per this repo's [[feedback_changelog_versioning]] convention)
- Modify: `TODO.md` (mark emote rendering follow-up done, if it was listed — check current file for wording, this design was newly added and TODO.md's EventSub entry doesn't yet mention it)

**Interfaces:** None — this task is verification and bookkeeping only.

- [ ] **Step 1: Run the full test suite**

Run: `pytest -v`
Expected: PASS, all tests (existing suite + Tasks 1-4's new tests), zero regressions.

- [ ] **Step 2: Bump version and changelog**

Read `addon.xml`'s current `version=` attribute and `CHANGELOG.md`'s top entry to match this repo's existing bump style (see e.g. commit `4fc382c chore: bump version to 0.16.0, changelog and TODO for the EventSub chat engine setting`). Add a new changelog entry describing: EventSub chat messages now show a row of real emote images below the text (up to 6 per message), IRC engine unaffected. Bump `addon.xml`'s version by one patch level.

- [ ] **Step 3: Commit**

```bash
git add CHANGELOG.md addon.xml
git commit -m "chore: bump version for EventSub emote rendering"
```

- [ ] **Step 4: Note remaining live-testing step**

This plan's automated tests cover extraction logic, art-slot assignment, and skin XML structure. Actual on-screen rendering (icon size/spacing/visibility against a live Twitch channel with real emotes) is NOT verified by automated tests, per the spec's own scope note. Live-test manually per this repo's Kodi-testing conventions ([[feedback_live_kodi_testing]]: clean-restart before testing, one `ExecuteAddon` per test) before considering this feature done end-to-end. No code change needed for this step — it is a manual verification checkpoint, not part of the commit.

## Self-Review Notes

- Spec coverage: `_extract_emotes` (Task 1), `_handle_payload` wiring (Task 2), `_build_message_item` art (Task 3), skin XML slots (Task 4), tests for all three Python components plus skin structure (Tasks 1-4), changelog/version bump (Task 5, per this repo's established convention though not in the spec itself) — all spec sections have a corresponding task. IRC-untouched guarantee is exercised implicitly (IRC's own test suite must stay green in Task 3's Step 4) rather than a dedicated new test, since the spec's error-handling section states the "no `emotes` key" path is exactly today's dict-`.get`-default behavior.
- No placeholders: every step has literal code/XML.
- Type consistency: `_extract_emotes` return shape (`{"id", "text", "url"}`) matches usage in `_build_message_item` (`emote["url"]`) and skin XML keys (`emote_0".."emote_5"`) throughout.
