# Followed Games Filter Row Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a row of the user's real followed games (fetched via Twitch's unofficial internal
GraphQL API) above the Home screen's channel list. Selecting a game filters the channel list to
live followed channels playing it; selecting "All" clears the filter.

**Architecture:** A new `lib/twitch/gql.py` module (pure Python, zero `xbmc*` imports, matching the
existing `lib/twitch/*` boundary) wraps the single verified GQL call, best-effort by design —
returns `[]` on any failure rather than raising. `lib/windows/home.py` calls it alongside the
existing official-Helix followed-channels/live-status fetch, caches all three results on `self` for
in-memory re-filtering, and adds a new games-row list control with click-to-filter behavior. The
existing Kodi stub's `ControlLabel.getSelectedItem()` (currently hardcoded to always return index 0)
needs generalizing to track a real selected index, since this is the first feature that needs to
read back which list item a user actually picked.

**Tech Stack:** Python 3, `requests`, `pytest` + `unittest.mock`, existing `tests/kodi_stubs/`
harness (extended with selectable-item tracking).

## Global Constraints

- `lib/twitch/*` must have zero `xbmc*` imports — enforced by `tests/test_architecture.py`;
  `gql.py` should import only `requests`.
- `gql.get_followed_live_games` must never raise — network error, non-200, or unexpected response
  shape all return `[]`. This is deliberate: the response field names
  (`data.currentUser.followedGames.nodes[].{id,name,displayName}`) are inferred from Twitch's
  typical GraphQL conventions, **not independently verified** (see the design spec's "Known
  limitation" section) — only the request shape (operation name, persisted-query hash, variables)
  was captured directly from Twitch's own web client.
- Exact verified request values (do not alter):
  - URL: `https://gql.twitch.tv/gql`
  - Operation name: `FollowingGames_CurrentUser`
  - Persisted query hash: `f3c5d45175d623ed3d5ff4ca4c7de379ea6a1a4852236087dc1b81b7dbfd3114`
  - Variables: `{"limit": <int>, "type": "LIVE"}`
  - Headers: `Client-Id: kimne78kx3ncx6brgo4mv6wki5h1ko` (Twitch's public web client ID, distinct
    from our registered Helix `client_id` setting), `Authorization: OAuth <access_token>`
- A failure of `gql.get_followed_live_games` must NOT be treated as a Home-screen error — the
  channel list must still populate normally from the existing official-Helix data path.
- `pip install -r requirements-dev.txt && pytest` must pass after every task.
- No test makes a real network call.

---

## File Structure

```
lib/
  twitch/
    gql.py                    # create: unofficial GQL client
  windows/
    home.py                   # modify: games row, caching, filter-on-select
resources/
  skins/Default/1080i/
    script-twitch-center-home.xml   # modify: add games row list control, reflow layout
tests/
  kodi_stubs/
    xbmcgui.py                 # modify: ControlLabel gets real selected-index tracking
  test_kodi_stubs.py            # modify: new tests for selection tracking
  twitch/
    test_gql.py                 # create
  windows/
    test_home_window.py         # modify: fix 4 pre-existing tests that would otherwise hit real network; add new tests
```

---

### Task 1: Extend Kodi stub with real selected-item tracking

**Files:**
- Modify: `tests/kodi_stubs/xbmcgui.py`
- Modify: `tests/test_kodi_stubs.py`

**Interfaces:**
- Produces: `ControlLabel.selectItem(index) -> None` (test-setup method, mirrors the existing
  `WindowXML.setFocusId` pattern — production code never calls this, only tests simulating "user
  has this item highlighted"); `ControlLabel.getSelectedItem()` now returns the item at the
  tracked index (clamped to the last valid index if items shrank), not always index 0;
  `ControlLabel.reset()` now also resets the selected index to 0.
- Consumed by: Task 3's `lib/windows/home.py` (reads the games list's selected item) and its tests.

- [ ] **Step 1: Write the failing tests**

```python
# Append to tests/test_kodi_stubs.py

def test_xbmcgui_stub_control_selectitem_changes_selected_item():
    import xbmcgui
    win = xbmcgui.WindowXML("dummy.xml", "/tmp")
    control = win.getControl(101)
    item1 = xbmcgui.ListItem("First")
    item2 = xbmcgui.ListItem("Second")
    control.addItems([item1, item2])
    assert control.getSelectedItem() is item1
    control.selectItem(1)
    assert control.getSelectedItem() is item2


def test_xbmcgui_stub_control_reset_clears_selection():
    import xbmcgui
    win = xbmcgui.WindowXML("dummy.xml", "/tmp")
    control = win.getControl(101)
    control.addItems([xbmcgui.ListItem("A"), xbmcgui.ListItem("B")])
    control.selectItem(1)
    control.reset()
    assert control.getSelectedItem() is None
    control.addItems([xbmcgui.ListItem("C")])
    assert control.getSelectedItem().getLabel() == "C"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_kodi_stubs.py -v`
Expected: FAIL — `test_xbmcgui_stub_control_selectitem_changes_selected_item` fails because
`getSelectedItem()` currently always returns index 0 regardless of `selectItem` (which doesn't
exist yet, so this raises `AttributeError`).

- [ ] **Step 3: Update `tests/kodi_stubs/xbmcgui.py`**

Replace the `ControlLabel` class's `__init__`, `getSelectedItem`, and `reset` (keep every other
method — `setLabel`/`getLabel`/`addItems`/`size`/`setVisible`/`isVisible` — unchanged), and add
`selectItem`:

```python
class ControlLabel:
    def __init__(self):
        self._label = ""
        self._items = []
        self._visible = True
        self._selected_index = 0

    def setLabel(self, text):
        self._label = text

    def getLabel(self):
        return self._label

    def addItems(self, items):
        self._items.extend(items)

    def reset(self):
        self._items = []
        self._selected_index = 0

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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_kodi_stubs.py -v`
Expected: PASS (all existing tests plus the 2 new ones).

- [ ] **Step 5: Run the full suite**

Run: `.venv/bin/pytest -v`
Expected: PASS — this stub change is additive/behavior-preserving for every existing single-item
list use (Home's channel list never previously called `selectItem`, so `getSelectedItem()`
continues returning index 0 — i.e. whatever was added first — for all pre-existing tests).

- [ ] **Step 6: Commit**

```bash
git add tests/kodi_stubs/xbmcgui.py tests/test_kodi_stubs.py
git commit -m "test: track real selected index in ControlLabel stub"
```

---

### Task 2: Implement `lib/twitch/gql.py`

**Files:**
- Create: `lib/twitch/gql.py`
- Create: `tests/twitch/test_gql.py`

**Interfaces:**
- Produces:
  - `gql.GQL_URL = "https://gql.twitch.tv/gql"`
  - `gql.WEB_CLIENT_ID = "kimne78kx3ncx6brgo4mv6wki5h1ko"`
  - `gql.get_followed_live_games(access_token, limit=100) -> list[dict]` — each dict has `id`,
    `name`, `displayName`. Returns `[]` on any failure. Never raises.
- Consumed by: Task 3's `lib/windows/home.py`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/twitch/test_gql.py
from unittest.mock import MagicMock, patch

import requests

from lib.twitch import gql


def _response(json_body, status_code=200):
    response = MagicMock()
    response.status_code = status_code
    response.json.return_value = json_body
    return response


def test_get_followed_live_games_returns_parsed_list_on_success():
    body = [
        {
            "data": {
                "currentUser": {
                    "followedGames": {
                        "nodes": [
                            {"id": "1", "name": "just-chatting", "displayName": "Just Chatting"},
                            {"id": "2", "name": "programming", "displayName": "Programming"},
                        ]
                    }
                }
            }
        }
    ]
    with patch.object(gql.requests, "post", return_value=_response(body)) as mock_post:
        result = gql.get_followed_live_games("access-token")
    assert result == [
        {"id": "1", "name": "just-chatting", "displayName": "Just Chatting"},
        {"id": "2", "name": "programming", "displayName": "Programming"},
    ]
    headers = mock_post.call_args.kwargs["headers"]
    assert headers["Client-Id"] == gql.WEB_CLIENT_ID
    assert headers["Authorization"] == "OAuth access-token"


def test_get_followed_live_games_sends_expected_query_and_variables():
    body = [{"data": {"currentUser": {"followedGames": {"nodes": []}}}}]
    with patch.object(gql.requests, "post", return_value=_response(body)) as mock_post:
        gql.get_followed_live_games("access-token", limit=50)
    payload = mock_post.call_args.kwargs["json"]
    assert payload[0]["operationName"] == "FollowingGames_CurrentUser"
    assert payload[0]["variables"] == {"limit": 50, "type": "LIVE"}
    assert (
        payload[0]["extensions"]["persistedQuery"]["sha256Hash"]
        == "f3c5d45175d623ed3d5ff4ca4c7de379ea6a1a4852236087dc1b81b7dbfd3114"
    )


def test_get_followed_live_games_returns_empty_list_on_network_error():
    with patch.object(gql.requests, "post", side_effect=requests.ConnectionError("boom")):
        result = gql.get_followed_live_games("access-token")
    assert result == []


def test_get_followed_live_games_returns_empty_list_on_non_200():
    with patch.object(gql.requests, "post", return_value=_response({}, status_code=401)):
        result = gql.get_followed_live_games("access-token")
    assert result == []


def test_get_followed_live_games_returns_empty_list_on_unexpected_shape():
    with patch.object(
        gql.requests, "post", return_value=_response({"unexpected": "shape"})
    ):
        result = gql.get_followed_live_games("access-token")
    assert result == []


def test_get_followed_live_games_returns_empty_list_on_missing_nodes_key():
    body = [{"data": {"currentUser": {"followedGames": {}}}}]
    with patch.object(gql.requests, "post", return_value=_response(body)):
        result = gql.get_followed_live_games("access-token")
    assert result == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/twitch/test_gql.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'lib.twitch.gql'`.

- [ ] **Step 3: Write `lib/twitch/gql.py`**

```python
"""Twitch's unofficial internal GraphQL API. No xbmc* imports - pure Python.

Unofficial/undocumented - same risk tier as lib/twitch/stream.py's playback
resolution: uses Twitch's public web client ID, not our registered Helix
client_id, and can break without notice if Twitch changes its persisted-query
hash or response shape. Every function here is best-effort: failures return
an empty result rather than raising, since this data is decoration
(a filter convenience) on top of the official-Helix-backed channel list, not
something the rest of Home should ever fail over."""
import requests

GQL_URL = "https://gql.twitch.tv/gql"
WEB_CLIENT_ID = "kimne78kx3ncx6brgo4mv6wki5h1ko"

_FOLLOWING_GAMES_QUERY_HASH = "f3c5d45175d623ed3d5ff4ca4c7de379ea6a1a4852236087dc1b81b7dbfd3114"


def get_followed_live_games(access_token, limit=100):
    """Return the user's followed games that currently have live viewers, as
    a list of {"id", "name", "displayName"} dicts. Best-effort: returns []
    on any failure (network error, non-200, unexpected response shape) -
    never raises. The response field names here are inferred from Twitch's
    typical GraphQL naming conventions and have not been independently
    confirmed against a real captured response (the request shape - operation
    name, persisted-query hash, variables - was captured directly from
    Twitch's own web client; the response shape was not, per
    docs/superpowers/specs/2026-08-11-followed-games-filter-design.md's
    "Known limitation" section). Defensive parsing means a wrong guess about
    field names degrades to an empty list rather than crashing."""
    try:
        response = requests.post(
            GQL_URL,
            json=[
                {
                    "operationName": "FollowingGames_CurrentUser",
                    "variables": {"limit": limit, "type": "LIVE"},
                    "extensions": {
                        "persistedQuery": {
                            "version": 1,
                            "sha256Hash": _FOLLOWING_GAMES_QUERY_HASH,
                        }
                    },
                }
            ],
            headers={
                "Client-Id": WEB_CLIENT_ID,
                "Authorization": "OAuth " + access_token,
            },
            timeout=10,
        )
    except requests.RequestException:
        return []

    if response.status_code != 200:
        return []

    try:
        body = response.json()
        nodes = body[0]["data"]["currentUser"]["followedGames"]["nodes"]
        return [
            {"id": node["id"], "name": node["name"], "displayName": node["displayName"]}
            for node in nodes
        ]
    except (ValueError, KeyError, IndexError, TypeError):
        return []
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/twitch/test_gql.py -v`
Expected: PASS (6 tests).

- [ ] **Step 5: Run the full suite**

Run: `.venv/bin/pytest -v`
Expected: PASS. `tests/test_architecture.py` must still pass — `gql.py` imports only `requests`.

- [ ] **Step 6: Commit**

```bash
git add lib/twitch/gql.py tests/twitch/test_gql.py
git commit -m "feat: implement unofficial followed-live-games GQL client"
```

---

### Task 3: Games row skin layout and `lib/windows/home.py` integration

**Files:**
- Modify: `resources/skins/Default/1080i/script-twitch-center-home.xml`
- Modify: `lib/windows/home.py`
- Modify: `tests/windows/test_home_window.py`

**Interfaces:**
- Consumes: `gql.get_followed_live_games` (Task 2); `ControlLabel.selectItem`/generalized
  `getSelectedItem` (Task 1); existing `api`/`auth` interfaces (unchanged).
- Produces: `HomeWindow.GAMES_LIST_ID = 105`; `HomeWindow` caches `self._followed`, `self._live`,
  `self._games`, `self._selected_game` (all set in `__init__` to empty defaults, updated on each
  successful load); `_populate(followed, live_list, game_filter=None)` gains the optional filter
  parameter; new methods `_populate_games(games)` and `_on_game_selected()`.

- [ ] **Step 1: Fix the 4 pre-existing tests that would otherwise hit real network, then write the new failing tests**

`lib/windows/home.py`'s `_load_and_populate` will call `gql.get_followed_live_games` on every
successful load once this task's code change lands. Four pre-existing tests in
`tests/windows/test_home_window.py` reach a successful load without mocking it:
`test_oninit_populates_list_on_success`, `test_oninit_shows_empty_state_when_no_followed_channels`,
`test_oninit_refreshes_token_and_retries_on_expiry`, `test_populate_hides_relogin_button_on_success`.
(The other 10 pre-existing tests all fail or short-circuit before reaching a successful load — via
an early-return missing-token/no-user-id path, or an exception from `get_followed_channels` — so
`gql.get_followed_live_games` is never called in them; verify this by reading each one rather than
assuming, the same way the device-code-login and Home-screen plans' earlier task briefs required.)

Add `from lib.twitch import gql` to this test file's imports (alongside the existing `from
lib.twitch import api`). Then add `patch.object(gql, "get_followed_live_games", return_value=[])`
to each of the four `with patch(...)` blocks in those four tests — for example,
`test_oninit_populates_list_on_success` becomes:

```python
def test_oninit_populates_list_on_success():
    addon = _addon_with_token({"access_token": "tok", "refresh_token": "ref", "user_id": "u1"})
    with patch("xbmcaddon.Addon", return_value=addon), patch.object(
        api, "get_followed_channels", return_value=FOLLOWED
    ), patch.object(api, "get_live_status", return_value=LIVE), patch.object(
        gql, "get_followed_live_games", return_value=[]
    ):
        win = HomeWindow("script-twitch-center-home.xml", "/tmp")
        win.onInit()
    control = win.getControl(HomeWindow.CHANNEL_LIST_ID)
    assert control.size() == 3
```

Apply the same `patch.object(gql, "get_followed_live_games", return_value=[])` addition to the
other three tests' `with` blocks (each already has a multi-context-manager `with patch(...),
patch.object(...), ...:` block — add this as one more entry in that same `with`, don't nest a
separate `with` block). No assertions in these four tests need to change — they're only being kept
from making a real network call, not testing games-row behavior themselves.

Then add these new tests to the same file:

```python
GAMES = [
    {"id": "10", "name": "just-chatting", "displayName": "Just Chatting"},
    {"id": "20", "name": "programming", "displayName": "Programming"},
]


def test_oninit_populates_games_row_with_all_plus_followed_games():
    addon = _addon_with_token({"access_token": "tok", "refresh_token": "ref", "user_id": "u1"})
    with patch("xbmcaddon.Addon", return_value=addon), patch.object(
        api, "get_followed_channels", return_value=FOLLOWED
    ), patch.object(api, "get_live_status", return_value=LIVE), patch.object(
        gql, "get_followed_live_games", return_value=GAMES
    ):
        win = HomeWindow("script-twitch-center-home.xml", "/tmp")
        win.onInit()
    games_control = win.getControl(HomeWindow.GAMES_LIST_ID)
    assert games_control.size() == 3
    labels = [games_control._items[i].getLabel() for i in range(games_control.size())]
    assert labels == ["All", "Just Chatting", "Programming"]


def test_oninit_games_row_empty_when_gql_fails():
    addon = _addon_with_token({"access_token": "tok", "refresh_token": "ref", "user_id": "u1"})
    with patch("xbmcaddon.Addon", return_value=addon), patch.object(
        api, "get_followed_channels", return_value=FOLLOWED
    ), patch.object(api, "get_live_status", return_value=LIVE), patch.object(
        gql, "get_followed_live_games", return_value=[]
    ):
        win = HomeWindow("script-twitch-center-home.xml", "/tmp")
        win.onInit()
    games_control = win.getControl(HomeWindow.GAMES_LIST_ID)
    assert games_control.size() == 1
    assert games_control._items[0].getLabel() == "All"
    channel_control = win.getControl(HomeWindow.CHANNEL_LIST_ID)
    assert channel_control.size() == 3


def test_selecting_a_game_filters_channel_list_to_matching_live_channels():
    addon = _addon_with_token({"access_token": "tok", "refresh_token": "ref", "user_id": "u1"})
    with patch("xbmcaddon.Addon", return_value=addon), patch.object(
        api, "get_followed_channels", return_value=FOLLOWED
    ), patch.object(api, "get_live_status", return_value=LIVE), patch.object(
        gql, "get_followed_live_games", return_value=GAMES
    ):
        win = HomeWindow("script-twitch-center-home.xml", "/tmp")
        win.onInit()
        games_control = win.getControl(HomeWindow.GAMES_LIST_ID)
        games_control.selectItem(1)  # "Just Chatting" (Bob, per LIVE fixture)
        win.setFocusId(HomeWindow.GAMES_LIST_ID)
        win.onAction(xbmcgui.Action(xbmcgui.ACTION_SELECT_ITEM))

    channel_control = win.getControl(HomeWindow.CHANNEL_LIST_ID)
    assert channel_control.size() == 1
    assert channel_control._items[0].getLabel() == "Bob"


def test_selecting_all_clears_the_filter():
    addon = _addon_with_token({"access_token": "tok", "refresh_token": "ref", "user_id": "u1"})
    with patch("xbmcaddon.Addon", return_value=addon), patch.object(
        api, "get_followed_channels", return_value=FOLLOWED
    ), patch.object(api, "get_live_status", return_value=LIVE), patch.object(
        gql, "get_followed_live_games", return_value=GAMES
    ):
        win = HomeWindow("script-twitch-center-home.xml", "/tmp")
        win.onInit()
        games_control = win.getControl(HomeWindow.GAMES_LIST_ID)
        games_control.selectItem(1)
        win.setFocusId(HomeWindow.GAMES_LIST_ID)
        win.onAction(xbmcgui.Action(xbmcgui.ACTION_SELECT_ITEM))
        games_control.selectItem(0)  # "All"
        win.onAction(xbmcgui.Action(xbmcgui.ACTION_SELECT_ITEM))

    channel_control = win.getControl(HomeWindow.CHANNEL_LIST_ID)
    assert channel_control.size() == 3


def test_selecting_a_game_with_no_live_matches_shows_no_matches_message():
    addon = _addon_with_token({"access_token": "tok", "refresh_token": "ref", "user_id": "u1"})
    games_with_unmatched = GAMES + [{"id": "30", "name": "some-other-game", "displayName": "Some Other Game"}]
    with patch("xbmcaddon.Addon", return_value=addon), patch.object(
        api, "get_followed_channels", return_value=FOLLOWED
    ), patch.object(api, "get_live_status", return_value=LIVE), patch.object(
        gql, "get_followed_live_games", return_value=games_with_unmatched
    ):
        win = HomeWindow("script-twitch-center-home.xml", "/tmp")
        win.onInit()
        games_control = win.getControl(HomeWindow.GAMES_LIST_ID)
        games_control.selectItem(3)  # "Some Other Game" - no live followed channel plays it
        win.setFocusId(HomeWindow.GAMES_LIST_ID)
        win.onAction(xbmcgui.Action(xbmcgui.ACTION_SELECT_ITEM))

    channel_control = win.getControl(HomeWindow.CHANNEL_LIST_ID)
    assert channel_control.size() == 0
    assert win.getControl(HomeWindow.EMPTY_LABEL_ID).getLabel() != ""
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/windows/test_home_window.py -v`
Expected: FAIL — `HomeWindow.GAMES_LIST_ID` doesn't exist, `_populate` doesn't accept `game_filter`,
`onAction` doesn't route games-list selection.

- [ ] **Step 3: Update `resources/skins/Default/1080i/script-twitch-center-home.xml`**

Insert a new games-row list control between the title and the existing channel list, reposition
the channel list down/shorter, and rewire the channel list's `<onup>` to reach the new row:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<window>
  <defaultcontrol always="true">101</defaultcontrol>
  <controls>
    <control type="label">
      <description>Title</description>
      <posx>60</posx>
      <posy>60</posy>
      <width>800</width>
      <height>50</height>
      <font>font32</font>
      <label>Twitch Center</label>
    </control>
    <control type="list" id="105">
      <description>Followed games filter</description>
      <posx>60</posx>
      <posy>130</posy>
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
      <description>Followed channels</description>
      <posx>60</posx>
      <posy>240</posy>
      <width>1800</width>
      <height>760</height>
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
      <description>Empty followed list message</description>
      <posx>560</posx>
      <posy>460</posy>
      <width>800</width>
      <height>60</height>
      <font>font20</font>
      <align>center</align>
      <label></label>
    </control>
    <control type="label" id="103">
      <description>Error / re-login message</description>
      <posx>560</posx>
      <posy>460</posy>
      <width>800</width>
      <height>60</height>
      <font>font20</font>
      <align>center</align>
      <label></label>
    </control>
    <control type="button" id="104">
      <description>Log in again</description>
      <posx>760</posx>
      <posy>1010</posy>
      <width>400</width>
      <height>60</height>
      <font>font13</font>
      <align>center</align>
      <label>Log in again</label>
    </control>
  </controls>
</window>
```

- [ ] **Step 4: Update `lib/windows/home.py`**

Add `gql` to the existing `from lib.twitch import api, auth` import line (making it
`from lib.twitch import api, auth, gql`). Add the new control-id constant and message constant
near the top:

```python
GAMES_LIST_ID = 105
```

```python
_ALL_GAMES_LABEL = "All"
_NO_MATCHES_MESSAGE = "None of your live followed channels are playing this game right now."
```

Add `GAMES_LIST_ID = GAMES_LIST_ID` to the `HomeWindow` class's existing block of `= `-assigned
class constants (alongside `CHANNEL_LIST_ID`, `EMPTY_LABEL_ID`, etc.).

Update `__init__` to also initialize the new cache attributes:

```python
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.closed_event = threading.Event()
        self._followed = []
        self._live = []
        self._games = []
        self._selected_game = None
```

Update `_load_and_populate` to also fetch and cache games, and populate the games row:

```python
    def _load_and_populate(self, addon, client_id, token):
        followed = api.get_followed_channels(token["access_token"], client_id, token["user_id"])
        broadcaster_ids = [c["broadcaster_id"] for c in followed]
        live_list = api.get_live_status(token["access_token"], client_id, broadcaster_ids)
        games = gql.get_followed_live_games(token["access_token"])
        self._followed = followed
        self._live = live_list
        self._games = games
        self._selected_game = None
        self._populate_games(games)
        self._populate(followed, live_list)
```

Add the new `_populate_games` method (place it right before `_populate`):

```python
    def _populate_games(self, games):
        control = self.getControl(self.GAMES_LIST_ID)
        control.reset()
        all_item = xbmcgui.ListItem(_ALL_GAMES_LABEL)
        items = [all_item]
        for game in games:
            item = xbmcgui.ListItem(game["displayName"])
            item.setProperty("game_name", game["name"])
            items.append(item)
        control.addItems(items)
```

Update `_populate` to accept an optional filter and use a distinct message when a filter produces
zero results (vs. the existing "not following anyone yet" message for a genuinely empty followed
list):

```python
    def _populate(self, followed, live_list, game_filter=None):
        self.getControl(self.RELOGIN_BUTTON_ID).setVisible(False)
        control = self.getControl(self.CHANNEL_LIST_ID)
        control.reset()
        if not followed:
            self.getControl(self.EMPTY_LABEL_ID).setLabel(_EMPTY_FOLLOWED_MESSAGE)
            return
        live, offline = _merge_channels(followed, live_list)
        if game_filter is not None:
            live = [(channel, stream) for channel, stream in live if stream["game_name"] == game_filter]
            offline = []
        items = [_build_list_item(channel, stream) for channel, stream in live]
        items += [_build_list_item(channel) for channel in offline]
        if not items:
            self.getControl(self.EMPTY_LABEL_ID).setLabel(_NO_MATCHES_MESSAGE)
            return
        control.addItems(items)
```

Update `_show_error` to also clear the games row, so a stale games list can't linger alongside an
error state:

```python
    def _show_error(self, message):
        self.getControl(self.GAMES_LIST_ID).reset()
        self.getControl(self.ERROR_LABEL_ID).setLabel(message)
        self.getControl(self.RELOGIN_BUTTON_ID).setVisible(True)
```

Add the new `_on_game_selected` method (place it near `_open_login_window`):

```python
    def _on_game_selected(self):
        selected = self.getControl(self.GAMES_LIST_ID).getSelectedItem()
        if selected is None:
            return
        game_name = selected.getProperty("game_name")
        self._selected_game = game_name or None
        self._populate(self._followed, self._live, game_filter=self._selected_game)
```

Update `onAction` to route `ACTION_SELECT_ITEM` based on which control has focus:

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
```

Every other method (`_handle_expired_token`, `_open_login_window`) stays exactly as-is —
`_handle_expired_token` already calls `_load_and_populate`, which now transitively includes the
games fetch, so no separate change is needed there.

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/windows/test_home_window.py -v`
Expected: PASS (14 pre-existing tests, all green including the 4 fixed ones, plus 5 new tests = 19
total in this file).

- [ ] **Step 6: Run the full suite**

Run: `.venv/bin/pytest -v`
Expected: PASS, full suite green (all 3 tasks combined).

- [ ] **Step 7: Commit**

```bash
git add resources/skins/Default/1080i/script-twitch-center-home.xml lib/windows/home.py tests/windows/test_home_window.py
git commit -m "feat: add followed-games filter row to Home screen"
```

---

## Post-plan state

After Task 3, Home shows a row of the user's real followed live games above the channel list;
selecting one filters the channel list to live followed channels playing it, "All" clears the
filter. Manually verify in real Kodi before considering this done — specifically, capture the
actual `FollowingGames_CurrentUser` response shape from a real request (e.g. by re-running the
browser-based network capture used to design this plan, or inspecting `xbmc.log` if
`gql.get_followed_live_games` is temporarily instrumented to log a parse failure) and correct
`lib/twitch/gql.py`'s response-parsing field names if they don't match — the design spec's "Known
limitation" section flags this as the one genuinely unverified piece of this plan. If the shape is
wrong, the automated suite (which tests against the *assumed* shape) will stay green while the
real feature silently shows an empty games row — this is exactly the class of gap the real-Kodi
verification pass exists to catch.

Out of scope, still deferred: game box art, any followed-games `type` other than `"LIVE"`,
free-text search (the already-deferred Discover screen).
