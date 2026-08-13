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

Separately: today, opening the addon drops straight into the followed-channel
list. There's no landing menu separating "go watch something" from other
options (Discover, Search, Settings, re-login) — they're all crammed onto the
same screen as the channel list itself.

## Goal

1. Eliminate the revert bug at the source: never construct a second
   top-level `xbmcgui.Window*` instance during a session. Fold every screen
   into one persistent window, switching between them by toggling which
   skin `<group>` is visible.
2. Add a landing **Menu** view as the new entry point (after Login): four
   buttons — **Live Streams**, **Discover**, **Search**, **Settings** — plus
   **Log in again**. "Live Streams" leads to a view holding exactly today's
   Home content (followed-channel list + games filter row, otherwise
   unchanged). Menu becomes the new navigational "top" — Back from Live
   Streams/Discover/Search returns to Menu; Back from Menu asks to quit
   (Menu takes over the role Home's Back handling has today).

Out of scope for this spec: the Material 3 card-grid visual redesign of
Discover (separate spec, built afterward on top of this architecture).
Discover's current plain-list visuals carry over unchanged here.

## Architecture

One `xbmcgui.WindowXML` subclass, `MainWindow`
(`lib/windows/main_window.py`), backed by one skin file,
`resources/skins/Default/1080i/script-twitch-center-main.xml`, containing
five `<control type="group">` blocks — one per screen: Login, Menu, Live
Streams, Discover, Search. `MainWindow` owns:

- View switching: `_switch_view(name)` hides all five groups, shows the
  target one, calls the target controller's `activate()`.
- Centralized Back handling in `onAction`, before delegating to the active
  controller: if a stream is playing, stop it; else if the active view is
  Menu, ask for quit-confirmation (existing `main.run()` flow); else switch
  to the Menu view. This replaces several near-identical copies of the same
  Back logic with one, and moves the "top of the stack" role from Home to
  Menu.
- Delegation: `onAction`/`onClick` not handled above are passed to
  `self._active_controller.handle_action(action)` /
  `.handle_click(control_id)`.

Five plain Python controller classes — **not** `Window` subclasses —
hold each screen's logic: `LoginView`, `MenuView`, `LiveStreamsView`,
`DiscoverView`, `SearchView` (`lib/views/login_view.py`, `menu_view.py`,
`live_streams_view.py`, `discover_view.py`, `search_view.py`).
`LiveStreamsView`/`DiscoverView`/`SearchView` are adapted from today's
`HomeWindow`/`DiscoverWindow`/`SearchWindow` bodies almost unchanged, minus
the button-row handling that moves to `MenuView` (see below). `MenuView` is
new: four buttons + Log in again, each `handle_action`/`handle_click`
branch just calls `self.window._switch_view(...)` (or
`xbmcaddon.Addon().openSettings()` for Settings, same native call as
today). Each controller is constructed with a reference to the owning
`MainWindow` (for `getControl`/`setFocusId`/`getFocusId`/`close`
passthrough) and the shared `closed_event`. Today's `onInit` body becomes
`activate()`; today's `onAction`/`onClick` bodies become
`handle_action()`/`handle_click()` (minus Back-handling, now centralized in
`MainWindow`); every other method (search threads, `_render_results`,
`_build_channel_item`, etc.) moves over unchanged.

Cross-screen navigation (`_open_discover_window`, `_open_login_window`,
`_open_search_window` today) collapses to a single call:
`self.window._switch_view("discover")` — no window construction, no
`show()`/`close()` handoff, no per-transition `closed_event` passing (one
`closed_event`, owned by `MainWindow`, shared by construction).

`main.py` shrinks to: decide the initial view from token presence (`"menu"`
if a token exists, else `"login"`), construct `MainWindow` once, `.show()`,
then the existing `monitor.waitForAbort(1)` loop — now watching for two
things instead of window teardown: the shared `closed_event`, and a
`login_succeeded` flag (see Login handoff below).

Player (`lib/windows/player.py`) and `ChatOverlay`
(`lib/windows/chat_overlay.py`) are untouched — they're Kodi's native
fullscreen-video window plus an existing, already-working
`WindowXMLDialog`-over-player overlay, never part of this bug.

## Control ID plan

Control IDs are window-wide in Kodi even inside `<group>` blocks, so each
screen gets its own hundred-block to avoid collisions. The button-row
constants (`DISCOVER_BUTTON_ID`, `SEARCH_BUTTON_ID`, `SETTINGS_BUTTON_ID`,
`RELOGIN_BUTTON_ID`) move off Home/Live-Streams entirely, onto the new Menu
view:

| View | Constant | Old ID (old owner) | New ID |
|---|---|---|---|
| Login | `CODE_LABEL_ID` | 101 (Login) | 101 |
| Login | `URL_LABEL_ID` | 102 (Login) | 102 |
| Login | `STATUS_LABEL_ID` | 103 (Login) | 103 |
| Menu | `LIVE_STREAMS_BUTTON_ID` | — (new) | 501 |
| Menu | `DISCOVER_BUTTON_ID` | 106 (Home) | 502 |
| Menu | `SEARCH_BUTTON_ID` | 109 (Home) | 503 |
| Menu | `SETTINGS_BUTTON_ID` | 108 (Home) | 504 |
| Menu | `RELOGIN_BUTTON_ID` | 104 (Home) | 505 |
| Live Streams | `CHANNEL_LIST_ID` | 101 (Home) | 201 |
| Live Streams | `EMPTY_LABEL_ID` | 102 (Home) | 202 |
| Live Streams | `ERROR_LABEL_ID` | 103 (Home) | 203 |
| Live Streams | `GAMES_LIST_ID` | 105 (Home) | 205 |
| Live Streams | `TITLE_LABEL_ID` | 107 (Home) | 207 |
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

Notes:
- Discover keeps its own `RELOGIN_BUTTON_ID` (304): Discover's relogin
  button today handles a session expiring *while browsing Discover*, a
  different case from Menu's always-visible "Log in again" — both still
  route to `_switch_view("login")`, just from different screens. Live
  Streams' equivalent relogin case (`_show_relogin_prompt` in today's
  `HomeWindow`) now also switches to Menu's relogin path rather than
  needing its own button — Live Streams' error/empty label already
  communicates the problem; the user backs out to Menu and picks "Log in
  again" there. (Simplification worth calling out during implementation
  review — if it reads as worse UX in practice, Live Streams can keep a
  dedicated relogin button too, at ID 204.)
- Each view's top-level `<control type="group">` also gets an ID (100 Login,
  500 Menu, 200 Live Streams, 300 Discover, 400 Search) so
  `MainWindow._switch_view` can `getControl(group_id).setVisible(...)`.

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
polling once a second and, on seeing it, calls `window._switch_view("menu")`
itself (main thread) instead of constructing a new `HomeWindow`.

## File structure

- `lib/windows/main_window.py` — new. `MainWindow(xbmcgui.WindowXML)`:
  `__init__`, `onInit`, `onAction`, `onClick`, `_switch_view`.
- `lib/views/__init__.py` — new, empty.
- `lib/views/login_view.py` — new. `LoginView`, adapted from
  `lib/windows/login.py`'s `LoginWindow` body.
- `lib/views/menu_view.py` — new. `MenuView`: four buttons + Log in again,
  each branch calling `_switch_view` (or `openSettings()` for Settings).
- `lib/views/live_streams_view.py` — new. `LiveStreamsView`, adapted from
  `lib/windows/home.py`'s `HomeWindow` body, minus the button-row handling
  (`DISCOVER_BUTTON_ID`/`SEARCH_BUTTON_ID`/`SETTINGS_BUTTON_ID` branches,
  which move to `MenuView`).
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
- `tests/windows/test_home_window.py`, `test_discover_window.py`,
  `tests/windows/test_search_window.py` → moved/renamed to
  `tests/views/test_live_streams_view.py`, `test_discover_view.py`,
  `test_search_view.py`, adapted to construct the controller directly
  against a fake `window` double instead of instantiating an
  `xbmcgui.WindowXML` subclass (see Testing below).
- `tests/views/test_menu_view.py` — new.
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
`LiveStreamsView(FakeWindow(), closed_event=...)`.

New coverage this spec adds: `tests/windows/test_main_window.py` — view
switching (`_switch_view` hides/shows the right groups, calls `activate()`
on the target controller), centralized Back handling (playing → stop;
Menu + not playing → quit-requested; non-Menu → switches to Menu), and
action/click delegation to whichever controller is active.
`tests/views/test_menu_view.py` — each button's `handle_click`/`handle_action`
calls `_switch_view` with the right target (or `openSettings()` for
Settings).

## Error handling

Unchanged per-view: each controller keeps its own `_safe_control`/try-except
patterns exactly as they exist today. No new error-handling surface is
introduced by this spec beyond what view-switching itself needs (which is a
direct `getControl(group_id).setVisible(bool)` call — no failure mode beyond
what already exists for any `getControl` call).
