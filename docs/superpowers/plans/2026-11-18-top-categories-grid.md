# Top Categories Grid Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A full-screen box-art grid of Twitch's top 100 categories, reached from Discover. Picking a tile opens a page of that category's live streams.

**Architecture:** Two new MainWindow-hosted views, `top_categories` (grid) and `category_streams` (streams page). They mirror the existing `vod_clips_channels`/`vod_clips` two-level pattern and are wired through `GROUP_IDS`, `BACK_TARGET` and `context`. Discover's text-only Twitch top-games row is replaced by a "Browse Twitch Categories" button. Discover's playback code moves to a shared helper so the streams page doesn't copy it.

**Tech Stack:** Python 3, Kodi xbmc/xbmcgui APIs (stubbed in `tests/kodi_stubs`), Kodi skin XML (`resources/skins/Default/1080i/script-twitch-center-main.xml`), pytest.

**Spec:** `docs/superpowers/specs/2026-11-18-top-categories-grid-design.md`

## Global Constraints

- Twitch only. The Kick row and Discover search stay unchanged, apart from Discover's navigation targets.
- The grid loads `first=100` from Helix `/games/top`. Box art is the Helix `box_art_url` template filled at 285x380.
- The category streams page loads `first=100` from `get_live_streams_by_game`. *Plan call: the spec doesn't fix this number. A full page needs more than the default 20.*
- Back from `category_streams` returns to `top_categories` with focus on the same tile and no refetch. Entering `top_categories` from Discover always refetches.
- Skin colours are literal hex only. `$VAR[]` never resolves in script add-ons.
- Kodi `panel` with `<orientation>vertical</orientation>`: the column count comes from panel width ÷ item width. Use a 1824 px panel with 300 px items, giving 6 columns.
- Log prefix `script.twitch.center: `. User-facing copy:
  - Empty grid: `"No categories right now."`
  - Empty category: `"Nobody's live in this category right now."`
  - Network error, missing token and relogin messages: reuse Discover's exact strings.
- Release: version `0.32.0` in `addon.xml`, a `CHANGELOG.md` heading `## [0.32.0] - <release date>`, and a `<news>` line `v0.32.0 (<release date>): ...`, in the same commit as the feature.

## Review Focus

1. **Back to the grid after a failed or empty first load.** Nothing is cached, so the grid must refetch instead of showing a blank screen. Test in Task 3: `test_back_with_no_cached_categories_refetches`.
2. **Refetch after the saved position no longer fits** (a shorter list). The grid must not `selectItem` past the end; the position resets to 0. Test in Task 3: `test_reentry_from_discover_resets_selection`.
3. **A category with no box art.** Helix can return `box_art_url: ""`. The tile still shows the name and building it doesn't crash. Test in Task 3: `test_category_without_box_art_still_renders`.
4. **Token expires while opening a category.** The streams page refreshes the token and retries the same `game_id`, not a different one. Test in Task 4: `test_expired_token_refreshes_and_retries_same_category`.
5. **Playback failure on the streams page.** The error label shows, the streams list stays populated, and the view doesn't switch. Test in Task 4: `test_playback_failure_shows_error_and_keeps_streams`.

---

### Task 1: Shared Twitch/Kick playback helper

**Files:**
- Modify: `lib/views/utils.py` (append the helper)
- Modify: `lib/views/discover_view.py:385-414` (`_play_channel` delegates to the helper)
- Test: `tests/views/test_utils.py`

**Interfaces:**
- Produces: `view_utils.play_channel(platform: str, broadcaster_login: str, show_error: Callable[[str], None], token: dict | None = None, client_id: str | None = None) -> bool`. It returns True when `player.play_stream` reports success. On any failure it calls `show_error(PLAYBACK_ERROR_MESSAGE)` and returns False.
- Produces: `view_utils.PLAYBACK_ERROR_MESSAGE = "Couldn't start playback. Try again."`

- [ ] **Step 1: Write failing tests** in `tests/views/test_utils.py`. Patch `lib.views.utils.providers.resolve_stream_url` and `lib.views.utils.player.play_stream`.
  - `test_play_channel_twitch_passes_token_fields`: `play_stream` is called with `(url, "alice", platform="twitch", access_token="tok", client_id="cid", user_id="u1")` and the result is True.
  - `test_play_channel_kick_passes_platform_only`: called with `(url, "bob", platform="kick")`.
  - `test_play_channel_stream_start_error_shows_dialog_and_error`: `resolve_stream_url` raises `providers.StreamStartError("why")`, `xbmcgui.Dialog().ok` is called with `("Couldn't start stream", "why")`, `show_error` gets `PLAYBACK_ERROR_MESSAGE`, and the result is False.
  - `test_play_channel_unavailable_and_unexpected_errors_show_error`: covers both `StreamUnavailableError` and `RuntimeError`. Each calls `show_error` once and returns False.
  - `test_play_channel_play_stream_false_shows_error`.
- [ ] **Step 2: Run** `pytest tests/views/test_utils.py -v`. Expected: the new tests FAIL with `AttributeError: ... play_channel`.
- [ ] **Step 3: Implement `play_channel`** by moving the body of `DiscoverView._play_channel` into it (same exception ladder and log line, generalised to "channel selection failed"). Then `DiscoverView._play_channel` calls `view_utils.play_channel(..., show_error=self._show_results_error)` and clears the error label on True. Import `providers` and `player` in `utils.py` lazily, or at module level if that creates no import cycle. Check with `python -c "import lib.views.utils"` under the test stubs (run the pytest suite).
- [ ] **Step 4: Run** `pytest tests/views -v`. Expected: everything PASSES, including Discover's existing playback tests unchanged. If they patch `lib.views.discover_view.player.play_stream`, update those patch targets to `lib.views.utils.player.play_stream` only.
- [ ] **Step 5: Commit** with the message `Extract shared channel playback helper from Discover`.

### Task 2: Box-art-aware top games call

**Files:**
- Modify: `lib/twitch/api.py:99-103`
- Test: `tests/twitch/test_api.py:116-129`

**Interfaces:**
- Produces: `api.get_top_games(access_token, client_id, first=20) -> list[{"id": str, "name": str, "box_art_url": str}]`. `box_art_url` is the raw Helix template (still containing `{width}x{height}`), or `""` when it's missing.

- [ ] **Step 1: Update the test.** Rename it to `test_get_top_games_returns_id_name_and_box_art`. Expected items now include `"box_art_url": "https://example.invalid/1.jpg"`. Add `test_get_top_games_defaults_missing_box_art_to_empty`: an entry without the key gives `""`. Add `test_get_top_games_passes_first`: `first=100` puts `params["first"] == 100`.
- [ ] **Step 2: Run** `pytest tests/twitch/test_api.py -k top_games -v`. Expected: FAIL.
- [ ] **Step 3: Implement** by adding `"box_art_url": game.get("box_art_url") or ""` to each dict.
- [ ] **Step 4: Run** the same command. Expected: PASS.
- [ ] **Step 5: Commit** with the message `Return box art URL from get_top_games`.

### Task 3: TopCategoriesView (grid)

**Files:**
- Create: `lib/views/top_categories_view.py`
- Test: `tests/views/test_top_categories_view.py` (copy the `FakeWindow` and `_addon_with_token` helpers from `tests/views/test_vod_clips_channels_view.py`)

**Interfaces:**
- Consumes: `api.get_top_games` (Task 2), `view_utils.thumbnail_url(raw_url, width, height)`, `auth.load_token/clear_token/refresh_access_token/save_token`.
- Produces: class `TopCategoriesView(window, closed_event=None)` with:
  - Constants: `GROUP_ID = 1000`, `CATEGORY_LIST_ID = 1001`, `EMPTY_LABEL_ID = 1002`, `ERROR_LABEL_ID = 1003`, `RELOGIN_BUTTON_ID = 1004`, `TITLE_LABEL_ID = 1005`.
  - Navigation attributes: `DEFAULT_FOCUS_ID = 1001`, `BACK_TARGET = "discover"`.
  - Methods: `activate()`, `handle_action(action)`, `handle_click(control_id)`, `context` attribute.
- Contract: Discover switches here with `context={"refresh": True}`. Selecting a tile calls `window._switch_view("category_streams", context={"game_id": id, "game_name": name})`.
- Each ListItem has the label set to the name, the property `game_id`, and art `{"thumb": thumbnail_url(box_art_url, 285, 380)}` (no art when `box_art_url` is empty).

- [ ] **Step 1: Write failing tests:**
  - `test_activate_loads_top_100_with_box_art`: `get_top_games` is called with `first=100`. The list holds 2 items with labels `["Just Chatting", "League of Legends"]`. Item 0 has art thumb `"https://x.invalid/509658-285x380.jpg"` from template `"https://x.invalid/509658-{width}x{height}.jpg"`. Focus is on `CATEGORY_LIST_ID`.
  - `test_selecting_a_tile_opens_category_streams`: select item 1 with `ACTION_SELECT_ITEM` while focused on the list. Then `window.switched_to[-1] == ("category_streams", {"game_id": "21779", "game_name": "League of Legends"})`.
  - `test_back_from_streams_restores_selection_without_refetch`: activate with refresh, select item 1, then select it again. Set `view.context = None` and call `activate()` again. `get_top_games` has been called exactly once, the list has size 2, and `getSelectedPosition() == 1`.
  - `test_reentry_from_discover_resets_selection` (Review Focus 2): after selecting item 1, re-activate with `context={"refresh": True}` and a 1-item result. Then `get_top_games` has 2 calls and the selected position is 0.
  - `test_back_with_no_cached_categories_refetches` (Review Focus 1): the first activate raises `requests.ConnectionError` and the error label is non-empty. The second activate with `context=None` succeeds, `get_top_games` has 2 calls, and the list has items.
  - `test_category_without_box_art_still_renders` (Review Focus 3).
  - `test_empty_result_shows_message`: the empty label is `"No categories right now."`.
  - `test_missing_token_shows_error_and_relogin`.
  - `test_expired_token_refreshes_then_loads`: the first `get_top_games` raises `api.TokenExpiredError`, `auth.refresh_access_token` returns a new token, and the second call succeeds and populates the list.
  - `test_relogin_button_switches_to_login`.
- [ ] **Step 2: Run** `pytest tests/views/test_top_categories_view.py -v`. Expected: FAIL (module missing).
- [ ] **Step 3: Implement `TopCategoriesView`.** Keep state in `self._categories: list` and `self._selected: int`. In `activate`:
  - Set the title label to `"Top Categories"`.
  - Refetch when `(self.context or {}).get("refresh")` is set or `self._categories` is empty. Otherwise repopulate from cache.
  - After populating, `selectItem(min(self._selected, size-1))` and focus the list.
  - Errors and token expiry follow `VodClipsChannelsView`'s structure (`_show_error`, `_handle_expired_token`, relogin button).
  - Record `self._selected = control.getSelectedPosition()` before switching to `category_streams`.
- [ ] **Step 4: Run** the test file. Expected: PASS.
- [ ] **Step 5: Commit** with the message `Add Top Categories grid view`.

### Task 4: CategoryStreamsView

**Files:**
- Create: `lib/views/category_streams_view.py`
- Test: `tests/views/test_category_streams_view.py`

**Interfaces:**
- Consumes: `api.get_live_streams_by_game(access_token, client_id, game_id, first=100)`, `view_utils.build_stream_item`, `view_utils.play_channel` (Task 1), and context `{"game_id", "game_name"}` (Task 3).
- Produces: class `CategoryStreamsView(window, closed_event=None)` with:
  - Constants: `GROUP_ID = 1100`, `STREAM_LIST_ID = 1101`, `EMPTY_LABEL_ID = 1102`, `ERROR_LABEL_ID = 1103`, `RELOGIN_BUTTON_ID = 1104`, `TITLE_LABEL_ID = 1105`.
  - Navigation attributes: `DEFAULT_FOCUS_ID = 1101`, `BACK_TARGET = "top_categories"`.
- No context menu. Every item is a Twitch stream, and Discover's context menu only acts on Kick items.

- [ ] **Step 1: Write failing tests:**
  - `test_activate_lists_streams_for_context_game`: `get_live_streams_by_game` is called with `("tok", <client_id>, "509658", first=100)`. The title label is `"Just Chatting"`, the list size matches the stub, and focus is on the list.
  - `test_missing_context_switches_back_to_grid`: with `context=None`, `switched_to[-1] == ("top_categories", None)`. This mirrors `VodClipsView`'s guard; check `lib/views/vod_clips_view.py:47` and copy its behaviour.
  - `test_empty_category_shows_message`: the empty label is `"Nobody's live in this category right now."`.
  - `test_selecting_stream_plays_it`: `view_utils.play_channel` is called with `("twitch", "alice", show_error=..., token=<token>, client_id=<client_id>)`.
  - `test_playback_failure_shows_error_and_keeps_streams` (Review Focus 5): use the real `play_channel` with `resolve_stream_url` raising `StreamUnavailableError`. The error label is non-empty, the list size is unchanged, and `switched_to` is empty.
  - `test_expired_token_refreshes_and_retries_same_category` (Review Focus 4): both calls to `get_live_streams_by_game` received `"509658"`.
  - `test_network_error_shows_error`.
- [ ] **Step 2: Run** `pytest tests/views/test_category_streams_view.py -v`. Expected: FAIL.
- [ ] **Step 3: Implement** following `VodClipsView`'s structure: a context guard, then load, then populate with `build_stream_item`, plus error/relogin handling. Play through `view_utils.play_channel(..., show_error=self._show_list_error)`, where `_show_list_error` only sets the error label.
- [ ] **Step 4: Run** the test file. Expected: PASS.
- [ ] **Step 5: Commit** with the message `Add category streams view`.

### Task 5: Wire into MainWindow, Discover and skin

**Files:**
- Modify: `lib/windows/main_window.py:12-20` (`GROUP_IDS` gains `"top_categories": 1000` and `"category_streams": 1100`), plus the default view registry around lines 40-56.
- Modify: `lib/views/discover_view.py`:
  - Remove `GAMES_LIST_ID`, `_populate_games`, `_on_game_selected`, `_EMPTY_GAMES_MESSAGE`, and the `get_top_games` call. Rename `_load_games` to `_load_rows`, which loads the Kick row only.
  - Add `BROWSE_CATEGORIES_BUTTON_ID = 310`. When it's selected: `window._switch_view("top_categories", context={"refresh": True})`.
  - After load, `activate` focuses `BROWSE_CATEGORIES_BUTTON_ID`.
  - Update the module docstring.
- Modify: `resources/skins/Default/1080i/script-twitch-center-main.xml`:
  - Discover: replace the "TWITCH:" label and list 305 (lines ~637-692) with button 310 at posx 48, posy 210, 1824x70, label `Browse Twitch Categories`, styled like buttons 307/308.
  - Navigation: 306/307/308 `ondown` to 310. Button 310 `onup` to 306 and `ondown` to 309. List 309 `onup` to 310.
  - New group 1000 after group 800:
    - Title label 1005 (same style and position as 705).
    - Panel 1001 at posx 48, posy 140, 1824x900, `<orientation>vertical</orientation>`, `onleft`/`onright`/`onup`/`ondown` to 1001.
    - Itemlayout 300x420: a 260x347 `$INFO[ListItem.Art(thumb)]` image at 20,10 with `<aspectratio>keep</aspectratio>`, and a 260x50 name label below it (font `CardHeadline`, colour `FFE6E1E5`, centred, scrolling in the focused layout).
    - Focusedlayout: the same layout with a `card_surface_focus.png` frame behind it, `colordiffuse ff0a6ed3`, name colour `FFFFFFFF`.
    - Empty label 1002, error label 1003 and relogin button 1004, styled like 702-704.
  - New group 1100: title label 1105, panel 1101 copying Discover panel 301's position, size, item and focused layouts exactly (IDs and navigation pointed at 1101), and labels 1102/1103 plus button 1104 styled like 302-304.
- Test: `tests/views/test_discover_view.py`, `tests/windows/test_main_window.py`

- [ ] **Step 1: Update Discover tests:**
  - Delete the tests that exist only for the games row: `test_oninit_populates_top_games`, `test_selecting_a_game_populates_results_with_stream_items`, `test_empty_top_games_shows_a_message_instead_of_a_blank_row`, `test_game_select_failure_keeps_the_top_games_row_intact`, `test_expired_token_during_game_select_retries_that_game_after_refresh`.
  - Rework the playback tests that reached results through the games row so they reach results through game-mode search (`search_categories` + `get_live_streams_by_game`) instead.
  - Remove `get_top_games` patches and `games_control` assertions.
  - Add `test_browse_categories_button_opens_grid_with_refresh`: `switched_to[-1] == ("top_categories", {"refresh": True})`.
  - Add `test_activate_focuses_browse_categories_button`.
  - Add `test_activate_does_not_call_get_top_games`.
- [ ] **Step 2: Add MainWindow tests:** `test_group_ids_include_category_views` (1000/1100), and `test_back_from_category_streams_goes_to_top_categories` using `FakeView` subclasses with those `BACK_TARGET`s via `view_classes`.
- [ ] **Step 3: Run** `pytest tests/views/test_discover_view.py tests/windows/test_main_window.py -v`. Expected: the new tests FAIL.
- [ ] **Step 4: Implement** the Discover, MainWindow and skin changes above. Check the skin XML is well-formed with `python -c "import xml.etree.ElementTree as E; E.parse('resources/skins/Default/1080i/script-twitch-center-main.xml')"`. Also check no control ID is duplicated: `grep -o 'id="[0-9]*"' <skin> | sort | uniq -d` must print nothing.
- [ ] **Step 5: Run** `pytest -q`. Expected: the whole suite PASSES.
- [ ] **Step 6: Commit** with the message `Open Top Categories grid from Discover`.

### Task 6: Release 0.32.0 and live check

**Files:**
- Modify: `addon.xml` (version `0.32.0`, prepend the `<news>` line)
- Modify: `CHANGELOG.md` (a new `## [0.32.0] - <release date>` with `### Added` and `### Changed`)

- [ ] **Step 1: Bump the version and write the changelog.**
  - `### Added`: Discover's new "Browse Twitch Categories" button opens a grid of the top 100 Twitch categories with box art; picking one lists its live streams.
  - `### Changed`: the text-only Twitch top-games row on Discover is replaced by that button.
  - News line: `v0.32.0 (<release date>): Browse the top 100 Twitch categories as a box-art grid from Discover.`
- [ ] **Step 2: Run** `pytest -q`. Expected: all PASS, including the `tests/test_addon_manifest.py` news/version checks.
- [ ] **Step 3: Commit** with the message `Top Categories box-art grid (0.32.0)`. The commit includes the feature's version bump, as CLAUDE.md requires.
- [ ] **Step 4: Live check on local Kodi (ask the user before running anything on Kodi).**
  1. Full `rsync --delete` of `lib/` and `resources/` into the local `~/.kodi/addons/script.twitch.center` before restarting Kodi.
  2. Clean-restart Kodi.
  3. Open the addon, go to Discover, open Browse Twitch Categories. Confirm the 6-column grid scrolls vertically with box art, a tile opens its streams, a stream plays, and Back lands on the same tile.
  4. Report what you see. Don't claim the grid layout works without the user seeing it.
