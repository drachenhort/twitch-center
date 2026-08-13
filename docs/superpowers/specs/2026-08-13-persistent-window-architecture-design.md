# Persistent Window Architecture — Design Spec

## Problem

Every screen transition beyond the very first custom window in a Kodi session
(Home→Discover, Home→Search, Home→Login/re-login) hits a native Kodi
window-manager bug: the second `xbmcgui.WindowXML`/`WindowXMLDialog` instance
gets silently reverted (`CGUIWindowManager::PreviousWindow: Deactivate`) with
no Python error, sometimes cascading back past our own windows to Kodi's own
built-in Home. This has been investigated exhaustively (see the
`project_second_window_revert_open_issue` memory) and is confirmed to be
independent of window class (`WindowXML` vs `WindowXMLDialog`), trigger path
(`onClick` vs `onAction`), and `defaultcontrol` type — root cause sits in
Kodi's own window manager and is not something addon code can work around by
picking a different window flavor.

## Goal

Eliminate the bug at the source: never construct a second top-level
`xbmcgui.Window*` instance during a session. Fold Login, Home, Discover, and
Search into one persistent window, switching between them by toggling which
skin `<group>` is visible.

Out of scope for this spec: the Material 3 card-grid visual redesign of
Discover (separate spec, built afterward on top of this architecture).
Discover's current plain-list visuals carry over unchanged here.

## Architecture

One `xbmcgui.WindowXML` subclass, `MainWindow`
(`lib/windows/main_window.py`), backed by one skin file,
`resources/skins/Default/1080i/script-twitch-center-main.xml`, containing
four `<control type="group">` blocks — one per screen. `MainWindow` owns:

- View switching: `_switch_view(name)` hides all four groups, shows the
  target one, calls the target controller's `activate()`.
- Centralized Back handling in `onAction`, before delegating to the active
  controller: if a stream is playing, stop it; else if the active view is
  Home, ask for quit-confirmation (existing `main.run()` flow); else switch
  back to the Home view. This replaces four near-identical copies of the
  same Back logic with one.
- Delegation: `onAction`/`onClick` not handled above are passed to
  `self._active_controller.handle_action(action)` /
  `.handle_click(control_id)`.

Four plain Python controller classes — **not** `Window` subclasses —
hold each screen's existing logic almost unchanged: `LoginView`,
`HomeView`, `DiscoverView`, `SearchView` (`lib/views/login_view.py`,
`home_view.py`, `discover_view.py`, `search_view.py`). Each is constructed
with a reference to the owning `MainWindow` (for `getControl`/`setFocusId`/
`getFocusId`/`close` passthrough) and the shared `closed_event`. Today's
`onInit` body becomes `activate()`; today's `onAction`/`onClick` bodies
become `handle_action()`/`handle_click()` (minus the Back-handling lines,
now centralized in `MainWindow`); every other method (search threads,
`_render_results`, `_build_channel_item`, etc.) moves over unchanged.

Cross-screen navigation (`_open_discover_window`, `_open_login_window`,
`_open_search_window` today) collapses to a single call:
`self.window._switch_view("discover")` — no window construction, no
`show()`/`close()` handoff, no per-transition `closed_event` passing (one
`closed_event`, owned by `MainWindow`, shared by construction).

`main.py` shrinks to: decide the initial view from token presence, construct
`MainWindow` once, `.show()`, then the existing `monitor.waitForAbort(1)`
loop — now watching for two things instead of window teardown: the shared
`closed_event`, and a `pending_view_switch` flag (see Login handoff below).

Player (`lib/windows/player.py`) and `ChatOverlay`
(`lib/windows/chat_overlay.py`) are untouched — they're Kodi's native
fullscreen-video window plus an existing, already-working
`WindowXMLDialog`-over-player overlay, never part of this bug.

## Control ID plan

Control IDs are window-wide in Kodi even inside `<group>` blocks, so each
screen gets its own hundred-block to avoid collisions (pure renumbering, no
behavior change):

| View | Constant | Old ID | New ID |
|---|---|---|---|
| Login | `CODE_LABEL_ID` | 101 | 101 |
| Login | `URL_LABEL_ID` | 102 | 102 |
| Login | `STATUS_LABEL_ID` | 103 | 103 |
| Home | `CHANNEL_LIST_ID` | 101 | 201 |
| Home | `EMPTY_LABEL_ID` | 102 | 202 |
| Home | `ERROR_LABEL_ID` | 103 | 203 |
| Home | `RELOGIN_BUTTON_ID` | 104 | 204 |
| Home | `GAMES_LIST_ID` | 105 | 205 |
| Home | `DISCOVER_BUTTON_ID` | 106 | 206 |
| Home | `TITLE_LABEL_ID` | 107 | 207 |
| Home | `SETTINGS_BUTTON_ID` | 108 | 208 |
| Home | `SEARCH_BUTTON_ID` | 109 | 209 |
| Discover | `RESULTS_LIST_ID` | 201 | 301 |
| Discover | `EMPTY_LABEL_ID` | 202 | 302 |
| Discover | `ERROR_LABEL_ID` | 203 | 303 |
| Discover | `RELOGIN_BUTTON_ID` | 204 | 304 |
| Discover | `GAMES_LIST_ID` | 205 | 305 |
| Discover | `SEARCH_EDIT_ID` | 206 | 306 |
| Discover | `SEARCH_BUTTON_ID` | 207 | 307 |
| Discover | `SEARCH_MODE_TOGGLE_ID` | 208 | 308 |
| Search | `SEARCH_INPUT_ID` | 101 | 401 |
| Search | `RESULTS_LIST_ID` | 102 | 402 |
| Search | `STATUS_LABEL_ID` | 103 | 403 |
| Search | `NEXT_PAGE_BUTTON_ID` | 104 | 404 |

Each view's top-level `<control type="group">` also gets an ID (100, 200,
300, 400) so `MainWindow._switch_view` can `getControl(group_id).setVisible(...)`.

## Login handoff (background-thread constraint preserved)

`LoginWindow._on_status("success")` today sets `self.login_succeeded = True`
from a background polling thread, because creating/showing an `xbmcgui`
window must happen on the main thread — `main.run()`'s 1-second monitor loop
picks that flag up and does the actual `HomeWindow` construction on the main
thread. That constraint doesn't disappear just because we're no longer
constructing a new window: `setVisible`/`setFocusId` calls on an existing
window are still Kodi GUI API calls, and this codebase's existing pattern
(also used by Search/Discover's background search threads via
`_update_queue`) is to never call them off the main thread.

`LoginView` keeps the same shape: `_on_status("success")` sets
`self.login_succeeded = True` (unchanged). `main.py`'s monitor loop keeps
polling once a second and, on seeing it, calls
`window._switch_view("home")` itself (main thread) instead of constructing a
new `HomeWindow`.

## File structure

- `lib/windows/main_window.py` — new. `MainWindow(xbmcgui.WindowXML)`:
  `__init__`, `onInit`, `onAction`, `onClick`, `_switch_view`.
- `lib/views/__init__.py` — new, empty.
- `lib/views/login_view.py` — new. `LoginView`, adapted from
  `lib/windows/login.py`'s `LoginWindow` body.
- `lib/views/home_view.py` — new. `HomeView`, adapted from
  `lib/windows/home.py`'s `HomeWindow` body.
- `lib/views/discover_view.py` — new. `DiscoverView`, adapted from
  `lib/windows/discover.py`'s `DiscoverWindow` body (module-level helpers
  `_build_channel_item`/`_build_stream_item` move here too).
- `lib/views/search_view.py` — new. `SearchView`, adapted from
  `lib/windows/search.py`'s `SearchWindow` body.
- `lib/windows/login.py`, `discover.py`, `search.py`, `home.py` — deleted
  once their content has moved.
- `resources/skins/Default/1080i/script-twitch-center-main.xml` — new,
  replaces the four existing per-screen skin files (which get deleted).
- `lib/main.py` — rewritten `run()`, much shorter.
- `tests/windows/test_home_window.py`,
  `test_discover_window.py`,
  `tests/windows/test_search_window.py` → moved/renamed to
  `tests/views/test_home_view.py` etc., adapted to construct the
  controller directly against a fake `window` double instead of
  instantiating an `xbmcgui.WindowXML` subclass (see Testing below).
- `tests/test_main.py` — updated for the new `run()` shape.

## Testing

Controllers no longer inherit `xbmcgui.WindowXML`, so tests construct them
directly with a lightweight stand-in `window` object exposing the same
surface the real `MainWindow` provides (`getControl`, `setFocusId`,
`getFocusId`, `close`, `_switch_view`) — the existing `tests/kodi_stubs`
`WindowXML` stub class already has the right shape for this; tests build one
instance of it and pass it into each controller's constructor instead of the
controller being a `WindowXML` itself. Existing assertions (`getControl(...).getLabel()`,
`getFocusId()`, `closed_event.quit_requested`, etc.) carry over unchanged —
only construction changes, from
`HomeWindow("script-twitch-center-home.xml", "/tmp")` to
`HomeView(FakeWindow(), closed_event=...)`.

New coverage this spec adds: `tests/windows/test_main_window.py` — view
switching (`_switch_view` hides/shows the right groups, calls `activate()`
on the target controller), centralized Back handling (playing → stop;
Home + not playing → quit-requested; non-Home → switches to Home), and
action/click delegation to whichever controller is active.

## Error handling

Unchanged per-view: each controller keeps its own `_safe_control`/try-except
patterns exactly as they exist today. No new error-handling surface is
introduced by this spec beyond what view-switching itself needs (which is a
direct `getControl(group_id).setVisible(bool)` call — no failure mode beyond
what already exists for any `getControl` call).
