# Persistent Window Architecture Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fold Login, Menu, Live Streams, Discover, and Search into one persistent `xbmcgui.WindowXML` (`MainWindow`) so no second top-level Kodi window is ever constructed during a session — eliminating the native window-manager revert bug at its source. Adds a new landing Menu view as the entry point after Login.

**Architecture:** One skin file (`script-twitch-center-main.xml`) with five `<control type="group">` blocks. `MainWindow` toggles group visibility and delegates `onAction`/`onClick` to whichever of five plain (non-`Window`) controller objects — `LoginView`, `MenuView`, `LiveStreamsView`, `DiscoverView`, `SearchView` — is currently active. Back handling (stop playback / return to Menu / quit-confirm) is centralized once in `MainWindow` instead of duplicated per screen.

**Tech Stack:** Python 3, Kodi `xbmcgui`/`xbmc`/`xbmcaddon` (real at runtime, stubbed in `tests/kodi_stubs` for pytest), pytest.

## Global Constraints

- Every control ID is globally unique across the single new skin file (see the ID table in the spec, `docs/superpowers/specs/2026-08-13-persistent-window-architecture-design.md`) — Kodi resolves IDs window-wide even inside `<group>` blocks.
- Controllers are plain Python classes, not `xbmcgui.Window*` subclasses — they take a `window` reference (the real `MainWindow`, or a `FakeWindow` test double) and call `self.window.getControl(...)` / `self.window.setFocusId(...)` / `self.window.getFocusId()` / `self.window.close()` instead of inheriting those methods.
- One `closed_event`, owned by `MainWindow`, shared by all five controllers at construction — no per-transition event handoff.
- Every task must leave `python3 -m pytest -q` fully green before its commit.
- Follow `[[feedback_changelog_versioning]]`: bump `addon.xml`'s version and add a `CHANGELOG.md` entry in the final task once the whole migration is verified end-to-end (not per-task — this is one cohesive release, per-task version bumps would be noise).

---

### Task 1: Merged skin file

**Files:**
- Create: `resources/skins/Default/1080i/script-twitch-center-main.xml`

No Python in this task — the skin file isn't parsed by the pytest stubs (they never load real XML), so there's no automated test for it. Verification is `xmllint --noout` (well-formedness) plus a manual Kodi smoke-test after Task 8 wires it up.

- [ ] **Step 1: Write the merged skin file**

Combine the four existing skin files' controls into five `<control type="group">` blocks under one `<window>`, applying the ID renumbering table from the spec. Each group's internal `onup`/`ondown`/`onleft`/`onright` chains keep the same *relative* structure as today, just with renumbered targets. The window's own `<defaultcontrol always="true">` targets Login's cancel button (104) — Login is always the safe, always-focusable initial control regardless of which group ends up visible first; `MainWindow.onInit` explicitly calls `setFocusId` for whichever view is actually active immediately after, the same explicit-focus pattern already used by `HomeWindow._load_and_populate` today.

```xml
<?xml version="1.0" encoding="UTF-8"?>
<window>
  <defaultcontrol always="true">104</defaultcontrol>
  <controls>

    <!-- ===================== LOGIN (100) ===================== -->
    <control type="group" id="100">
      <control type="label">
        <description>Title</description>
        <posx>560</posx>
        <posy>260</posy>
        <width>800</width>
        <height>50</height>
        <font>font32</font>
        <align>center</align>
        <label>Activate Twitch Center</label>
      </control>
      <control type="label" id="101">
        <description>User code</description>
        <posx>560</posx>
        <posy>340</posy>
        <width>800</width>
        <height>140</height>
        <font>font37</font>
        <align>center</align>
        <aligny>center</aligny>
        <label></label>
      </control>
      <control type="label" id="102">
        <description>Verification URL</description>
        <posx>560</posx>
        <posy>500</posy>
        <width>800</width>
        <height>40</height>
        <font>font13</font>
        <align>center</align>
        <label></label>
      </control>
      <control type="label" id="103">
        <description>Status</description>
        <posx>560</posx>
        <posy>560</posy>
        <width>800</width>
        <height>40</height>
        <font>font13</font>
        <align>center</align>
        <label></label>
      </control>
      <control type="button" id="104">
        <description>Cancel</description>
        <posx>760</posx>
        <posy>640</posy>
        <width>400</width>
        <height>60</height>
        <font>font13</font>
        <align>center</align>
        <label>Cancel</label>
        <onclick>PreviousMenu</onclick>
      </control>
    </control>

    <!-- ===================== MENU (500) ===================== -->
    <control type="group" id="500">
      <control type="image">
        <posx>0</posx>
        <posy>0</posy>
        <width>1920</width>
        <height>1080</height>
        <texture>black.png</texture>
      </control>
      <control type="label">
        <description>Title</description>
        <posx>60</posx>
        <posy>60</posy>
        <width>800</width>
        <height>50</height>
        <font>font32</font>
        <label>Twitch Center</label>
      </control>
      <control type="button" id="501">
        <description>Live Streams</description>
        <posx>660</posx>
        <posy>360</posy>
        <width>600</width>
        <height>80</height>
        <font>font20</font>
        <align>center</align>
        <aligny>center</aligny>
        <onright>501</onright>
        <onleft>501</onleft>
        <ondown>502</ondown>
        <onup>505</onup>
        <label>Live Streams</label>
      </control>
      <control type="button" id="502">
        <description>Discover</description>
        <posx>660</posx>
        <posy>460</posy>
        <width>600</width>
        <height>80</height>
        <font>font20</font>
        <align>center</align>
        <aligny>center</aligny>
        <onright>502</onright>
        <onleft>502</onleft>
        <onup>501</onup>
        <ondown>503</ondown>
        <label>Discover</label>
      </control>
      <control type="button" id="503">
        <description>Search</description>
        <posx>660</posx>
        <posy>560</posy>
        <width>600</width>
        <height>80</height>
        <font>font20</font>
        <align>center</align>
        <aligny>center</aligny>
        <onright>503</onright>
        <onleft>503</onleft>
        <onup>502</onup>
        <ondown>504</ondown>
        <label>Search</label>
      </control>
      <control type="button" id="504">
        <description>Settings</description>
        <posx>660</posx>
        <posy>660</posy>
        <width>600</width>
        <height>80</height>
        <font>font20</font>
        <align>center</align>
        <aligny>center</aligny>
        <onright>504</onright>
        <onleft>504</onleft>
        <onup>503</onup>
        <ondown>505</ondown>
        <label>Settings</label>
      </control>
      <control type="button" id="505">
        <description>Log in again</description>
        <posx>660</posx>
        <posy>760</posy>
        <width>600</width>
        <height>80</height>
        <font>font13</font>
        <align>center</align>
        <aligny>center</aligny>
        <onright>505</onright>
        <onleft>505</onleft>
        <onup>504</onup>
        <ondown>501</ondown>
        <label>Log in again</label>
      </control>
    </control>

    <!-- ===================== LIVE STREAMS (200) ===================== -->
    <control type="group" id="200">
      <control type="label" id="207">
        <description>Title with version</description>
        <posx>60</posx>
        <posy>60</posy>
        <width>800</width>
        <height>50</height>
        <font>font32</font>
        <label>Twitch Center</label>
      </control>
      <control type="list" id="205">
        <description>Followed games filter</description>
        <posx>60</posx>
        <posy>130</posy>
        <width>1800</width>
        <height>90</height>
        <orientation>horizontal</orientation>
        <onup>205</onup>
        <ondown>201</ondown>
        <onleft>205</onleft>
        <onright>205</onright>
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
      <control type="list" id="201">
        <description>Followed channels</description>
        <posx>60</posx>
        <posy>240</posy>
        <width>1800</width>
        <height>760</height>
        <onup>205</onup>
        <ondown>201</ondown>
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
      <control type="label" id="202">
        <description>Empty followed list message</description>
        <posx>560</posx>
        <posy>460</posy>
        <width>800</width>
        <height>60</height>
        <font>font20</font>
        <align>center</align>
        <label></label>
      </control>
      <control type="label" id="203">
        <description>Error / re-login message</description>
        <posx>560</posx>
        <posy>460</posy>
        <width>800</width>
        <height>60</height>
        <font>font20</font>
        <align>center</align>
        <label></label>
      </control>
    </control>

    <!-- ===================== DISCOVER (300) ===================== -->
    <control type="group" id="300">
      <control type="label">
        <description>Title</description>
        <posx>60</posx>
        <posy>60</posy>
        <width>800</width>
        <height>50</height>
        <font>font32</font>
        <label>Discover</label>
      </control>
      <control type="edit" id="306">
        <description>Search query</description>
        <posx>60</posx>
        <posy>130</posy>
        <width>1200</width>
        <height>60</height>
        <font>font13</font>
        <onright>307</onright>
        <ondown>305</ondown>
        <label>Search channels...</label>
      </control>
      <control type="button" id="307">
        <description>Search</description>
        <posx>1280</posx>
        <posy>130</posy>
        <width>200</width>
        <height>60</height>
        <font>font13</font>
        <align>center</align>
        <onleft>306</onleft>
        <onright>308</onright>
        <ondown>305</ondown>
        <label>Search</label>
      </control>
      <control type="button" id="308">
        <description>Search mode toggle (channels/games)</description>
        <posx>1500</posx>
        <posy>130</posy>
        <width>360</width>
        <height>60</height>
        <font>font13</font>
        <align>center</align>
        <onleft>307</onleft>
        <onright>304</onright>
        <ondown>305</ondown>
        <label>Searching: Channels</label>
      </control>
      <control type="list" id="305">
        <description>Top games</description>
        <posx>60</posx>
        <posy>220</posy>
        <width>1800</width>
        <height>90</height>
        <orientation>horizontal</orientation>
        <onup>306</onup>
        <ondown>301</ondown>
        <onleft>305</onleft>
        <onright>305</onright>
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
      <control type="list" id="301">
        <description>Results</description>
        <posx>60</posx>
        <posy>330</posy>
        <width>1800</width>
        <height>670</height>
        <onup>305</onup>
        <ondown>301</ondown>
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
      <control type="label" id="302">
        <description>Empty results message</description>
        <posx>560</posx>
        <posy>600</posy>
        <width>800</width>
        <height>60</height>
        <font>font20</font>
        <align>center</align>
        <label></label>
      </control>
      <control type="label" id="303">
        <description>Error / re-login message</description>
        <posx>560</posx>
        <posy>600</posy>
        <width>800</width>
        <height>60</height>
        <font>font20</font>
        <align>center</align>
        <label></label>
      </control>
      <control type="button" id="304">
        <description>Log in again</description>
        <posx>760</posx>
        <posy>680</posy>
        <width>400</width>
        <height>60</height>
        <font>font13</font>
        <align>center</align>
        <onleft>308</onleft>
        <ondown>305</ondown>
        <label>Log in again</label>
      </control>
    </control>

    <!-- ===================== SEARCH (400) ===================== -->
    <control type="group" id="400">
      <control type="image">
        <posx>0</posx>
        <posy>0</posy>
        <width>1920</width>
        <height>1080</height>
        <texture>black.png</texture>
        <colordiffuse>CC000000</colordiffuse>
      </control>
      <control type="group">
        <posx>100</posx>
        <posy>100</posy>
        <width>1720</width>
        <height>880</height>

        <control type="edit" id="401">
          <description>Search Input</description>
          <posx>0</posx>
          <posy>0</posy>
          <width>1720</width>
          <height>60</height>
          <font>font20</font>
          <align>center</align>
          <aligny>center</aligny>
          <textcolor>ffffff</textcolor>
          <focusedcolor>ff9146ff</focusedcolor>
          <label>Search channels or streams...</label>
          <onup>401</onup>
          <ondown>402</ondown>
          <onleft>401</onleft>
          <onright>401</onright>
        </control>

        <control type="label" id="403">
          <description>Status</description>
          <posx>0</posx>
          <posy>70</posy>
          <width>1720</width>
          <height>40</height>
          <font>font13</font>
          <align>center</align>
          <textcolor>aaaaaa</textcolor>
          <label></label>
        </control>

        <control type="list" id="402">
          <description>Results List</description>
          <posx>0</posx>
          <posy>120</posy>
          <width>1720</width>
          <height>760</height>
          <onup>401</onup>
          <ondown>404</ondown>
          <itemlayout width="1720" height="80">
            <control type="label">
              <posx>20</posx>
              <width>1680</width>
              <height>80</height>
              <font>font20</font>
              <align>left</align>
              <aligny>center</aligny>
              <label>$INFO[ListItem.Label]</label>
            </control>
          </itemlayout>
          <focusedlayout width="1720" height="80">
            <control type="label">
              <posx>20</posx>
              <width>1680</width>
              <height>80</height>
              <font>font20</font>
              <align>left</align>
              <aligny>center</aligny>
              <textcolor>ff9146ff</textcolor>
              <label>$INFO[ListItem.Label]</label>
            </control>
          </focusedlayout>
        </control>

        <control type="button" id="404">
          <description>Next Page</description>
          <posx>0</posx>
          <posy>890</posy>
          <width>1720</width>
          <height>60</height>
          <font>font13</font>
          <align>center</align>
          <aligny>center</aligny>
          <label>Next Page</label>
          <onup>402</onup>
          <ondown>402</ondown>
          <visible>false</visible>
        </control>
      </control>
    </control>

  </controls>
</window>
```

- [ ] **Step 2: Verify well-formedness**

Run: `xmllint --noout resources/skins/Default/1080i/script-twitch-center-main.xml`
Expected: no output, exit code 0.

- [ ] **Step 3: Commit**

```bash
git add resources/skins/Default/1080i/script-twitch-center-main.xml
git commit -m "feat: add merged skin file for persistent-window architecture"
```

---

### Task 2: `MainWindow` shell

**Files:**
- Create: `lib/windows/main_window.py`
- Test: `tests/windows/test_main_window.py`

**Interfaces:**
- Produces: `MainWindow(xbmcgui.WindowXML)` — `__init__(self, *args, initial_view="login", closed_event=None, view_classes=None, **kwargs)`; `.closed_event`; `._switch_view(name: str)`; `.onInit()`; `.onAction(action)`; `.onClick(control_id)`. `view_classes` is an optional `{name: cls}` override dict for tests (defaults to the real `LoginView`/`MenuView`/`LiveStreamsView`/`DiscoverView`/`SearchView`, wired in Task 7 — until then, tests inject fakes).
- Consumes: nothing from earlier tasks (this task defines the controller contract every later task's view class must satisfy: `activate()`, `handle_action(action)`, `handle_click(control_id)`, constructed as `cls(window, closed_event=closed_event)`).

Group IDs (from Task 1): Login=100, Menu=500, Live Streams=200, Discover=300, Search=400.

- [ ] **Step 1: Write the failing tests**

```python
# tests/windows/test_main_window.py
from unittest.mock import MagicMock, patch

import xbmcgui

from lib.windows.main_window import MainWindow


class FakeView:
    def __init__(self, window, closed_event=None):
        self.window = window
        self.closed_event = closed_event
        self.activate_calls = 0
        self.actions = []
        self.clicks = []

    def activate(self):
        self.activate_calls += 1

    def handle_action(self, action):
        self.actions.append(action)

    def handle_click(self, control_id):
        self.clicks.append(control_id)


def _make_window(initial_view="menu"):
    views = {name: FakeView for name in ("login", "menu", "live_streams", "discover", "search")}
    return MainWindow(
        "script-twitch-center-main.xml", "/tmp", initial_view=initial_view, view_classes=views
    )


def test_oninit_activates_the_initial_view_and_shows_only_its_group():
    win = _make_window(initial_view="menu")
    win.onInit()
    assert win._active_name == "menu"
    assert win._views["menu"].activate_calls == 1
    assert win.getControl(win.GROUP_IDS["menu"]).isVisible() is True
    for name, group_id in win.GROUP_IDS.items():
        if name != "menu":
            assert win.getControl(group_id).isVisible() is False


def test_switch_view_hides_old_group_shows_new_group_and_activates_target():
    win = _make_window(initial_view="menu")
    win.onInit()
    win._switch_view("discover")
    assert win._active_name == "discover"
    assert win._views["discover"].activate_calls == 1
    assert win.getControl(win.GROUP_IDS["discover"]).isVisible() is True
    assert win.getControl(win.GROUP_IDS["menu"]).isVisible() is False


def test_onaction_back_switches_to_menu_from_a_non_menu_view():
    win = _make_window(initial_view="discover")
    win.onInit()
    with patch("lib.windows.main_window.xbmc.Player") as mock_player_cls:
        mock_player_cls.return_value.isPlaying.return_value = False
        win.onAction(xbmcgui.Action(xbmcgui.ACTION_NAV_BACK))
    assert win._active_name == "menu"
    assert not win.closed_event.is_set()
    assert not getattr(win.closed_event, "quit_requested", False)


def test_onaction_back_requests_quit_from_menu_when_nothing_playing():
    win = _make_window(initial_view="menu")
    win.onInit()
    with patch("lib.windows.main_window.xbmc.Player") as mock_player_cls:
        mock_player_cls.return_value.isPlaying.return_value = False
        win.onAction(xbmcgui.Action(xbmcgui.ACTION_NAV_BACK))
    assert win.closed_event.quit_requested is True
    assert win._active_name == "menu"


def test_onaction_back_stops_playback_instead_of_navigating_when_playing():
    win = _make_window(initial_view="discover")
    win.onInit()
    with patch("lib.windows.main_window.xbmc.Player") as mock_player_cls:
        mock_player_cls.return_value.isPlaying.return_value = True
        win.onAction(xbmcgui.Action(xbmcgui.ACTION_NAV_BACK))
        mock_player_cls.return_value.stop.assert_called_once()
    # Still on Discover - Back stopped the stream, didn't navigate away.
    assert win._active_name == "discover"
    assert not win.closed_event.quit_requested


def test_onaction_delegates_non_back_actions_to_the_active_view():
    win = _make_window(initial_view="search")
    win.onInit()
    action = xbmcgui.Action(xbmcgui.ACTION_SELECT_ITEM)
    win.onAction(action)
    assert win._views["search"].actions == [action]


def test_onclick_delegates_to_the_active_view():
    win = _make_window(initial_view="live_streams")
    win.onInit()
    win.onClick(201)
    assert win._views["live_streams"].clicks == [201]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/windows/test_main_window.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'lib.windows.main_window'`

- [ ] **Step 3: Implement `MainWindow`**

```python
# lib/windows/main_window.py
"""Persistent shell window: hosts every screen as a toggle-able skin group
instead of ever constructing a second top-level Kodi window, which is what
triggers a native window-manager bug (see
docs/superpowers/specs/2026-08-13-persistent-window-architecture-design.md)."""
import threading

import xbmc
import xbmcgui


class MainWindow(xbmcgui.WindowXML):
    GROUP_IDS = {
        "login": 100,
        "menu": 500,
        "live_streams": 200,
        "discover": 300,
        "search": 400,
    }

    def __init__(self, *args, initial_view="login", closed_event=None, view_classes=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.closed_event = closed_event or threading.Event()
        if not hasattr(self.closed_event, "quit_requested"):
            self.closed_event.quit_requested = False
        self._initial_view = initial_view
        view_classes = view_classes or self._default_view_classes()
        self._views = {
            name: cls(self, closed_event=self.closed_event) for name, cls in view_classes.items()
        }
        self._active_name = None

    @staticmethod
    def _default_view_classes():
        from lib.views.discover_view import DiscoverView
        from lib.views.live_streams_view import LiveStreamsView
        from lib.views.login_view import LoginView
        from lib.views.menu_view import MenuView
        from lib.views.search_view import SearchView

        return {
            "login": LoginView,
            "menu": MenuView,
            "live_streams": LiveStreamsView,
            "discover": DiscoverView,
            "search": SearchView,
        }

    def onInit(self):
        self._switch_view(self._initial_view)

    def _switch_view(self, name):
        for view_name, group_id in self.GROUP_IDS.items():
            control = self._safe_control(group_id)
            if control:
                control.setVisible(view_name == name)
        self._active_name = name
        self._views[name].activate()

    def _safe_control(self, control_id):
        try:
            return self.getControl(control_id)
        except Exception:
            return None

    def onAction(self, action):
        if action.getId() in (xbmcgui.ACTION_PREVIOUS_MENU, xbmcgui.ACTION_NAV_BACK):
            if xbmc.Player().isPlaying():
                xbmc.Player().stop()
                return
            if self._active_name == "menu":
                self.closed_event.quit_requested = True
            else:
                self._switch_view("menu")
            return
        self._views[self._active_name].handle_action(action)

    def onClick(self, control_id):
        self._views[self._active_name].handle_click(control_id)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/windows/test_main_window.py -v`
Expected: PASS (7 tests) — `_default_view_classes` isn't exercised yet since every test passes `view_classes=views`; it starts resolving real imports once Task 7 wires `lib/main.py` to construct `MainWindow` without that override, after the view modules exist.

- [ ] **Step 5: Commit**

```bash
git add lib/windows/main_window.py tests/windows/test_main_window.py
git commit -m "feat: add MainWindow shell for persistent-window architecture"
```

---

### Task 3: `LoginView`

**Files:**
- Create: `lib/views/__init__.py` (empty)
- Create: `lib/views/login_view.py`
- Create: `tests/views/__init__.py` (empty)
- Create: `tests/views/test_login_view.py`

**Interfaces:**
- Produces: `LoginView(window, closed_event=None)` implementing `activate()`, `handle_action(action)`, `handle_click(control_id)` (unused — Login has no `onClick`-routed controls; the Cancel button's `PreviousMenu` skin action already becomes `ACTION_PREVIOUS_MENU`, handled by `MainWindow.onAction`'s centralized Back logic before it would ever reach `handle_action`). Also exposes `login_succeeded` (bool, read by `lib/main.py`'s monitor loop in Task 7), `CODE_LABEL_ID = 101`, `URL_LABEL_ID = 102`, `STATUS_LABEL_ID = 103`.
- Consumes: nothing new — same `lib.twitch.auth` module `LoginWindow` already used.

This is a mechanical port of `lib/windows/login.py`'s `LoginWindow` (read in full at `lib/windows/login.py:1-97`). Apply these substitutions uniformly:

1. `class LoginWindow(xbmcgui.WindowXML):` → `class LoginView:` (drop the `xbmcgui`/`xbmcgui.WindowXML` inheritance entirely — no `xbmcgui` import needed in this file at all).
2. `def __init__(self, *args, closed_event=None, **kwargs): super().__init__(*args, **kwargs)` → `def __init__(self, window, closed_event=None): self.window = window` (drop `*args`/`**kwargs`/`super()` — there's no `xbmcgui.Window.__init__` to call anymore).
3. Every `self.getControl(...)` → `self.window.getControl(...)`.
4. `def onInit(self):` → `def activate(self):` (body unchanged).
5. `def onAction(self, action):` → `def handle_action(self, action):`, with the Back-handling block removed entirely (now centralized in `MainWindow`):
   ```python
   # DELETE this whole block from the ported method body:
   def onAction(self, action):
       if action.getId() in (xbmcgui.ACTION_PREVIOUS_MENU, xbmcgui.ACTION_NAV_BACK):
           self._cancel_event.set()
           self.closed_event.quit_requested = True
           return
   ```
   Login's `onAction` today has *only* that block (see `lib/windows/login.py:92-97`) — so `handle_action` ends up an empty pass-through:
   ```python
   def handle_action(self, action):
       pass
   ```
   The `self._cancel_event.set()` line that was inside the deleted block must move somewhere it still runs on Back — add it to a new small `on_back()` method that `MainWindow` doesn't call (Login has no cancel-in-progress semantics that matter once Back always routes to Menu instead of tearing the window down) — **actually, simpler:** keep `_cancel_event.set()` firing whenever the view stops being active, by calling it from a new `deactivate()` no-op hook is overkill for one flag; instead just leave `_cancel_event` alone — it exists to stop the background thread from calling `_on_code`/`_on_status` after a *real* teardown (window closing for good), which still happens via `MainWindow.onAction`'s quit path today. Add a `stop()` method Login's polling thread checks the same way, and call it from `MainWindow._switch_view` whenever `login` stops being the active view:
   ```python
   def stop(self):
       self._cancel_event.set()
   ```
   Then in Task 2's `MainWindow._switch_view`, before switching away, call `deactivate` if present:
   ```python
   # lib/windows/main_window.py, in _switch_view, before the loop:
   old_view = self._views.get(self._active_name)
   if old_view is not None and hasattr(old_view, "stop"):
       old_view.stop()
   ```
   (This is a small addition to Task 2's `_switch_view` — apply it now as part of this task, then re-run Task 2's test suite to confirm nothing broke: `python3 -m pytest tests/windows/test_main_window.py -v` should still be all-green, since none of Task 2's `FakeView`s define `stop`.)
6. Everything else (`__init__` body's `_cancel_event`/`_thread`/`login_succeeded` setup, `_on_code`, `_on_status`) copies over unchanged except for the `getControl` substitution in rule 3. Drop the `closed_event`-sharing boilerplate lines that referenced `threading.Event()` construction — `MainWindow` always passes a real shared `closed_event`, so the `or threading.Event()` fallback and the `quit_requested` attribute bootstrap move to `MainWindow.__init__` (already done there in Task 2) and are **not** repeated per-view. `LoginView.__init__` becomes:
   ```python
   def __init__(self, window, closed_event=None):
       self.window = window
       self.closed_event = closed_event
       self._cancel_event = threading.Event()
       self._thread = None
       self.login_succeeded = False
   ```

- [ ] **Step 1: Write the failing test**

Port `tests/windows/test_login_window.py` to `tests/views/test_login_view.py` with these mechanical changes: import `LoginView` instead of `LoginWindow`; construct with `LoginView(FakeWindow(), closed_event=threading.Event())` instead of `LoginWindow("script-twitch-center-login.xml", "/tmp")`; `win._on_code(...)`/`win._on_status(...)` calls unchanged; assertions read via `win.window.getControl(...)` instead of `win.getControl(...)`; the Back test becomes:

```python
def test_on_action_back_is_a_no_op_pass_through():
    # Back is handled centrally by MainWindow now - LoginView.handle_action
    # has nothing left to do for it.
    win = LoginView(FakeWindow(), closed_event=threading.Event())
    win._cancel_event = threading.Event()
    win.handle_action(xbmcgui.Action(xbmcgui.ACTION_NAV_BACK))
    assert not win._cancel_event.is_set()
```

and drop `test_shared_closed_event_is_used_instead_of_a_fresh_one` (no longer meaningful — `MainWindow` always owns the one shared event; there's no "fresh vs shared" distinction left to test at the view level).

Add a small `FakeWindow` double at the top of the new test file (mirrors the shape `tests/kodi_stubs/xbmcgui.py`'s `WindowXML` already provides):

```python
# tests/views/test_login_view.py
import threading
from unittest.mock import MagicMock, patch

import xbmcgui

from lib.views.login_view import LoginView


class FakeWindow:
    def __init__(self):
        self._controls = {}

    def getControl(self, control_id):
        from xbmcgui import ControlLabel

        if control_id not in self._controls:
            self._controls[control_id] = ControlLabel()
        return self._controls[control_id]
```

(then the ported test bodies follow, per the substitutions above)

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/views/test_login_view.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'lib.views'`

- [ ] **Step 3: Write `lib/views/__init__.py` (empty) and `lib/views/login_view.py`**

Apply all substitution rules above to the full body of `lib/windows/login.py`. Resulting file:

```python
# lib/views/login_view.py
"""Login view: device-code login screen, displays the code + verification
URL, polls for auth. Not a Window subclass - see MainWindow."""
import threading

import xbmc
import xbmcaddon

from lib.twitch import auth

STATUS_MESSAGES = {
    "pending": "Waiting for authorization...",
    "expired": "Code expired. Reopen the addon to try again.",
    "success": "Logged in!",
    "error": "Connection error. Reopen the addon to try again.",
}


class LoginView:
    CODE_LABEL_ID = 101
    URL_LABEL_ID = 102
    STATUS_LABEL_ID = 103

    def __init__(self, window, closed_event=None):
        self.window = window
        self.closed_event = closed_event
        self._cancel_event = threading.Event()
        self._thread = None
        self.login_succeeded = False

    def stop(self):
        self._cancel_event.set()

    def activate(self):
        if self.login_succeeded:
            return
        if self._thread is not None and self._thread.is_alive():
            return
        self._cancel_event = threading.Event()
        addon = xbmcaddon.Addon()
        client_id = addon.getSetting("client_id")
        thread = threading.Thread(
            target=auth.run_device_code_login,
            kwargs={
                "client_id": client_id,
                "scopes": auth.SCOPES,
                "addon": addon,
                "on_code": self._on_code,
                "on_status": self._on_status,
                "cancel_event": self._cancel_event,
            },
        )
        thread.daemon = True
        thread.start()
        self._thread = thread

    def _on_code(self, user_code, verification_uri):
        if self._cancel_event.is_set():
            return
        self.window.getControl(self.CODE_LABEL_ID).setLabel(user_code)
        self.window.getControl(self.URL_LABEL_ID).setLabel(verification_uri)

    def _on_status(self, status):
        if self._cancel_event.is_set():
            return
        if status == "error":
            xbmc.log("script.twitch.center: device-code login reported an error", xbmc.LOGERROR)
        message = STATUS_MESSAGES.get(status, "")
        self.window.getControl(self.STATUS_LABEL_ID).setLabel(message)
        if status == "success":
            self.login_succeeded = True

    def handle_action(self, action):
        pass

    def handle_click(self, control_id):
        pass
```

- [ ] **Step 4: Add the `stop()`-on-deactivate hook to `MainWindow._switch_view`**

```python
# lib/windows/main_window.py — modify _switch_view:
def _switch_view(self, name):
    old_view = self._views.get(self._active_name)
    if old_view is not None and hasattr(old_view, "stop"):
        old_view.stop()
    for view_name, group_id in self.GROUP_IDS.items():
        control = self._safe_control(group_id)
        if control:
            control.setVisible(view_name == name)
    self._active_name = name
    self._views[name].activate()
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python3 -m pytest tests/views/test_login_view.py tests/windows/test_main_window.py -v`
Expected: PASS (all tests, including Task 2's — `hasattr(old_view, "stop")` is `False` for `FakeView`, so that path is inert there).

- [ ] **Step 6: Commit**

```bash
git add lib/views/__init__.py lib/views/login_view.py tests/views/__init__.py tests/views/test_login_view.py lib/windows/main_window.py tests/windows/test_main_window.py
git commit -m "feat: add LoginView controller for persistent-window architecture"
```

---

### Task 4: `MenuView` (new)

**Files:**
- Create: `lib/views/menu_view.py`
- Create: `tests/views/test_menu_view.py`

**Interfaces:**
- Produces: `MenuView(window, closed_event=None)`: `activate()` (no-op — nothing to load), `handle_action(action)` (routes `ACTION_SELECT_ITEM` by `window.getFocusId()`, same pattern as today's `HomeWindow.onAction`), `handle_click(control_id)` (no-op — Menu has no list controls needing `onClick`). Constants: `LIVE_STREAMS_BUTTON_ID = 501`, `DISCOVER_BUTTON_ID = 502`, `SEARCH_BUTTON_ID = 503`, `SETTINGS_BUTTON_ID = 504`, `RELOGIN_BUTTON_ID = 505`.
- Consumes: `self.window._switch_view(name)` (Task 2) for the first four buttons; `xbmcaddon.Addon().openSettings()` for Settings, matching today's `HomeWindow._open_addon_settings` (`lib/windows/home.py:389-397`) minus the reload-`onInit` step — reloading is `LiveStreamsView`'s concern now (it reloads itself when it becomes active again after Back, since `activate()` already re-runs its own load logic every time, same as today's `onInit` re-firing).

- [ ] **Step 1: Write the failing test**

```python
# tests/views/test_menu_view.py
from unittest.mock import MagicMock, patch

import xbmcaddon
import xbmcgui

from lib.views.menu_view import MenuView


class FakeMainWindow:
    def __init__(self):
        self.switched_to = []

    def _switch_view(self, name):
        self.switched_to.append(name)

    def getFocusId(self):
        return self._focus_id

    def setFocusId(self, control_id):
        self._focus_id = control_id


def _select(window, control_id):
    window.setFocusId(control_id)
    view = MenuView(window)
    view.handle_action(xbmcgui.Action(xbmcgui.ACTION_SELECT_ITEM))
    return view


def test_selecting_live_streams_switches_to_live_streams_view():
    window = FakeMainWindow()
    _select(window, MenuView.LIVE_STREAMS_BUTTON_ID)
    assert window.switched_to == ["live_streams"]


def test_selecting_discover_switches_to_discover_view():
    window = FakeMainWindow()
    _select(window, MenuView.DISCOVER_BUTTON_ID)
    assert window.switched_to == ["discover"]


def test_selecting_search_switches_to_search_view():
    window = FakeMainWindow()
    _select(window, MenuView.SEARCH_BUTTON_ID)
    assert window.switched_to == ["search"]


def test_selecting_relogin_switches_to_login_view():
    window = FakeMainWindow()
    _select(window, MenuView.RELOGIN_BUTTON_ID)
    assert window.switched_to == ["login"]


def test_selecting_settings_opens_addon_settings_without_switching_view():
    window = FakeMainWindow()
    addon = xbmcaddon.Addon()
    with patch("xbmcaddon.Addon", return_value=addon), patch.object(
        addon, "openSettings"
    ) as mock_open_settings:
        _select(window, MenuView.SETTINGS_BUTTON_ID)
    mock_open_settings.assert_called_once()
    assert window.switched_to == []


def test_non_select_action_is_a_no_op():
    window = FakeMainWindow()
    window.setFocusId(MenuView.DISCOVER_BUTTON_ID)
    view = MenuView(window)
    view.handle_action(xbmcgui.Action(999))
    assert window.switched_to == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/views/test_menu_view.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'lib.views.menu_view'`

- [ ] **Step 3: Write `lib/views/menu_view.py`**

```python
# lib/views/menu_view.py
"""Menu view: the landing screen after Login - Live Streams / Discover /
Search / Settings / Log in again. Not a Window subclass - see MainWindow."""
import xbmcaddon
import xbmcgui


class MenuView:
    LIVE_STREAMS_BUTTON_ID = 501
    DISCOVER_BUTTON_ID = 502
    SEARCH_BUTTON_ID = 503
    SETTINGS_BUTTON_ID = 504
    RELOGIN_BUTTON_ID = 505

    def __init__(self, window, closed_event=None):
        self.window = window
        self.closed_event = closed_event

    def activate(self):
        pass

    def handle_action(self, action):
        if action.getId() != xbmcgui.ACTION_SELECT_ITEM:
            return
        focus = self.window.getFocusId()
        if focus == self.LIVE_STREAMS_BUTTON_ID:
            self.window._switch_view("live_streams")
        elif focus == self.DISCOVER_BUTTON_ID:
            self.window._switch_view("discover")
        elif focus == self.SEARCH_BUTTON_ID:
            self.window._switch_view("search")
        elif focus == self.SETTINGS_BUTTON_ID:
            xbmcaddon.Addon().openSettings()
        elif focus == self.RELOGIN_BUTTON_ID:
            self.window._switch_view("login")

    def handle_click(self, control_id):
        pass
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/views/test_menu_view.py -v`
Expected: PASS (6 tests)

- [ ] **Step 5: Commit**

```bash
git add lib/views/menu_view.py tests/views/test_menu_view.py
git commit -m "feat: add MenuView, the new landing screen"
```

---

### Task 5: `LiveStreamsView`

**Files:**
- Create: `lib/views/live_streams_view.py`
- Create: `tests/views/test_live_streams_view.py`

**Interfaces:**
- Produces: `LiveStreamsView(window, closed_event=None)` — same public surface as today's `HomeWindow` minus button-row IDs/handling (those moved to `MenuView` in Task 4) and minus `_open_login_window`/`_open_discover_window`/`_open_search_window`/`_open_addon_settings` (replaced by `self.window._switch_view(...)` calls). Constants: `CHANNEL_LIST_ID = 201`, `EMPTY_LABEL_ID = 202`, `ERROR_LABEL_ID = 203`, `GAMES_LIST_ID = 205`, `TITLE_LABEL_ID = 207`. Module-level: `_thumbnail_url`, `_merge_channels`, `_build_list_item` (unchanged, copied verbatim from `lib/windows/home.py:35-70`).
- Consumes: `lib.settings.Settings`, `lib.twitch.{api,auth,gql,stream}`, `lib.windows.player` — same imports as today's `home.py`.

This is a mechanical port of `lib/windows/home.py`'s `HomeWindow` (full source read at `lib/windows/home.py:1-412`). Apply the same substitution rules as Task 3 (drop `Window` inheritance, `self.getControl` → `self.window.getControl`, `self.setFocusId` → `self.window.setFocusId`, `self.getFocusId()` → `self.window.getFocusId()`, `onInit` → `activate`, closed_event always passed in directly not defaulted), **plus** these Home-specific changes:

1. Delete the `RELOGIN_BUTTON_ID`, `DISCOVER_BUTTON_ID`, `SETTINGS_BUTTON_ID`, `SEARCH_BUTTON_ID` class constants and their corresponding module-level assignments (lines 18, 20, 22-23) — those buttons no longer exist on this screen.
2. Delete `_show_error`'s and `_load_and_populate`'s relogin-button-visibility lines (`lib/windows/home.py:270-275`, `223-225`) — there is no relogin button on Live Streams anymore (per the spec's noted simplification: relogin now happens via Menu). `_load_and_populate`'s focus-fallback (`lib/windows/home.py:150-154`, "focus Discover button if list is empty") becomes: fall back to switching to Menu instead —
   ```python
   channel_list = self._safe_control(self.CHANNEL_LIST_ID)
   if channel_list and channel_list.size():
       self.window.setFocusId(self.CHANNEL_LIST_ID)
   else:
       self.window._switch_view("menu")
   ```
   and `_show_error`'s focus-fallback (`lib/windows/home.py:270-275`) similarly becomes a `_switch_view("menu")` call instead of focusing a (now-nonexistent) relogin button:
   ```python
   def _show_error(self, message):
       games_list = self._safe_control(self.GAMES_LIST_ID)
       if games_list:
           games_list.reset()
       channel_list = self._safe_control(self.CHANNEL_LIST_ID)
       if channel_list:
           channel_list.reset()
       empty_label = self._safe_control(self.EMPTY_LABEL_ID)
       if empty_label:
           empty_label.setLabel("")
       error_label = self._safe_control(self.ERROR_LABEL_ID)
       if error_label:
           error_label.setLabel(message)
   ```
3. Delete `onAction`'s `RELOGIN_BUTTON_ID`/`DISCOVER_BUTTON_ID`/`SETTINGS_BUTTON_ID`/`SEARCH_BUTTON_ID` branches (`lib/windows/home.py:298-308`) — only `GAMES_LIST_ID` and `CHANNEL_LIST_ID` branches remain, and the Back-handling block at the top (`lib/windows/home.py:286-297`) is deleted (centralized in `MainWindow`, same as Task 3 rule 5):
   ```python
   def handle_action(self, action):
       if action.getId() == xbmcgui.ACTION_SELECT_ITEM:
           if self.window.getFocusId() == self.GAMES_LIST_ID:
               self._on_game_selected()
           elif self.window.getFocusId() == self.CHANNEL_LIST_ID:
               self._on_channel_selected()

   def handle_click(self, control_id):
       pass
   ```
4. Delete `_open_login_window`, `_open_discover_window`, `_open_search_window`, `_open_addon_settings` entirely (`lib/windows/home.py:357-411`) — no longer called from anywhere in this view.
5. `TITLE_LABEL_ID`'s `onInit` body (`lib/windows/home.py:104-108`) is unchanged — Live Streams keeps its own title label (renumbered 207).

`_MISSING_TOKEN_MESSAGE` no longer needs its "Reopen the addon to log in" wording change (Menu makes re-login reachable without reopening) — leave the string as-is for this task; copy tightening is out of scope here.

- [ ] **Step 1: Write the failing test**

Port `tests/windows/test_home_window.py` to `tests/views/test_live_streams_view.py`. Mechanical changes throughout: `HomeWindow("script-twitch-center-home.xml", "/tmp")` → `LiveStreamsView(FakeWindow())`; `win.getControl(...)` → `win.window.getControl(...)`; `win.setFocusId(...)` → `win.window.setFocusId(...)`; `win.getFocusId()` → `win.window.getFocusId()`; `win.onInit()` → `win.activate()`; `win.onAction(...)` → `win.handle_action(...)`; `patch("lib.windows.home.xbmc.Player")` → `patch("lib.views.live_streams_view.xbmc.Player")`; `patch("lib.windows.home.auth...")` → `patch("lib.views.live_streams_view.auth...")` (same for `stream.resolve_stream_url`, `player.play_stream`).

Delete these tests entirely (they test now-removed relogin/Discover/Settings-button behavior that moved to `MenuView`, already covered by Task 4's tests): `test_back_requests_quit_when_nothing_is_playing`, `test_back_stops_playback_instead_of_requesting_quit_when_stream_is_playing` (Back is centralized now, covered by Task 2's `test_main_window.py`), `test_relogin_button_visible_when_relogin_prompt_shown`, `test_selecting_relogin_button_opens_login_window_and_closes_home`, `test_relogin_chain_requests_quit_only_when_login_window_back_is_pressed`, `test_selecting_settings_button_opens_addon_settings_and_reloads`, `test_selecting_settings_button_does_not_reload_if_window_already_closed`, `test_selecting_discover_button_opens_discover_window_and_closes_home`, `test_discover_chain_requests_quit_only_when_discover_back_is_pressed`.

Adapt `test_oninit_shows_empty_state_when_no_followed_channels` (its final assertion changes from checking `DISCOVER_BUTTON_ID` focus to checking a view switch):
```python
def test_activate_switches_to_menu_when_no_followed_channels():
    addon = _addon_with_token({"access_token": "tok", "refresh_token": "ref", "user_id": "u1"})
    with patch("xbmcaddon.Addon", return_value=addon), patch.object(
        api, "get_followed_channels", return_value=[]
    ), patch.object(api, "get_live_status", return_value=[]), patch.object(
        gql, "get_followed_live_games", return_value=[]
    ):
        window = FakeWindow()
        win = LiveStreamsView(window)
        win.activate()
    assert win.window.getControl(LiveStreamsView.EMPTY_LABEL_ID).getLabel() != ""
    assert win.window.getControl(LiveStreamsView.CHANNEL_LIST_ID).size() == 0
    assert window.switched_to == ["menu"]
```
and `test_oninit_shows_error_state_on_network_failure`'s final assertion, similarly, from `win.getFocusId() == HomeWindow.RELOGIN_BUTTON_ID` to `window.switched_to == ["menu"]`.

Every other test's body keeps its assertions, just with the renamed methods/attributes from the mechanical substitution list.

`FakeWindow` for this test file needs a `_switch_view` recorder in addition to `getControl`/`setFocusId`/`getFocusId`:
```python
# tests/views/test_live_streams_view.py — FakeWindow
class FakeWindow:
    def __init__(self):
        self._controls = {}
        self._focus_id = None
        self.switched_to = []

    def getControl(self, control_id):
        from xbmcgui import ControlLabel

        if control_id not in self._controls:
            self._controls[control_id] = ControlLabel()
        return self._controls[control_id]

    def setFocusId(self, control_id):
        self._focus_id = control_id

    def getFocusId(self):
        return self._focus_id

    def _switch_view(self, name):
        self.switched_to.append(name)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/views/test_live_streams_view.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'lib.views.live_streams_view'`

- [ ] **Step 3: Write `lib/views/live_streams_view.py`**

Apply substitution rules 1-5 above plus the Task-3-style rules to the full body of `lib/windows/home.py`. (Given the length, this step's deliverable is the fully substituted file — apply every rule listed above to `lib/windows/home.py`'s complete source rather than retyping it inline here; the result has these exact members: module-level `_thumbnail_url`, `_merge_channels`, `_build_list_item` unchanged; `class LiveStreamsView:` with `CHANNEL_LIST_ID/EMPTY_LABEL_ID/ERROR_LABEL_ID/GAMES_LIST_ID/TITLE_LABEL_ID`, `__init__`, `_safe_control`, `activate` (was `onInit`), `_load_and_populate`, `_handle_expired_token`, `_populate_games`, `_populate`, `_show_error`, `_show_results_error`, `handle_action`, `handle_click`, `_on_game_selected`, `_on_channel_selected`, `_play_channel`.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/views/test_live_streams_view.py -v`
Expected: PASS (all remaining/adapted tests — should be 22 tests: 27 original minus the 9 deleted relogin/Discover/Settings tests, with the 2 adapted ones counted in)

- [ ] **Step 5: Commit**

```bash
git add lib/views/live_streams_view.py tests/views/test_live_streams_view.py
git commit -m "feat: add LiveStreamsView controller (ported from HomeWindow)"
```

---

### Task 6: `DiscoverView`

**Files:**
- Create: `lib/views/discover_view.py`
- Create: `tests/views/test_discover_view.py`

**Interfaces:**
- Produces: `DiscoverView(window, closed_event=None)` — same public surface as today's `DiscoverWindow` (`lib/windows/discover.py`) minus `_open_login_window` (replaced by `self.window._switch_view("login")`) and minus the centralized Back block. Constants keep their existing values unchanged: `RESULTS_LIST_ID = 301`, `EMPTY_LABEL_ID = 302`, `ERROR_LABEL_ID = 303`, `RELOGIN_BUTTON_ID = 304`, `GAMES_LIST_ID = 305`, `SEARCH_EDIT_ID = 306`, `SEARCH_BUTTON_ID = 307`, `SEARCH_MODE_TOGGLE_ID = 308` (per the spec's ID table — Discover keeps its own dedicated relogin button, unlike Live Streams, since Discover's relogin case is a mid-browse session-expiry, not the empty/error initial-load case). Module-level: `_thumbnail_url`, `_build_stream_item`, `_build_channel_item` unchanged.
- Consumes: `lib.twitch.{api,auth,stream}`, `lib.windows.player` — same imports as today.

Apply the same substitution rules as Task 5 (drop inheritance, `getControl`/`setFocusId`/`getFocusId` → `self.window.*`, `onInit` → `activate`, `onAction` → `handle_action` with the Back block deleted, add `handle_click` as a no-op pass-through), plus:

1. `_open_login_window` (`lib/windows/discover.py:396-408`) is deleted; its one call site, in `onAction`'s `RELOGIN_BUTTON_ID` branch, becomes `self.window._switch_view("login")`.
2. Every other method (`_load_games`, `_handle_expired_token`, `_populate_games`, `_populate_results`, `_load_streams_for_game`, `_load_search_results`, `_load_game_search_results`, `_on_game_selected`, `_on_channel_selected`, `_play_channel`, `_on_search`, `_toggle_search_mode`, `_show_error`, `_show_results_error`) copies over unchanged except for the `getControl`/`setFocusId` substitution.

- [ ] **Step 1: Write the failing test**

Port `tests/windows/test_discover_window.py` to `tests/views/test_discover_view.py` with the same mechanical substitutions as Task 5's test port (`DiscoverWindow(...)` → `DiscoverView(FakeWindow())`, `win.getControl` → `win.window.getControl`, `win.onInit()` → `win.activate()`, `win.onAction(...)` → `win.handle_action(...)`, `patch("lib.windows.discover.xbmc.Player")` → `patch("lib.views.discover_view.xbmc.Player")`, same pattern for `auth`/`stream`/`player`/`api` patches). Delete `test_back_requests_quit_when_nothing_is_playing` and `test_back_stops_playback_instead_of_requesting_quit_when_stream_is_playing` (centralized in `MainWindow`, covered by Task 2). Adapt the relogin-window test (`test_selecting_relogin_button_...` if present, or equivalent `RELOGIN_BUTTON_ID` selection test) to assert `window.switched_to == ["login"]` instead of asserting a `LoginWindow` construction. Reuse the same `FakeWindow` shape as Task 5's test file (`getControl`/`setFocusId`/`getFocusId`/`_switch_view`).

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/views/test_discover_view.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'lib.views.discover_view'`

- [ ] **Step 3: Write `lib/views/discover_view.py`**

Apply the substitution rules above to the full body of `lib/windows/discover.py` (read in full at `lib/windows/discover.py:1-409`). Resulting class: `class DiscoverView:` with the same method set as `DiscoverWindow` minus `_open_login_window`, plus `handle_action`/`handle_click` replacing `onAction`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/views/test_discover_view.py -v`
Expected: PASS (all adapted tests)

- [ ] **Step 5: Commit**

```bash
git add lib/views/discover_view.py tests/views/test_discover_view.py
git commit -m "feat: add DiscoverView controller (ported from DiscoverWindow)"
```

---

### Task 7: `SearchView`

**Files:**
- Create: `lib/views/search_view.py`
- Create: `tests/views/test_search_view.py`
- Delete: `tests/windows/test_search_window.py` (superseded)

**Interfaces:**
- Produces: `SearchView(window, closed_event=None)` — same public surface as today's `SearchWindow` (`lib/windows/search.py`, already fixed in commit `eb84b88` — the `setFocus` crash fix carries over automatically since this is a straight port of the already-fixed source). Constants: `SEARCH_INPUT_ID = 401`, `RESULTS_LIST_ID = 402`, `STATUS_LABEL_ID = 403`, `NEXT_PAGE_BUTTON_ID = 404`.
- Consumes: `lib.twitch.{gql,stream}`, `lib.windows.player`.

Apply the same substitution rules as Task 6. `SearchWindow` already has a real `onClick` (unlike Login/Live-Streams/Discover, which route everything through `onAction`) — port it as `handle_click` unchanged (minus the `getControl` substitution), and `onAction`'s Back block is deleted same as always, leaving:
```python
def handle_action(self, action):
    if action.getId() == xbmcgui.ACTION_SELECT_ITEM:
        if self.window.getFocusId() == self.SEARCH_INPUT_ID:
            self.start_search()
        elif self.window.getFocusId() == self.RESULTS_LIST_ID:
            self.play_selected()
        elif self.window.getFocusId() == self.NEXT_PAGE_BUTTON_ID:
            self.load_next_page()
    if self._update_queue:
        self._process_updates()

def handle_click(self, control_id):
    if control_id == self.SEARCH_INPUT_ID:
        self.start_search()
    elif control_id == self.RESULTS_LIST_ID:
        self.play_selected()
    elif control_id == self.NEXT_PAGE_BUTTON_ID:
        self.load_next_page()
```
`onFocus` (today a no-op `pass`, `lib/windows/search.py:37-38`) is dropped entirely — nothing calls it once this isn't a real `xbmcgui.Window` (Kodi itself called `onFocus`; `MainWindow` never will since it has no reason to forward focus events to views).

- [ ] **Step 1: Write the failing test**

Port `tests/windows/test_search_window.py` (both tests) to `tests/views/test_search_view.py`: `SearchWindow(...)` → `SearchView(FakeWindow())`, `win.onInit()` → `win.activate()`, `win.getFocusId()` → `win.window.getFocusId()`, `win.getControl(...)` → `win.window.getControl(...)`, `win.onAction(...)` → `win.handle_action(...)`. The regression-test docstring's explanation stays accurate (`setFocus` bug already fixed at the source in Task 5's/6's port lineage — no new regression risk here, this is a straight carry-forward).

```python
# tests/views/test_search_view.py
import xbmcgui

from lib.views.search_view import SearchView


class FakeWindow:
    def __init__(self):
        self._controls = {}
        self._focus_id = None

    def getControl(self, control_id):
        from xbmcgui import ControlLabel

        if control_id not in self._controls:
            self._controls[control_id] = ControlLabel()
        return self._controls[control_id]

    def setFocusId(self, control_id):
        self._focus_id = control_id

    def getFocusId(self):
        return self._focus_id


def test_activate_does_not_raise_and_focuses_search_input():
    win = SearchView(FakeWindow())
    win.activate()
    assert win.window.getFocusId() == SearchView.SEARCH_INPUT_ID
    assert win.window.getControl(SearchView.STATUS_LABEL_ID).getLabel() == ""


def test_back_is_a_no_op_pass_through():
    win = SearchView(FakeWindow())
    win.handle_action(xbmcgui.Action(xbmcgui.ACTION_NAV_BACK))
    # No assertion beyond "doesn't raise" - Back is centralized in
    # MainWindow now; SearchView never sees ACTION_NAV_BACK in practice.
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/views/test_search_view.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'lib.views.search_view'`

- [ ] **Step 3: Write `lib/views/search_view.py`**

Apply the substitution rules to the full body of `lib/windows/search.py` (read in full at `lib/windows/search.py:1-129`, post-`eb84b88` fix). Resulting class: `class SearchView:` with `SEARCH_INPUT_ID/RESULTS_LIST_ID/STATUS_LABEL_ID/NEXT_PAGE_BUTTON_ID`, `__init__`, `_safe_control`, `activate` (was `onInit`), `handle_click`/`handle_action` (per above), `start_search`, `load_next_page`, `_process_updates`, `_render_results`, `_update_next_page_button`, `play_selected`.

- [ ] **Step 4: Run tests to verify they pass, then delete the superseded test file**

Run: `python3 -m pytest tests/views/test_search_view.py -v`
Expected: PASS (2 tests)

```bash
git rm tests/windows/test_search_window.py
```

- [ ] **Step 5: Commit**

```bash
git add lib/views/search_view.py tests/views/test_search_view.py
git commit -m "feat: add SearchView controller (ported from SearchWindow)"
```

---

### Task 8: Rewire `lib/main.py`, delete old windows/skins, full-suite verification

**Files:**
- Modify: `lib/main.py` (full rewrite of `run()`)
- Modify: `tests/test_main.py` (full rewrite)
- Delete: `lib/windows/login.py`, `lib/windows/discover.py`, `lib/windows/search.py`, `lib/windows/home.py`
- Delete: `tests/windows/test_login_window.py`, `tests/windows/test_discover_window.py`, `tests/windows/test_home_window.py`
- Delete: `resources/skins/Default/1080i/script-twitch-center-login.xml`, `script-twitch-center-discover.xml`, `script-twitch-center-home.xml`, `script-twitch-center-search.xml`
- Modify: `addon.xml` (version bump + news), `CHANGELOG.md` (new entry)

**Interfaces:**
- Consumes: `MainWindow` (Task 2, now resolving real view classes via `_default_view_classes` since the override is no longer passed), `lib.twitch.auth.load_token`.

- [ ] **Step 1: Write the failing tests for the new `run()`**

```python
# tests/test_main.py
import threading

from lib import main


class FakeAddon:
    def __init__(self, token=None):
        self._token = token

    def getSetting(self, id):
        if id == "twitch_token":
            return '{"access_token": "tok"}' if self._token else ""
        return ""

    def getAddonInfo(self, id):
        if id == "path":
            return "/fake/addon/path"
        return ""


class FakeMonitor:
    def waitForAbort(self, timeout=None):
        raise AssertionError("waitForAbort should not be called when closed_event is already set")


class FakeMainWindow:
    instances = []

    def __init__(self, xml_filename, script_path, *args, initial_view="login", closed_event=None, **kwargs):
        self.xml_filename = xml_filename
        self.script_path = script_path
        self.initial_view = initial_view
        self.shown = False
        self.closed_event = closed_event or threading.Event()
        self.closed_event.set()  # already-closed: run()'s loop exits immediately
        self._views = {"login": _FakeView()}
        FakeMainWindow.instances.append(self)

    def show(self):
        self.shown = True


class _FakeView:
    login_succeeded = False


def test_run_shows_login_view_first_when_no_token_saved():
    FakeMainWindow.instances.clear()
    main.run([], addon=FakeAddon(token=None), main_window_cls=FakeMainWindow, monitor_cls=FakeMonitor)
    assert len(FakeMainWindow.instances) == 1
    assert FakeMainWindow.instances[0].initial_view == "login"
    assert FakeMainWindow.instances[0].shown is True


def test_run_shows_menu_view_first_when_token_saved():
    FakeMainWindow.instances.clear()
    main.run(
        [], addon=FakeAddon(token={"access_token": "tok"}), main_window_cls=FakeMainWindow, monitor_cls=FakeMonitor
    )
    assert FakeMainWindow.instances[0].initial_view == "menu"


def test_run_blocks_until_closed_event_is_set():
    class SlowCloseFakeMainWindow(FakeMainWindow):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.closed_event = threading.Event()

    class TickingMonitor:
        def __init__(self):
            self.calls = 0

        def waitForAbort(self, timeout=None):
            self.calls += 1
            if self.calls >= 2:
                FakeMainWindow.instances[-1].closed_event.set()
            return False

    FakeMainWindow.instances.clear()
    main.run(
        [],
        addon=FakeAddon(token=None),
        main_window_cls=SlowCloseFakeMainWindow,
        monitor_cls=TickingMonitor,
    )
    assert FakeMainWindow.instances[-1].closed_event.is_set()


def test_run_switches_to_menu_when_login_succeeded_flag_is_set():
    FakeMainWindow.instances.clear()

    class FlaggingView:
        login_succeeded = True

    class FlaggingMainWindow(FakeMainWindow):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.closed_event = threading.Event()
            self._views = {"login": FlaggingView()}
            self.switched_to = []

        def _switch_view(self, name):
            self.switched_to.append(name)

    class TickingMonitor:
        def __init__(self):
            self.calls = 0

        def waitForAbort(self, timeout=None):
            self.calls += 1
            if self.calls >= 2:
                FakeMainWindow.instances[-1].closed_event.set()
            return False

    main.run(
        [], addon=FakeAddon(token=None), main_window_cls=FlaggingMainWindow, monitor_cls=TickingMonitor
    )
    assert FakeMainWindow.instances[-1].switched_to == ["menu"]


def test_run_prompts_before_quit_and_exits_when_confirmed():
    FakeMainWindow.instances.clear()

    class QuittingMainWindow(FakeMainWindow):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.closed_event = threading.Event()
            self.closed_event.quit_requested = False

    class TickingMonitor:
        def __init__(self):
            self.calls = 0

        def waitForAbort(self, timeout=None):
            self.calls += 1
            if self.calls == 1:
                FakeMainWindow.instances[-1].closed_event.quit_requested = True
            return False

    prompts = []
    original_prompt = main.show_quit_prompt
    main.show_quit_prompt = lambda: prompts.append(True) or True
    try:
        main.run(
            [],
            addon=FakeAddon(token={"access_token": "tok"}),
            main_window_cls=QuittingMainWindow,
            monitor_cls=TickingMonitor,
        )
    finally:
        main.show_quit_prompt = original_prompt

    assert len(prompts) == 1
    assert FakeMainWindow.instances[0].closed_event.is_set()


def test_run_does_not_quit_when_user_cancels_prompt():
    FakeMainWindow.instances.clear()

    class QuittingMainWindow(FakeMainWindow):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.closed_event = threading.Event()
            self.closed_event.quit_requested = False

    class TickingMonitor:
        def __init__(self):
            self.calls = 0

        def waitForAbort(self, timeout=None):
            self.calls += 1
            if self.calls == 1:
                FakeMainWindow.instances[-1].closed_event.quit_requested = True
            elif self.calls >= 3:
                FakeMainWindow.instances[-1].closed_event.set()
            return False

    prompts = []
    original_prompt = main.show_quit_prompt
    main.show_quit_prompt = lambda: prompts.append(True) or False
    try:
        main.run(
            [],
            addon=FakeAddon(token={"access_token": "tok"}),
            main_window_cls=QuittingMainWindow,
            monitor_cls=TickingMonitor,
        )
    finally:
        main.show_quit_prompt = original_prompt

    assert len(prompts) == 1
    assert FakeMainWindow.instances[0].closed_event.is_set()
    assert not getattr(FakeMainWindow.instances[0].closed_event, "quit_requested", False)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_main.py -v`
Expected: FAIL (`main.run` still has the old `login_window_cls`/`home_window_cls` signature, so `main_window_cls` is an unexpected keyword argument in every test)

- [ ] **Step 3: Rewrite `lib/main.py`**

```python
# lib/main.py
"""Addon entry point, referenced by addon.xml's library="lib/main.py"."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import xbmc
import xbmcaddon
import xbmcgui

from lib.twitch import auth
from lib.windows.main_window import MainWindow


def show_quit_prompt():
    """Display a confirmation dialog when the user attempts to quit."""
    dialog = xbmcgui.Dialog()
    return dialog.yesno(
        "Twitch Center",
        "Are you sure you want to quit?",
        "Your chat and stream will be closed."
    )


def run(argv, addon=None, main_window_cls=None, monitor_cls=None):
    """Construct MainWindow once and block until it closes for real.

    Kodi's xbmc.python.script addons run to completion and tear down; a
    non-modal window (shown via show(), not doModal()) would be destroyed
    the instant run() returns. So after showing the window, block on an
    xbmc.Monitor() wait loop until either Kodi is shutting down or the
    window signals (via its closed_event) that it's done. This is the same
    wait-loop shape as before the persistent-window migration - only window
    construction collapsed from "one per screen transition" to "once, ever"."""
    addon = addon or xbmcaddon.Addon()
    main_window_cls = main_window_cls or MainWindow
    monitor_cls = monitor_cls or xbmc.Monitor

    token = auth.load_token(addon)
    initial_view = "menu" if token else "login"
    window = main_window_cls(
        "script-twitch-center-main.xml",
        addon.getAddonInfo("path"),
        "Default",
        "1080i",
        initial_view=initial_view,
    )
    window.show()

    monitor = monitor_cls()
    while not window.closed_event.is_set():
        if monitor.waitForAbort(1):
            break
        if getattr(window.closed_event, "quit_requested", False):
            if not show_quit_prompt():
                window.closed_event.quit_requested = False
                continue
            window.close()
            window.closed_event.set()
            window.closed_event.quit_requested = False
            break
        login_view = window._views.get("login")
        if login_view is not None and getattr(login_view, "login_succeeded", False):
            window._switch_view("menu")


if __name__ == "__main__":
    run(sys.argv)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_main.py -v`
Expected: PASS (6 tests)

- [ ] **Step 5: Delete superseded files**

```bash
git rm lib/windows/login.py lib/windows/discover.py lib/windows/search.py lib/windows/home.py
git rm tests/windows/test_login_window.py tests/windows/test_discover_window.py tests/windows/test_home_window.py
git rm resources/skins/Default/1080i/script-twitch-center-login.xml
git rm resources/skins/Default/1080i/script-twitch-center-discover.xml
git rm resources/skins/Default/1080i/script-twitch-center-home.xml
git rm resources/skins/Default/1080i/script-twitch-center-search.xml
```

- [ ] **Step 6: Run the full suite**

Run: `python3 -m pytest -q`
Expected: PASS, all tests (check for any remaining import of a deleted module first: `grep -rn "lib.windows.home\|lib.windows.discover\|lib.windows.login\|lib.windows.search\|HomeWindow\|DiscoverWindow\|LoginWindow\|SearchWindow" lib/ tests/` should return nothing outside of historical comments/docstrings that don't affect imports — fix any live import found before considering this step done).

- [ ] **Step 7: Version bump and changelog**

Per `[[feedback_changelog_versioning]]`, bump `addon.xml`'s `version` (minor bump — this is a feature, the new Menu view, plus an architectural fix) and its `<news>` tag, and add a `CHANGELOG.md` entry. Check the current version first (`grep version addon.xml`) and bump accordingly (e.g. `0.14.1` → `0.15.0`). Changelog entry should cover: new landing Menu view; the persistent-window architecture eliminating the window-revert bug for Discover/Search/re-login for good (supersedes the "Known issue" note added in `CHANGELOG.md`'s `0.14.1` entry - that entry's "Known issue" line can now be considered resolved and doesn't need a strikethrough or removal, just a new entry noting the fix).

- [ ] **Step 8: Commit**

```bash
git add lib/main.py tests/test_main.py addon.xml CHANGELOG.md
git commit -m "feat: switch to persistent-window architecture

Replaces per-screen xbmcgui.Window construction with one persistent
MainWindow hosting Login/Menu/Live Streams/Discover/Search as
toggle-able skin groups, eliminating the native Kodi window-manager
revert bug at its source (see the 2026-08-13 design spec). Adds a new
landing Menu view separating navigation from the followed-channel
list."
```

Manual verification after this task (not automatable in this repo's pytest harness, since it depends on live Kodi): restart Kodi clean, launch the addon, and walk Login → Menu → Live Streams → Back → Discover → Back → Search → Back → Menu → Log in again → Back-to-Menu-instead-of-crash, confirming no `PreviousWindow: Deactivate` ever appears in `kodi.log` for any of these transitions. Use the methodology in `[[feedback_live_kodi_testing]]`.
