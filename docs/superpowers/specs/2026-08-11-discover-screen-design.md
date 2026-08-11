# Discover Screen: Design

Date: 2026-08-11

## What this is

Replaces `lib/windows/discover.py`'s no-op stub with a real Discover screen: browse currently-live
Twitch streams by game (any streamer, not just followed channels — genuine discovery, distinct from
Home's followed-games filter row which only ever shows *your* followed channels), plus free-text
channel search. Opened from a new "Discover" button on the Home screen.

## Why this is separate from Home's games row

Home already has a followed-games filter row (`docs/superpowers/specs/2026-08-11-followed-games-filter-design.md`)
that filters your followed channels by game they're currently playing. That never surfaces a
streamer you don't already follow. Discover is the opposite: pick any popular game, or search any
channel name, and see results regardless of whether you follow them.

## Components

### `lib/twitch/api.py` (extended — official Helix, same trust tier as existing calls)

- `get_top_games(access_token, client_id, first=20) -> list[dict]` — **new**, Helix `/games/top`.
  Returns `[{"id": ..., "name": ...}, ...]` (Twitch's top-viewed game categories right now). Not
  previously stubbed by the original scaffold.
- `get_live_streams_by_game(access_token, client_id, game_id, first=20) -> list[dict]` — **replaces**
  the existing `NotImplementedError` stub (which had the old scaffold-guessed signature without
  `client_id` — same kind of deliberate signature supersession every other real `api.py` function
  went through). Helix `/streams?game_id=`. Same response shape as `get_live_status`'s stream
  objects (`user_id`, `user_login`, `user_name`, `game_name`, `title`, `viewer_count`,
  `thumbnail_url`, `started_at`).
- `search_channels(access_token, client_id, query, live_only=True, first=20) -> list[dict]` —
  **replaces** the existing stub, same signature-supersession reasoning. Helix `/search/channels`.
  Defaults `live_only=True` — search results are, by default, restricted to currently-live channels
  (matches this app's live-focused purpose throughout: Home only ever shows live-first, this screen
  is about finding something to watch *now*). Response shape is a **channel** object, not a stream
  object: `broadcaster_login`, `display_name`, `is_live`, `game_name`, `thumbnail_url` — no
  `viewer_count`, and `thumbnail_url` here is a static per-channel image, not the sized
  `{width}x{height}`-placeholder stream-preview URL `get_live_status`/`get_live_streams_by_game`
  return.
- `get_games_for_channels` stays untouched (`NotImplementedError`) — not needed by this design,
  left as-is per the original scaffold, not this task's concern.

### `lib/windows/discover.py` (replaces stub logic)

- `onInit`: loads the token (same pattern as `HomeWindow` — missing/no-`user_id` token shows a
  re-login state, reuses `auth.load_token`/`auth.refresh_access_token`/`auth.clear_token`'s existing
  refresh-then-reprompt flow since a Discover-screen visit needs the same valid token Home does),
  fetches top games via `api.get_top_games`, populates the top-games row. The results list starts
  empty until the user picks a game or searches.
- Selecting a game in the top-games row: fetches `api.get_live_streams_by_game(..., game_id)`,
  populates the shared results list using the **stream** item builder (thumbnail + viewer count).
- Pressing the Search button: reads the search `<edit>` control's current text, calls
  `api.search_channels(..., query)`, populates the shared results list using the **channel** item
  builder (no viewer count, static thumbnail, live/offline indicator via `is_live`).
- The results list is genuinely shared (one control) — whichever action (game select or search) ran
  most recently is what's currently shown. No simultaneous dual display.
- Clicking a result does nothing yet — same limitation as Home (`lib/twitch/stream.py`'s playback
  resolution is still a stub). Not addressed by this task.

### Skin XML (new)

`resources/skins/Default/1080i/script-twitch-center-discover.xml` — top-games horizontal list row,
a search `<edit>` control + Search button, and a results list below, following the same
large-centered-text and list-item conventions established by the login and Home screens.

### `resources/skins/Default/1080i/script-twitch-center-home.xml` (extended)

New "Discover" button, opens `DiscoverWindow` the same way the existing "Log in again" button
already opens `LoginWindow` (`_open_login_window`'s pattern: construct with
`("script-twitch-center-discover.xml", addon.getAddonInfo("path"), "Default", "1080i")`, `.show()`).

## Data flow

```
HomeWindow: "Discover" button selected
  -> construct + show DiscoverWindow, close Home (one-way, same as every existing window transition)

DiscoverWindow.onInit
  -> auth.load_token / refresh-then-reprompt (same as Home)
  -> api.get_top_games(...) -> populate top-games row

Top-games row: game selected
  -> api.get_live_streams_by_game(..., game_id) -> populate results list (stream item builder)

Search button pressed
  -> read edit control text -> api.search_channels(..., query) -> populate results list (channel item builder)
```

Opening Discover follows the same window-stacking pattern the existing "Log in again" button
already established in `_open_login_window` — construct and `.show()` the new window, close the
current one, so only one window is ever alive/blocking the `xbmc.Monitor` wait loop in
`lib/main.py`'s style (Discover reuses the same `closed_event`/`onAction` Back-closes-and-signals
pattern every other window in this project already has). Back from Discover does not return to
Home automatically — it closes the addon, same as Back from Home does today. (A "return to Home"
richer navigation stack is out of scope — consistent with this project's YAGNI posture so far;
every window transition to date has been one-way.)

## Error handling

- Network failure on `get_top_games`: error message, no top-games row (screen still usable for
  search, if the user already knows what they're searching for — search failure is independent).
- Network failure on `get_live_streams_by_game` or `search_channels`: error message in place of the
  results list, doesn't clear the top-games row.
- Empty top-games list, empty stream results, or empty search results: friendly "nothing found"
  message, not a blank list.
- Token expiry: same refresh-then-reprompt flow as Home, reusing `auth.refresh_access_token` /
  `auth.clear_token`. A re-login triggered from Discover opens `LoginWindow` the same way Home's
  re-login button does.

## Testing

- `lib/twitch/api.py`: `get_top_games`, `get_live_streams_by_game`, `search_channels` each tested
  with mocked `requests` — success, empty results, 401→`TokenExpiredError`, matching the existing
  test patterns for every other `api.py` function.
- `lib/windows/discover.py`: tested via `tests/kodi_stubs/`, all `api`/`auth` calls injected/faked,
  no real network — covers top-games population, game-select-populates-results,
  search-populates-results (with the two different item shapes correctly distinguished), token
  refresh/expiry reusing the same test patterns Home's suite already established.
- No test hits Twitch's real API.

## Out of scope for this task

- Clicking a result to play it (still deferred, same as Home).
- Returning to Home from Discover (Back closes the addon, consistent with existing one-way window
  navigation).
- Category/game box art images (text-only game names in the top-games row, consistent with Home's
  followed-games row).
- Pagination beyond Helix's default page size (`first=20`) for any of the three new/changed calls —
  a fixed-size single page is enough for a browse/discovery screen; no infinite scroll.
- `get_games_for_channels` (untouched, unrelated to this design).
