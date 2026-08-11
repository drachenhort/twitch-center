# Discover Screen Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace `lib/windows/discover.py`'s no-op stub with a real Discover screen: browse
currently-live streams by any game (not just followed channels) via a top-games row, or free-text
search any channel by name. Add a "Discover" button on Home that opens it.

**Architecture:** `lib/twitch/api.py` gains one new function (`get_top_games`) and two real
implementations replacing stubs (`get_live_streams_by_game`, `search_channels`), all official Helix
calls following the exact `_get`/`TokenExpiredError` pattern every other `api.py` function already
uses. `lib/windows/discover.py` mirrors `lib/windows/home.py`'s structure closely (same
token-load/refresh/re-login flow, same `_show_error`/control-reset conventions) since both screens
need the same authenticated-Helix-call handling — but Discover's results list is fed by two
different Helix response shapes (stream objects vs. channel-search objects), so it gets two
separate `ListItem` builders instead of one.

**Tech Stack:** Python 3, `requests`, `pytest` + `unittest.mock`, existing `tests/kodi_stubs/`
harness (extended with edit-control text support).

## Global Constraints

- `lib/twitch/*` must have zero `xbmc*` imports — enforced by `tests/test_architecture.py`; none of
  this plan's `api.py` changes should need to touch that test.
- Every Helix call needs `client_id` — this plan's two replaced stubs (`get_live_streams_by_game`,
  `search_channels`) get the same signature-supersession treatment every other real `api.py`
  function already went through (adding `client_id` the original scaffold's guessed signature
  lacked).
- `search_channels` defaults to `live_only=True`.
- `lib/windows/discover.py` reuses the existing `auth.load_token`/`auth.refresh_access_token`/
  `auth.clear_token` token lifecycle exactly as `lib/windows/home.py` already does — no new token
  handling logic, just the same pattern applied to a second window.
- Clicking a result does nothing yet (playback still deferred) — do not implement it.
- Discover does not return to Home on Back — Back closes the addon, consistent with every existing
  window transition in this project (one-way).
- `pip install -r requirements-dev.txt && pytest` must pass after every task.
- No test makes a real network call.

---

## File Structure

```
lib/
  twitch/
    api.py                    # modify: add get_top_games, real get_live_streams_by_game/search_channels
  windows/
    discover.py                # modify: real implementation
    home.py                     # modify: add Discover button wiring
resources/
  skins/Default/1080i/
    script-twitch-center-discover.xml   # create
    script-twitch-center-home.xml        # modify: add Discover button
tests/
  kodi_stubs/
    xbmcgui.py                 # modify: ControlLabel gets getText/setText (edit-control stand-in)
  test_kodi_stubs.py            # modify: new tests for getText/setText
  twitch/
    test_api.py                 # modify: add tests for the three new/changed functions
  windows/
    test_discover_window.py      # create
    test_home_window.py           # modify: add Discover-button test
```

---

### Task 1: Extend Kodi stub with edit-control text support

**Files:**
- Modify: `tests/kodi_stubs/xbmcgui.py`
- Modify: `tests/test_kodi_stubs.py`

**Interfaces:**
- Produces: `ControlLabel.setText(text) -> None`, `ControlLabel.getText() -> str` — the stub's
  existing single generic control class (already standing in for labels, lists, and buttons)
  additionally stands in for Kodi's `ControlEdit`, reusing the same internal `_label` storage so
  `setText`/`getText` and `setLabel`/`getLabel` are interchangeable on the same instance (matches
  how the stub already unifies label/list/button behavior on one class).
- Consumed by: Task 3's `lib/windows/discover.py` (reads the search box's text).

- [ ] **Step 1: Write the failing test**

```python
# Append to tests/test_kodi_stubs.py

def test_xbmcgui_stub_control_settext_gettext_round_trip():
    import xbmcgui
    win = xbmcgui.WindowXML("dummy.xml", "/tmp")
    control = win.getControl(106)
    assert control.getText() == ""
    control.setText("elden ring")
    assert control.getText() == "elden ring"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_kodi_stubs.py -v`
Expected: FAIL — `ControlLabel` has no `getText`/`setText`.

- [ ] **Step 3: Add to `ControlLabel` in `tests/kodi_stubs/xbmcgui.py`**

Add these two methods to the existing `ControlLabel` class (anywhere among its other methods; every
other method — `setLabel`/`getLabel`/`addItems`/`reset`/`size`/`getSelectedItem`/`selectItem`/
`setVisible`/`isVisible` — stays exactly as-is):

```python
    def setText(self, text):
        self._label = text

    def getText(self):
        return self._label
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_kodi_stubs.py -v`
Expected: PASS (all existing tests plus the 1 new one).

- [ ] **Step 5: Run the full suite**

Run: `.venv/bin/pytest -v`
Expected: PASS — purely additive.

- [ ] **Step 6: Commit**

```bash
git add tests/kodi_stubs/xbmcgui.py tests/test_kodi_stubs.py
git commit -m "test: add getText/setText to ControlLabel stub for edit-control use"
```

---

### Task 2: Extend `lib/twitch/api.py` with top-games, streams-by-game, and channel search

**Files:**
- Modify: `lib/twitch/api.py`
- Modify: `tests/twitch/test_api.py`

**Interfaces:**
- Produces:
  - `api.get_top_games(access_token, client_id, first=20) -> list[dict]` — **new**. Each dict:
    `{"id": ..., "name": ...}`.
  - `api.get_live_streams_by_game(access_token, client_id, game_id, first=20) -> list[dict]` —
    replaces the existing `NotImplementedError` stub. Returns Twitch's `data` list as-is (stream
    objects: `user_id`, `user_login`, `user_name`, `game_name`, `title`, `viewer_count`,
    `thumbnail_url`, `started_at`, same shape `get_live_status` already returns).
  - `api.search_channels(access_token, client_id, query, live_only=True, first=20) -> list[dict]` —
    replaces the existing stub. Returns Twitch's `data` list as-is (channel-search objects:
    `broadcaster_login`, `display_name`, `id`, `is_live`, `game_name`, `thumbnail_url`, `title`,
    `started_at` — note: no `viewer_count`, and `thumbnail_url` here is a static image URL, not the
    `{width}x{height}`-placeholder form the stream-shaped endpoints return).
  - `get_games_for_channels` is **not** touched by this task — stays an untouched
    `NotImplementedError` stub, unrelated to this design.
- Consumed by: Task 3's `lib/windows/discover.py`.

- [ ] **Step 1: Write the failing tests**

```python
# Append to tests/twitch/test_api.py

def test_get_top_games_returns_id_and_name():
    body = {
        "data": [
            {"id": "509658", "name": "Just Chatting", "box_art_url": "https://example.invalid/1.jpg"},
            {"id": "21779", "name": "League of Legends", "box_art_url": "https://example.invalid/2.jpg"},
        ]
    }
    with patch.object(api.requests, "get", return_value=_response(body)) as mock_get:
        result = api.get_top_games("token", "client-id")
    assert result == [
        {"id": "509658", "name": "Just Chatting"},
        {"id": "21779", "name": "League of Legends"},
    ]
    assert mock_get.call_args.kwargs["params"]["first"] == 20


def test_get_top_games_raises_token_expired_on_401():
    with patch.object(api.requests, "get", return_value=_response({}, status_code=401)):
        with pytest.raises(api.TokenExpiredError):
            api.get_top_games("token", "client-id")


def test_get_live_streams_by_game_returns_data():
    body = {"data": [{"user_id": "1", "user_name": "A", "game_name": "Foo", "viewer_count": 10}]}
    with patch.object(api.requests, "get", return_value=_response(body)) as mock_get:
        result = api.get_live_streams_by_game("token", "client-id", "509658")
    assert result == body["data"]
    assert mock_get.call_args.kwargs["params"]["game_id"] == "509658"
    assert mock_get.call_args.kwargs["params"]["first"] == 20


def test_get_live_streams_by_game_raises_token_expired_on_401():
    with patch.object(api.requests, "get", return_value=_response({}, status_code=401)):
        with pytest.raises(api.TokenExpiredError):
            api.get_live_streams_by_game("token", "client-id", "509658")


def test_search_channels_returns_data_with_live_only_default():
    body = {
        "data": [
            {
                "broadcaster_login": "someone",
                "display_name": "Someone",
                "id": "999",
                "is_live": True,
                "game_name": "Foo",
                "thumbnail_url": "https://example.invalid/thumb.jpg",
            }
        ]
    }
    with patch.object(api.requests, "get", return_value=_response(body)) as mock_get:
        result = api.search_channels("token", "client-id", "someone")
    assert result == body["data"]
    params = mock_get.call_args.kwargs["params"]
    assert params["query"] == "someone"
    assert params["live_only"] is True
    assert params["first"] == 20


def test_search_channels_can_disable_live_only():
    body = {"data": []}
    with patch.object(api.requests, "get", return_value=_response(body)) as mock_get:
        api.search_channels("token", "client-id", "someone", live_only=False)
    assert mock_get.call_args.kwargs["params"]["live_only"] is False


def test_search_channels_raises_token_expired_on_401():
    with patch.object(api.requests, "get", return_value=_response({}, status_code=401)):
        with pytest.raises(api.TokenExpiredError):
            api.search_channels("token", "client-id", "someone")
```

This assumes `tests/twitch/test_api.py` already has `_response(json_body, status_code=200)` and the
`patch`/`pytest` imports from the existing test suite — verify these exist before appending (they
do, per the file's existing `get_current_user`/`get_followed_channels`/`get_live_status` tests); do
not redefine `_response`.

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/twitch/test_api.py -v`
Expected: FAIL — `get_top_games` doesn't exist; `get_live_streams_by_game`/`search_channels` raise
`NotImplementedError` with the old scaffold signatures (missing `client_id`).

- [ ] **Step 3: Modify `lib/twitch/api.py`**

Replace the three stub functions (`get_games_for_channels` stays untouched — only
`get_live_streams_by_game` and `search_channels` are replaced, and `get_top_games` is added new)
with:

```python
def get_top_games(access_token, client_id, first=20):
    """Return Twitch's current top-viewed games (Helix /games/top) as a list of
    {"id", "name"} dicts."""
    body = _get(HELIX_BASE + "/games/top", access_token, client_id, params={"first": first})
    return [{"id": game["id"], "name": game["name"]} for game in body["data"]]


def get_live_streams_by_game(access_token, client_id, game_id, first=20):
    """Return currently-live streams (Helix /streams?game_id=) for the given game_id -
    any streamer, not just followed channels."""
    body = _get(
        HELIX_BASE + "/streams",
        access_token,
        client_id,
        params={"game_id": game_id, "first": first},
    )
    return body["data"]


def search_channels(access_token, client_id, query, live_only=True, first=20):
    """Free-text channel search (Helix /search/channels) for the given query string.
    Defaults to only currently-live channels - this app is about finding something
    to watch now, not a general channel directory."""
    body = _get(
        HELIX_BASE + "/search/channels",
        access_token,
        client_id,
        params={"query": query, "live_only": live_only, "first": first},
    )
    return body["data"]
```

`get_games_for_channels`'s existing `NotImplementedError` stub stays exactly where it is in the
file, untouched.

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/twitch/test_api.py -v`
Expected: PASS (all existing tests plus the 7 new ones).

- [ ] **Step 5: Run the full suite**

Run: `.venv/bin/pytest -v`
Expected: PASS. `tests/test_architecture.py` must still pass — no new imports beyond `requests`.

- [ ] **Step 6: Commit**

```bash
git add lib/twitch/api.py tests/twitch/test_api.py
git commit -m "feat: implement top games, streams-by-game, and channel search in lib.twitch.api"
```

---

### Task 3: Discover screen skin layout and `lib/windows/discover.py`

**Files:**
- Create: `resources/skins/Default/1080i/script-twitch-center-discover.xml`
- Modify: `lib/windows/discover.py`
- Create: `tests/windows/test_discover_window.py`

**Interfaces:**
- Consumes: `api.get_top_games`, `api.get_live_streams_by_game`, `api.search_channels`,
  `api.TokenExpiredError` (Task 2); `auth.load_token`/`refresh_access_token`/`clear_token`/
  `save_token` (existing); `ControlLabel.getText`/`setText` (Task 1); `xbmcgui`/`xbmcaddon`/`xbmc`.
- Produces: `discover.DiscoverWindow` with control-id constants `RESULTS_LIST_ID = 101`,
  `EMPTY_LABEL_ID = 102`, `ERROR_LABEL_ID = 103`, `RELOGIN_BUTTON_ID = 104`, `GAMES_LIST_ID = 105`,
  `SEARCH_EDIT_ID = 106`, `SEARCH_BUTTON_ID = 107`; module-level helpers `_thumbnail_url`,
  `_build_stream_item(stream)`, `_build_channel_item(channel)`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/windows/test_discover_window.py
from unittest.mock import patch

import xbmcaddon
import xbmcgui

from lib.twitch import api
from lib.twitch.auth import save_token
from lib.windows.discover import (
    DiscoverWindow,
    _build_channel_item,
    _build_stream_item,
)

FakeAddon = xbmcaddon.Addon

TOP_GAMES = [
    {"id": "509658", "name": "Just Chatting"},
    {"id": "21779", "name": "League of Legends"},
]

STREAMS = [
    {
        "user_id": "1",
        "user_name": "Alice",
        "game_name": "Just Chatting",
        "viewer_count": 500,
        "thumbnail_url": "https://example.invalid/{width}x{height}.jpg",
    }
]

SEARCH_RESULTS = [
    {
        "id": "2",
        "display_name": "Bob",
        "game_name": "League of Legends",
        "is_live": True,
        "thumbnail_url": "https://example.invalid/bob.jpg",
    },
    {
        "id": "3",
        "display_name": "Carol",
        "game_name": "",
        "is_live": False,
        "thumbnail_url": "https://example.invalid/carol.jpg",
    },
]


def _addon_with_token(token):
    addon = FakeAddon()
    if token is not None:
        save_token(token, addon)
    return addon


def test_build_stream_item_sets_label2_and_thumbnail():
    item = _build_stream_item(STREAMS[0])
    assert item.getLabel() == "Alice"
    assert "Just Chatting" in item.getLabel2()
    assert "500" in item.getLabel2()
    assert item.getArt("thumb") == "https://example.invalid/320x180.jpg"
    assert item.getProperty("broadcaster_id") == "1"


def test_build_channel_item_live_shows_game_and_live_status():
    item = _build_channel_item(SEARCH_RESULTS[0])
    assert item.getLabel() == "Bob"
    assert "Live" in item.getLabel2()
    assert "League of Legends" in item.getLabel2()
    assert item.getArt("thumb") == "https://example.invalid/bob.jpg"
    assert item.getProperty("broadcaster_id") == "2"


def test_build_channel_item_offline_shows_offline():
    item = _build_channel_item(SEARCH_RESULTS[1])
    assert item.getLabel() == "Carol"
    assert item.getLabel2() == "Offline"


def test_oninit_populates_top_games():
    addon = _addon_with_token({"access_token": "tok", "refresh_token": "ref", "user_id": "u1"})
    with patch("xbmcaddon.Addon", return_value=addon), patch.object(
        api, "get_top_games", return_value=TOP_GAMES
    ):
        win = DiscoverWindow("script-twitch-center-discover.xml", "/tmp")
        win.onInit()
    games_control = win.getControl(DiscoverWindow.GAMES_LIST_ID)
    assert games_control.size() == 2
    labels = [games_control._items[i].getLabel() for i in range(2)]
    assert labels == ["Just Chatting", "League of Legends"]


def test_oninit_shows_relogin_when_no_token():
    addon = FakeAddon()
    with patch("xbmcaddon.Addon", return_value=addon):
        win = DiscoverWindow("script-twitch-center-discover.xml", "/tmp")
        win.onInit()
    assert win.getControl(DiscoverWindow.ERROR_LABEL_ID).getLabel() != ""


def test_oninit_shows_error_on_network_failure():
    import requests

    addon = _addon_with_token({"access_token": "tok", "refresh_token": "ref", "user_id": "u1"})
    with patch("xbmcaddon.Addon", return_value=addon), patch.object(
        api, "get_top_games", side_effect=requests.ConnectionError("boom")
    ):
        win = DiscoverWindow("script-twitch-center-discover.xml", "/tmp")
        win.onInit()
    assert win.getControl(DiscoverWindow.ERROR_LABEL_ID).getLabel() != ""


def test_selecting_a_game_populates_results_with_stream_items():
    addon = _addon_with_token({"access_token": "tok", "refresh_token": "ref", "user_id": "u1"})
    with patch("xbmcaddon.Addon", return_value=addon), patch.object(
        api, "get_top_games", return_value=TOP_GAMES
    ), patch.object(api, "get_live_streams_by_game", return_value=STREAMS):
        win = DiscoverWindow("script-twitch-center-discover.xml", "/tmp")
        win.onInit()
        games_control = win.getControl(DiscoverWindow.GAMES_LIST_ID)
        games_control.selectItem(0)
        win.setFocusId(DiscoverWindow.GAMES_LIST_ID)
        win.onAction(xbmcgui.Action(xbmcgui.ACTION_SELECT_ITEM))

    results_control = win.getControl(DiscoverWindow.RESULTS_LIST_ID)
    assert results_control.size() == 1
    assert results_control._items[0].getLabel() == "Alice"


def test_pressing_search_populates_results_with_channel_items():
    addon = _addon_with_token({"access_token": "tok", "refresh_token": "ref", "user_id": "u1"})
    with patch("xbmcaddon.Addon", return_value=addon), patch.object(
        api, "get_top_games", return_value=TOP_GAMES
    ), patch.object(api, "search_channels", return_value=SEARCH_RESULTS):
        win = DiscoverWindow("script-twitch-center-discover.xml", "/tmp")
        win.onInit()
        win.getControl(DiscoverWindow.SEARCH_EDIT_ID).setText("bob")
        win.setFocusId(DiscoverWindow.SEARCH_BUTTON_ID)
        win.onAction(xbmcgui.Action(xbmcgui.ACTION_SELECT_ITEM))

    results_control = win.getControl(DiscoverWindow.RESULTS_LIST_ID)
    assert results_control.size() == 2
    assert results_control._items[0].getLabel() == "Bob"


def test_pressing_search_with_empty_query_does_nothing():
    addon = _addon_with_token({"access_token": "tok", "refresh_token": "ref", "user_id": "u1"})
    with patch("xbmcaddon.Addon", return_value=addon), patch.object(
        api, "get_top_games", return_value=TOP_GAMES
    ), patch.object(api, "search_channels") as mock_search:
        win = DiscoverWindow("script-twitch-center-discover.xml", "/tmp")
        win.onInit()
        win.setFocusId(DiscoverWindow.SEARCH_BUTTON_ID)
        win.onAction(xbmcgui.Action(xbmcgui.ACTION_SELECT_ITEM))

    mock_search.assert_not_called()


def test_empty_search_results_show_nothing_found_message():
    addon = _addon_with_token({"access_token": "tok", "refresh_token": "ref", "user_id": "u1"})
    with patch("xbmcaddon.Addon", return_value=addon), patch.object(
        api, "get_top_games", return_value=TOP_GAMES
    ), patch.object(api, "search_channels", return_value=[]):
        win = DiscoverWindow("script-twitch-center-discover.xml", "/tmp")
        win.onInit()
        win.getControl(DiscoverWindow.SEARCH_EDIT_ID).setText("nobody")
        win.setFocusId(DiscoverWindow.SEARCH_BUTTON_ID)
        win.onAction(xbmcgui.Action(xbmcgui.ACTION_SELECT_ITEM))

    assert win.getControl(DiscoverWindow.EMPTY_LABEL_ID).getLabel() != ""
    assert win.getControl(DiscoverWindow.RESULTS_LIST_ID).size() == 0


def test_selecting_relogin_button_opens_login_window_and_closes_discover():
    addon = _addon_with_token({"access_token": "old", "refresh_token": "ref", "user_id": "u1"})

    with patch("xbmcaddon.Addon", return_value=addon), patch.object(
        api, "get_top_games", side_effect=api.TokenExpiredError()
    ), patch("lib.windows.discover.auth.refresh_access_token", return_value=None), patch(
        "lib.windows.discover.LoginWindow"
    ) as mock_login_window_cls:
        win = DiscoverWindow("script-twitch-center-discover.xml", "/tmp")
        win.onInit()
        win.setFocusId(DiscoverWindow.RELOGIN_BUTTON_ID)
        win.onAction(xbmcgui.Action(xbmcgui.ACTION_SELECT_ITEM))

    mock_login_window_cls.assert_called_once()
    mock_login_window_cls.return_value.show.assert_called_once()
    assert win.closed_event.is_set()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/windows/test_discover_window.py -v`
Expected: FAIL — `ModuleNotFoundError`/`ImportError` (`DiscoverWindow` doesn't have this interface
yet, `_build_stream_item`/`_build_channel_item` don't exist).

- [ ] **Step 3: Create `resources/skins/Default/1080i/script-twitch-center-discover.xml`**

```xml
<?xml version="1.0" encoding="UTF-8"?>
<window>
  <defaultcontrol always="true">105</defaultcontrol>
  <controls>
    <control type="label">
      <description>Title</description>
      <posx>60</posx>
      <posy>60</posy>
      <width>800</width>
      <height>50</height>
      <font>font32</font>
      <label>Discover</label>
    </control>
    <control type="edit" id="106">
      <description>Search query</description>
      <posx>60</posx>
      <posy>130</posy>
      <width>1200</width>
      <height>60</height>
      <font>font13</font>
      <label>Search channels...</label>
    </control>
    <control type="button" id="107">
      <description>Search</description>
      <posx>1280</posx>
      <posy>130</posy>
      <width>200</width>
      <height>60</height>
      <font>font13</font>
      <align>center</align>
      <label>Search</label>
    </control>
    <control type="list" id="105">
      <description>Top games</description>
      <posx>60</posx>
      <posy>220</posy>
      <width>1800</width>
      <height>90</height>
      <orientation>horizontal</orientation>
      <onup>105</onup>
      <ondown>101</ondown>
      <onleft>105</onleft>
      <onright>105</onright>
      <itemlayout width="220" height="80">
        <control type="label">
          <width>220</width>
          <height>80</height>
          <font>font13</font>
          <align>center</align>
          <aligny>center</aligny>
          <label>$INFO[ListItem.Label]</label>
        </control>
      </itemlayout>
      <focusedlayout width="220" height="80">
        <control type="label">
          <width>220</width>
          <height>80</height>
          <font>font13</font>
          <align>center</align>
          <aligny>center</aligny>
          <textcolor>ff9146ff</textcolor>
          <label>$INFO[ListItem.Label]</label>
        </control>
      </focusedlayout>
    </control>
    <control type="list" id="101">
      <description>Results</description>
      <posx>60</posx>
      <posy>330</posy>
      <width>1800</width>
      <height>670</height>
      <onup>105</onup>
      <ondown>101</ondown>
      <itemlayout width="1800" height="120">
        <control type="image">
          <posx>10</posx>
          <posy>0</posy>
          <width>160</width>
          <height>90</height>
          <texture>$INFO[ListItem.Art(thumb)]</texture>
          <aspectratio>scale</aspectratio>
        </control>
        <control type="label">
          <posx>190</posx>
          <width>1600</width>
          <height>60</height>
          <font>font20</font>
          <label>$INFO[ListItem.Label]</label>
        </control>
        <control type="label">
          <posx>190</posx>
          <posy>65</posy>
          <width>1600</width>
          <height>40</height>
          <font>font13</font>
          <label>$INFO[ListItem.Label2]</label>
        </control>
      </itemlayout>
      <focusedlayout width="1800" height="120">
        <control type="image">
          <posx>10</posx>
          <posy>0</posy>
          <width>160</width>
          <height>90</height>
          <texture>$INFO[ListItem.Art(thumb)]</texture>
          <aspectratio>scale</aspectratio>
        </control>
        <control type="label">
          <posx>190</posx>
          <width>1600</width>
          <height>60</height>
          <font>font20</font>
          <textcolor>ff9146ff</textcolor>
          <label>$INFO[ListItem.Label]</label>
        </control>
        <control type="label">
          <posx>190</posx>
          <posy>65</posy>
          <width>1600</width>
          <height>40</height>
          <font>font13</font>
          <label>$INFO[ListItem.Label2]</label>
        </control>
      </focusedlayout>
    </control>
    <control type="label" id="102">
      <description>Empty results message</description>
      <posx>560</posx>
      <posy>600</posy>
      <width>800</width>
      <height>60</height>
      <font>font20</font>
      <align>center</align>
      <label></label>
    </control>
    <control type="label" id="103">
      <description>Error / re-login message</description>
      <posx>560</posx>
      <posy>600</posy>
      <width>800</width>
      <height>60</height>
      <font>font20</font>
      <align>center</align>
      <label></label>
    </control>
    <control type="button" id="104">
      <description>Log in again</description>
      <posx>760</posx>
      <posy>680</posy>
      <width>400</width>
      <height>60</height>
      <font>font13</font>
      <align>center</align>
      <label>Log in again</label>
    </control>
  </controls>
</window>
```

- [ ] **Step 4: Write `lib/windows/discover.py`** (full replacement)

```python
"""Discover screen: browse live channels by any game, or search any channel by name."""
import threading

import xbmc
import xbmcaddon
import xbmcgui

from lib.twitch import api, auth
from lib.windows.login import LoginWindow

RESULTS_LIST_ID = 101
EMPTY_LABEL_ID = 102
ERROR_LABEL_ID = 103
RELOGIN_BUTTON_ID = 104
GAMES_LIST_ID = 105
SEARCH_EDIT_ID = 106
SEARCH_BUTTON_ID = 107

_MISSING_TOKEN_MESSAGE = "You're not logged in. Reopen the addon to log in."
_EMPTY_RESULTS_MESSAGE = "Nothing found."
_NETWORK_ERROR_MESSAGE = "Couldn't reach Twitch. Check your connection and reopen the addon."
_RELOGIN_MESSAGE = "Your session expired. Log in again to continue."


def _thumbnail_url(raw_url, width=320, height=180):
    return raw_url.replace("{width}", str(width)).replace("{height}", str(height))


def _build_stream_item(stream):
    item = xbmcgui.ListItem(stream["user_name"])
    item.setLabel2(stream["game_name"] + " - " + str(stream["viewer_count"]) + " viewers")
    item.setArt({"thumb": _thumbnail_url(stream["thumbnail_url"])})
    item.setProperty("broadcaster_id", stream["user_id"])
    return item


def _build_channel_item(channel):
    item = xbmcgui.ListItem(channel["display_name"])
    if channel.get("is_live"):
        item.setLabel2("Live - " + channel.get("game_name", ""))
    else:
        item.setLabel2("Offline")
    item.setArt({"thumb": channel.get("thumbnail_url", "")})
    item.setProperty("broadcaster_id", channel.get("id", ""))
    return item


class DiscoverWindow(xbmcgui.WindowXML):
    RESULTS_LIST_ID = RESULTS_LIST_ID
    EMPTY_LABEL_ID = EMPTY_LABEL_ID
    ERROR_LABEL_ID = ERROR_LABEL_ID
    RELOGIN_BUTTON_ID = RELOGIN_BUTTON_ID
    GAMES_LIST_ID = GAMES_LIST_ID
    SEARCH_EDIT_ID = SEARCH_EDIT_ID
    SEARCH_BUTTON_ID = SEARCH_BUTTON_ID

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.closed_event = threading.Event()

    def onInit(self):
        addon = xbmcaddon.Addon()
        client_id = addon.getSetting("client_id")
        token = auth.load_token(addon)
        if token is None:
            self._show_error(_MISSING_TOKEN_MESSAGE)
            return
        if not token.get("user_id"):
            auth.clear_token(addon)
            self._show_error(_RELOGIN_MESSAGE)
            return

        try:
            self._load_games(addon, client_id, token)
        except api.TokenExpiredError:
            self._handle_expired_token(addon, client_id, token)
        except Exception as exc:
            xbmc.log(
                "script.twitch.center: Discover screen failed to load: " + repr(exc),
                xbmc.LOGERROR,
            )
            self._show_error(_NETWORK_ERROR_MESSAGE)

    def _load_games(self, addon, client_id, token):
        games = api.get_top_games(token["access_token"], client_id)
        self._populate_games(games)

    def _handle_expired_token(self, addon, client_id, token):
        new_token = auth.refresh_access_token(client_id, token["refresh_token"])
        if new_token is None:
            auth.clear_token(addon)
            self._show_error(_RELOGIN_MESSAGE)
            return

        new_token["user_id"] = token.get("user_id")
        new_token["login"] = token.get("login")
        new_token["display_name"] = token.get("display_name")
        auth.save_token(new_token, addon)

        try:
            self._load_games(addon, client_id, new_token)
        except api.TokenExpiredError:
            auth.clear_token(addon)
            self._show_error(_RELOGIN_MESSAGE)
        except Exception as exc:
            xbmc.log(
                "script.twitch.center: Discover screen failed after token refresh: "
                + repr(exc),
                xbmc.LOGERROR,
            )
            self._show_error(_NETWORK_ERROR_MESSAGE)

    def _populate_games(self, games):
        self.getControl(self.RELOGIN_BUTTON_ID).setVisible(False)
        control = self.getControl(self.GAMES_LIST_ID)
        control.reset()
        items = []
        for game in games:
            item = xbmcgui.ListItem(game["name"])
            item.setProperty("game_id", game["id"])
            items.append(item)
        control.addItems(items)

    def _populate_results(self, items):
        self.getControl(self.EMPTY_LABEL_ID).setLabel("")
        self.getControl(self.ERROR_LABEL_ID).setLabel("")
        control = self.getControl(self.RESULTS_LIST_ID)
        control.reset()
        if not items:
            self.getControl(self.EMPTY_LABEL_ID).setLabel(_EMPTY_RESULTS_MESSAGE)
            return
        control.addItems(items)

    def _on_game_selected(self):
        selected = self.getControl(self.GAMES_LIST_ID).getSelectedItem()
        if selected is None:
            return
        addon = xbmcaddon.Addon()
        client_id = addon.getSetting("client_id")
        token = auth.load_token(addon)
        if token is None:
            return
        game_id = selected.getProperty("game_id")
        try:
            streams = api.get_live_streams_by_game(token["access_token"], client_id, game_id)
        except api.TokenExpiredError:
            self._handle_expired_token(addon, client_id, token)
            return
        except Exception as exc:
            xbmc.log(
                "script.twitch.center: Discover browse-by-game failed: " + repr(exc),
                xbmc.LOGERROR,
            )
            self._show_error(_NETWORK_ERROR_MESSAGE)
            return
        self._populate_results([_build_stream_item(stream) for stream in streams])

    def _on_search(self):
        query = self.getControl(self.SEARCH_EDIT_ID).getText()
        if not query:
            return
        addon = xbmcaddon.Addon()
        client_id = addon.getSetting("client_id")
        token = auth.load_token(addon)
        if token is None:
            return
        try:
            channels = api.search_channels(token["access_token"], client_id, query)
        except api.TokenExpiredError:
            self._handle_expired_token(addon, client_id, token)
            return
        except Exception as exc:
            xbmc.log("script.twitch.center: Discover search failed: " + repr(exc), xbmc.LOGERROR)
            self._show_error(_NETWORK_ERROR_MESSAGE)
            return
        self._populate_results([_build_channel_item(channel) for channel in channels])

    def _show_error(self, message):
        self.getControl(self.GAMES_LIST_ID).reset()
        self.getControl(self.RESULTS_LIST_ID).reset()
        self.getControl(self.EMPTY_LABEL_ID).setLabel("")
        self.getControl(self.ERROR_LABEL_ID).setLabel(message)
        self.getControl(self.RELOGIN_BUTTON_ID).setVisible(True)

    def onAction(self, action):
        if action.getId() in (xbmcgui.ACTION_PREVIOUS_MENU, xbmcgui.ACTION_NAV_BACK):
            self.close()
            self.closed_event.set()
        elif action.getId() == xbmcgui.ACTION_SELECT_ITEM:
            focus = self.getFocusId()
            if focus == self.RELOGIN_BUTTON_ID:
                self._open_login_window()
            elif focus == self.GAMES_LIST_ID:
                self._on_game_selected()
            elif focus == self.SEARCH_BUTTON_ID:
                self._on_search()

    def _open_login_window(self):
        addon = xbmcaddon.Addon()
        login_window = LoginWindow(
            "script-twitch-center-login.xml", addon.getAddonInfo("path"), "Default", "1080i"
        )
        login_window.show()
        self.close()
        self.closed_event.set()
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/windows/test_discover_window.py -v`
Expected: PASS (11 tests).

- [ ] **Step 6: Run the full suite**

Run: `.venv/bin/pytest -v`
Expected: PASS, full suite green.

- [ ] **Step 7: Commit**

```bash
git add resources/skins/Default/1080i/script-twitch-center-discover.xml lib/windows/discover.py tests/windows/test_discover_window.py
git commit -m "feat: implement Discover screen (browse by game, channel search)"
```

---

### Task 4: Wire a "Discover" button on `lib/windows/home.py`

**Files:**
- Modify: `resources/skins/Default/1080i/script-twitch-center-home.xml`
- Modify: `lib/windows/home.py`
- Modify: `tests/windows/test_home_window.py`

**Interfaces:**
- Consumes: `discover.DiscoverWindow` (Task 3).
- Produces: `HomeWindow.DISCOVER_BUTTON_ID = 106`; new `HomeWindow._open_discover_window()` method;
  `onAction` gains a branch routing focus on this button to it.

- [ ] **Step 1: Write the failing test**

```python
# Append to tests/windows/test_home_window.py

def test_selecting_discover_button_opens_discover_window_and_closes_home():
    addon = _addon_with_token({"access_token": "tok", "refresh_token": "ref", "user_id": "u1"})

    with patch("xbmcaddon.Addon", return_value=addon), patch.object(
        api, "get_followed_channels", return_value=FOLLOWED
    ), patch.object(api, "get_live_status", return_value=LIVE), patch.object(
        gql, "get_followed_live_games", return_value=[]
    ), patch(
        "lib.windows.home.DiscoverWindow"
    ) as mock_discover_window_cls:
        win = HomeWindow("script-twitch-center-home.xml", "/tmp")
        win.onInit()
        win.setFocusId(HomeWindow.DISCOVER_BUTTON_ID)
        win.onAction(xbmcgui.Action(xbmcgui.ACTION_SELECT_ITEM))

    mock_discover_window_cls.assert_called_once()
    mock_discover_window_cls.return_value.show.assert_called_once()
    assert win.closed_event.is_set()
```

This test needs `from lib.twitch import gql` already imported in the test file (it is, from the
followed-games-filter plan) and follows the exact same shape as the existing
`test_selecting_relogin_button_opens_login_window_and_closes_home` test, just targeting the new
button and `DiscoverWindow` instead.

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/windows/test_home_window.py -v`
Expected: FAIL — `HomeWindow.DISCOVER_BUTTON_ID` doesn't exist, `lib.windows.home.DiscoverWindow`
isn't imported there yet.

- [ ] **Step 3: Update `resources/skins/Default/1080i/script-twitch-center-home.xml`**

Add a new button, id `106` (the next free id after the existing 101-105), placed to the left of the
existing "Log in again" button (id 104, at `posx 760`) so they don't overlap:

```xml
    <control type="button" id="106">
      <description>Discover</description>
      <posx>60</posx>
      <posy>1010</posy>
      <width>300</width>
      <height>60</height>
      <font>font13</font>
      <align>center</align>
      <label>Discover</label>
    </control>
```

Insert this as a new sibling control, right after the existing `id="104"` button block and before
the closing `</controls>` tag.

- [ ] **Step 4: Update `lib/windows/home.py`**

Add the import and constant:

```python
from lib.windows.discover import DiscoverWindow
```

(add this line right after the existing `from lib.windows.login import LoginWindow` import)

```python
DISCOVER_BUTTON_ID = 106
```

(add this right after the existing `GAMES_LIST_ID = 105` line)

Add `DISCOVER_BUTTON_ID = DISCOVER_BUTTON_ID` to the `HomeWindow` class's existing block of
`= `-assigned class constants (alongside `CHANNEL_LIST_ID`, `EMPTY_LABEL_ID`, etc.).

Update `onAction` to add a branch for the new button:

```python
    def onAction(self, action):
        if action.getId() in (xbmcgui.ACTION_PREVIOUS_MENU, xbmcgui.ACTION_NAV_BACK):
            self.close()
            self.closed_event.set()
        elif action.getId() == xbmcgui.ACTION_SELECT_ITEM:
            if self.getFocusId() == self.RELOGIN_BUTTON_ID:
                self._open_login_window()
            elif self.getFocusId() == self.GAMES_LIST_ID:
                self._on_game_selected()
            elif self.getFocusId() == self.DISCOVER_BUTTON_ID:
                self._open_discover_window()
```

Add the new method right after `_open_login_window`:

```python
    def _open_discover_window(self):
        addon = xbmcaddon.Addon()
        discover_window = DiscoverWindow(
            "script-twitch-center-discover.xml", addon.getAddonInfo("path"), "Default", "1080i"
        )
        discover_window.show()
        self.close()
        self.closed_event.set()
```

Every other part of `home.py` (`_load_and_populate`, `_handle_expired_token`, `_populate_games`,
`_populate`, `_show_error`, `_on_game_selected`, `_open_login_window`) stays exactly as-is.

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/windows/test_home_window.py -v`
Expected: PASS (all pre-existing tests plus the 1 new one).

- [ ] **Step 6: Run the full suite**

Run: `.venv/bin/pytest -v`
Expected: PASS, full suite green (all 4 tasks combined).

- [ ] **Step 7: Commit**

```bash
git add resources/skins/Default/1080i/script-twitch-center-home.xml lib/windows/home.py tests/windows/test_home_window.py
git commit -m "feat: add Discover button to Home screen"
```

---

## Post-plan state

After Task 4, Home has a working "Discover" button that opens a screen showing Twitch's current top
games; picking one shows any live streams of it (not just followed channels); searching finds any
channel by name (live-only by default). Manually verify in real Kodi before considering this done —
specifically confirm the `<edit>` control's virtual-keyboard behavior works as expected when
focused (this is the first `<edit>` control this project has used for anything other than the
already-tested device-code display, and Kodi's on-screen-keyboard interaction with `getText()` at
runtime is not something the automated suite can exercise) — the same category of gap the login and
Home screens' own real-Kodi verification passes already caught issues in before.

Out of scope, still deferred: clicking a result to play it, returning to Home from Discover
(Back closes the addon), category/game box art, pagination beyond Helix's default page size.
