# Changelog

All notable changes to this project are documented here. Format loosely follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions follow the addon's own
`version` field in `addon.xml`.

## [0.11.1] - 2026-08-12

### Fixed
- The "Website Token" setting (Settings > General, for ad-free/subscriber-perk playback) never
  actually appeared in the settings dialog, despite being fully implemented and wired into
  playback since it was added. Root cause: a string setting with an empty `<default></default>`
  fails to parse in Kodi (`CSettingString` errors reading the default value), and the setting is
  then silently dropped from the settings dialog entirely - no error visible to the user. Fixed
  with `<constraints><allowempty>true</allowempty></constraints>`, which tells Kodi's settings
  framework the empty default is intentional. Same fix applied to the internal `twitch_token`
  setting, which had the identical bug. Also corrected `settings.xml`'s declared schema version
  (1 → 2) to match its actual structure.

## [0.11.0] - 2026-08-12

### Added
- "Show offline channels on Home" setting (Settings > General, off by default). Turning it on
  restores the pre-v0.10.0 behavior of listing offline followed channels after the live ones,
  sorted alphabetically. Excluded when a game filter is active (an offline channel has no
  `game_name` to filter on) and unaffected by Discover, which never showed offline channels.

## [0.10.0] - 2026-08-12

### Added
- Chat overlay: while a stream plays, incoming Twitch chat now renders automatically as a
  scrolling list along the right edge of the screen (controlled by the existing "Chat display
  mode" setting - shows for "overlay" and "both", not "standalone"). Connects to Twitch IRC
  anonymously (no login needed for reading), auto-reconnects with backoff on drops, and closes
  itself and disconnects cleanly when the stream stops, ends, or fails to start. Foundation IRC
  client work landed separately in the same session; this wires it to a real window for the first
  time.
- A chat overlay failure (bad channel, network blip, anything) never surfaces as a playback
  failure - the stream keeps playing either way, with the problem only logged.

### Known gaps (tracked for follow-up, see `TODO.md`)
- No standalone full-screen chat view yet (`chat_display_mode: "standalone"` still does nothing).
- No picture-in-picture windowed-video layout (video stays fullscreen; chat is a transparent
  overlay on top, not video-in-a-box with chat beside it).
- Not yet verified against a live Kodi session - built and reviewed against the test suite only.

## [0.8.1] - 2026-08-12

### Fixed
- Found and fixed the actual cause of the recurring "stuck on Login" / "gets a new device code
  every time" reports: `script-twitch-center-home.xml`'s `<defaultcontrol always="true">` targeted
  the channel list (control 101), which is empty until `onInit` populates it. Kodi tries to focus
  that control natively, at skin-parse time, before Python's `onInit` ever runs - when it fails,
  Kodi's window manager (`CGUIWindowManager::PreviousWindow`) silently aborts the whole activation
  and reverts to whatever window was previously shown, with no error logged. This only manifested
  when Home wasn't the very first window Kodi ever activated in a session (e.g. after a fresh
  Login hands off to Home), which is why it read as intermittent. No amount of Python-side
  `setFocusId()` (the v0.6.2 fix) could catch this, since it happens before Python runs at all.
  Same root cause and fix as Discover's earlier "flashes then reverts to Home" bug -
  `defaultcontrol` now points at the always-focusable Discover button instead.

## [0.8.0] - 2026-08-12

### Added
- Discover search can now search by game/category as well as channel name. A new toggle button
  next to the search box ("Searching: Channels" / "Searching: Games") switches what the typed
  query searches - game mode uses Twitch's category search (`api.search_categories`,
  Helix `/search/categories`) to find the best-matching game, then lists its live streams via the
  existing `get_live_streams_by_game`. E.g. searching "warships" in game mode finds "World of
  Warships" and lists everyone currently streaming it.

## [0.7.2] - 2026-08-12

### Fixed
- Streams no longer keep playing in the background after pressing Back. Kodi's own
  fullscreen-video Back action only exits the fullscreen view - it doesn't stop playback - so Home
  regained focus with the stream still running, and a second Back press would have closed the
  whole addon while it kept playing. `HomeWindow.onAction` and `DiscoverWindow.onAction` now check
  `xbmc.Player().isPlaying()` on Back and stop the player instead of closing the window when a
  stream is active.

## [0.7.1] - 2026-08-12

### Added
- Settings button on Home, opening Kodi's native addon settings dialog directly (`Addon.openSettings()`)
  instead of requiring the Add-ons browser's context menu - matches the pattern already used in
  the jellyfin-kodi-plex sibling project. Home reloads after the dialog closes, so a newly pasted
  Website Token takes effect immediately rather than needing the addon reopened.

## [0.7.0] - 2026-08-12

### Added
- Optional "Website Token" setting (Settings > General): paste your twitch.tv browser session's
  `auth-token` cookie value to authenticate GQL requests as Twitch's own web client, which
  unlocks ad-free/Turbo/subscriber-perk playback (where your account has it) and fixes the
  followed-games filter row, which has been silently returning empty this whole time due to the
  same root cause as the v0.6.5 playback bug - `get_followed_live_games` was sending our own
  Helix access_token, which `gql.twitch.tv` has always rejected. Both `gql.get_playback_access_token`
  and `gql.get_followed_live_games` now take an optional `website_token` and fall back to their
  existing anonymous/failing-safe behavior when it's absent or no longer valid. No refresh
  mechanism for this token - Twitch itself invalidates it on browser logout, matching the
  behavior of other community Kodi Twitch addons that support this (e.g.
  github.com/Serph91P/plugin.video.twitch's own "Website Token", independently confirmed to hit
  the identical GQL 401 rejection this project hit).

## [0.6.5] - 2026-08-12

### Fixed
- Playback no longer fails with "Your session expired" on every single attempt. Root cause:
  `gql.twitch.tv` (Twitch's internal, unofficial GraphQL API) permanently rejects any real user
  OAuth token issued by a client_id it doesn't own as first-party, regardless of which `Client-Id`
  header accompanies the request - verified directly against the live API with a freshly issued,
  Helix-valid token. No refresh could ever have fixed this; the addon was refreshing a token that
  was never the problem. `gql.get_playback_access_token` now makes the request anonymously (no
  `Authorization` header), which Twitch serves correctly for public live streams -
  `stream.resolve_stream_url` and the `_play_channel` call sites in Home and Discover no longer
  need or accept an access token.

## [0.6.4] - 2026-08-12

### Fixed
- Login screen no longer restarts the device-code flow (fresh code + "waiting for authorization")
  after a login already succeeded. Kodi can re-fire a window's `onInit` while it still considers
  that window current, even after `_on_status("success")` already handed off to Home and the
  polling thread finished - the previous `is_alive()`-only guard didn't cover that case, so a
  finished thread let a second device-code request start on an already-completed login.

## [0.6.3] - 2026-08-12

### Added
- Token refresh failures are now logged with the actual reason (network error, HTTP status +
  response body, or unparseable response) via a new `on_error` callback on
  `auth.refresh_access_token` - previously a failed refresh silently forced re-login with nothing
  in the log to explain why.

## [0.6.2] - 2026-08-12

### Fixed
- Home no longer leaves focus wherever Kodi's fallback search happens to land right after load.
  The skin's `<defaultcontrol always="true">` targets the channel list, but that list is still
  empty at skin-parse time (populated afterward, in Python's `onInit`) - Kodi's focus attempt
  failed every time, silently landing on a nearby button. A stray or buffered keypress arriving in
  that window could trigger unintended navigation (e.g. Relogin) even with a valid session.
  `HomeWindow` now claims focus explicitly once the real screen state is known.

## [0.6.1] - 2026-08-12

### Fixed
- Successful login no longer ends the whole script: `LoginWindow` now opens `HomeWindow` directly
  (same shared-`closed_event` handoff pattern as every other window transition) instead of
  terminating the addon, which forced the user to manually reopen it after every re-login.

## [0.6.0] - 2026-08-12

### Added
- Real stream playback via inputstream.adaptive: clicking a live channel in Home or Discover now
  plays it in Kodi's own player instead of being a no-op.
- New `script.module.inputstreamhelper` addon dependency, used to ensure inputstream.adaptive is
  installed and enabled before playback starts.

## [0.5.0] - 2026-08-11

### Added
- Discover screen: browse live streams for any game (not just followed channels) via a top-games
  row, or search any channel by name.

### Fixed
- Window navigation no longer terminates the Kodi script when opening a new screen (Home →
  Discover, or any re-login hand-off) — a shared `closed_event` now propagates through the whole
  navigation chain instead of each window prematurely signaling the script's exit.
- Focus navigation now reaches every control in the Home and Discover skins (previously some
  buttons/controls were unreachable by remote).

## [0.4.0] - 2026-08-11

### Added
- Followed-games filter row on Home: a row of your real followed live games (via Twitch's
  unofficial internal API, response shape verified against a live capture), selecting one filters
  the channel list to live followed channels playing it.

## [0.3.0] - 2026-08-11

### Added
- Home screen: followed-channels list with live channels surfaced first, thumbnails, viewer counts,
  and game names.
- Transparent access-token refresh so a session persists past Twitch's ~4-hour token expiry instead
  of forcing re-login every time.

### Fixed
- Login code display made large and centered (was barely visible).

## [0.2.0] - 2026-08-11

### Added
- Twitch device-code login flow: displays a code + verification URL, polls in the background,
  saves the resulting token.

## [0.1.0] - 2026-08-11

### Added
- Initial Kodi addon scaffold: manifest, package skeleton (auth/API/stream/chat/UI layers, all
  stubbed), pytest harness.
