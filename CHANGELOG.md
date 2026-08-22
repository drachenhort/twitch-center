# Changelog

All notable changes to this project are documented here. Format loosely follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions follow the addon's own
`version` field in `addon.xml`.

## [0.21.0] - 2026-08-22

### Added
- First sub-project of Kick.com integration (not usable yet - unwired): a new `lib/kick/`
  package providing OAuth 2.1 Authorization Code + PKCE login (via a local loopback HTTP
  server since Kick has no device-code flow like Twitch), a Public API client
  (channel/live-streams/categories/user lookups, plus an isolated unofficial search
  fallback), and stream URL resolution - mirroring `lib/twitch/`'s shape so a later
  sub-project can wire both platforms through the same UI with minimal branching. Adds
  four new Settings entries (Kick Client ID, Client Secret, OAuth redirect port, saved
  token) - all advanced/hidden except Client ID, which needs a value from a
  self-registered Kick OAuth app to eventually work. Nothing in the running app calls this
  package yet; login/browsing/playback/chat for Kick land in follow-up releases.

## [0.20.0] - 2026-08-22

### Removed
- The "standalone chat window" and "both" chat display modes. `standalone` was never implemented
  beyond a stub (`lib/windows/chat_window.py`, now deleted) and always showed no chat at all;
  `both` behaved identically to `overlay` since nothing else consumed the third mode. Replaced the
  three-way `chat_display_mode` string setting with a single `chat_overlay_enabled` boolean
  ("Show chat overlay while playing"), defaulting on. Anyone previously on `standalone` will now
  see the chat overlay by default during playback - turn the new setting off to keep it hidden.

## [0.19.0] - 2026-08-22

### Added
- Version number and release date now shown in the top-left corner of the main window, across
  every screen (Login/Menu/Live Streams/Discover/Search) - a persistent label outside the
  view-toggling groups, set once from `addon.xml`'s version plus a release-date constant kept in
  sync with it in `lib/main.py`.

## [0.18.0] - 2026-08-22

### Changed
- Variable-size chat overlay (`chat_overlay_variable_height`) now defaults to `true` - still only
  takes effect when `chat_engine` is `eventsub`, same as before.

### Fixed
- `VariableChatOverlay`'s message wrapping had silently dropped its own line cap: `_wrap_message_lines()`
  no longer applied `_MAX_MESSAGE_LINES` (9), so an unusually long chat message could wrap to far more
  lines than intended, producing an oversized block that could exceed the column height outright.
  Restored truncation at 9 lines (with a trailing `...`), matching `ChatOverlay`'s existing pattern.
- `play_stream()` could silently fail to start playback at all: when the chat-overlay setup path
  (`chat_display_mode` is `overlay`/`both`) raised partway through - broadcaster-id lookup, overlay
  construction, `overlay.show()`, or the player callback wiring - the exception was logged but nothing
  played the stream, since the `xbmc.Player().play()` call had been moved inside that same `try` block.
  Added a fallback `xbmc.Player().play()` call in the exception handler so playback still starts
  without chat if overlay setup fails.

## [0.17.3] - 2026-08-22

### Fixed
- Live re-test of v0.17.2 found the remaining garbling was never a sizing issue - it always
  appeared at whatever message sat at the column's top edge, blended with content from an
  already-evicted message. Root cause: `VariableChatOverlay._render()` built controls for every
  new message first, then evicted overflow afterward in the same call - so a burst of messages
  arriving in one throttled tick could get `addControl()`'d and then `removeControl()`'d again
  within that same call. Kodi's `addControl()` appears to complete asynchronously on at least one
  tested build (kodi.local, LibreELEC/Kodi 22), so the same-tick removal could run before the add
  had actually taken effect, leaving an orphaned control rendered at its stale creation position.
  Restructured `_render()` to compute the eviction cutoff across existing and pending-new messages
  together *before* creating any new controls, so a message that would be evicted immediately is
  now never materialized as a control in the first place. Added
  `test_burst_of_messages_never_adds_a_control_only_to_evict_it_same_tick` covering this directly.

## [0.17.2] - 2026-08-22

### Fixed
- Live re-test of v0.17.1's cross-build safety margins on kodi.local found the overlap reduced but
  not eliminated: a residual ~1-line-tall graze remained specifically at the boundary between one
  message's last line and the next message's username, never within a single message's own wrapped
  lines. Increased `_BLOCK_MARGIN` in `lib/windows/variable_chat_overlay.py` from 10px to 34px - the
  constant that exists specifically to pad inter-message spacing.

## [0.17.1] - 2026-08-22

### Fixed
- The new variable-size chat overlay (v0.17.0) rendered with overlapping, garbled text on kodi.local
  (LibreELEC, Kodi 22) even though it rendered correctly on a Kodi 21.3 dev machine - real text
  height for the same declared font size differed enough between the two builds/platforms to matter.
  Because each message block's position is computed from the cumulative height of the blocks above
  it (unlike `ChatOverlay`'s independently fixed-size rows), this per-line error compounded across
  the handful of messages simultaneously visible, producing severe overlap after a few messages
  arrived rather than a small, easy-to-miss drift. `_USERNAME_ROW_HEIGHT` (26→40), `_LINE_PITCH`
  (42→60), and `_EMOTE_ROW_HEIGHT` (28→36) in `lib/windows/variable_chat_overlay.py` are now
  deliberately padded well past the tightest value that worked on any single tested device, plus a
  new fixed `_BLOCK_MARGIN` (10px) added to every block, trading some of the feature's space-saving
  benefit for correctness across builds.

## [0.17.0] - 2026-08-22

### Added
- New "Variable-size chat overlay" setting (Settings > General), off by default. When enabled and
  the EventSub chat engine is selected, chat messages size their on-screen box to their actual
  wrapped line count instead of the fixed-box overlay's 270px slot reserved for the worst-case
  5-line message. Built by placing Kodi controls directly rather than through the skin's `<list>`
  control, which can't vary row height per item - see
  `docs/superpowers/specs/2026-08-22-variable-height-chat-overlay-design.md`.

## [0.16.5] - 2026-08-22

### Fixed
- Chat overlay message box was undersized for the message-wrapping cap: `_MAX_MESSAGE_LINES` (5)
  needed roughly 200px at the message label's line height, but the label was only 140px tall, so
  a 4th/5th line could spill past its bottom edge into the emote-icon row. Grew the message label
  to 210px and moved the emote row and per-item row height down to match, so all 5 possible lines
  render inside their own box.

## [0.16.4] - 2026-08-22

### Fixed
- Chat overlay message label now explicitly sets `<aligny>top</aligny>`. Without it, some Kodi
  builds anchor a short single-line label vertically (bottom/center) within its allotted box
  instead of the top, which reads as a blank line above the message text - most visible on
  single-line messages, since multi-line messages already nearly fill the box height.

## [0.16.3] - 2026-08-22

### Fixed
- Chat overlay message label no longer sets both a manual `\n`-wrapped label and the skin's
  `wrapmultiline` flag on the same control. Kodi's own wrap pass, layered on top of the already
  hand-wrapped text, could add a stray blank line above the first line of a message.

## [0.16.2] - 2026-08-20

### Fixed
- Chat overlay message list is now updated incrementally (append new rows, drop evicted ones)
  instead of a full reset()+addItems() rebuild on every render tick. Previously, every new
  message caused the entire list to be rebuilt, which re-created already-displayed messages'
  list items and re-triggered their EventSub emote art loads - visible as an emote image popping
  in several renders after its message had already appeared, once its underlying Kodi texture
  finally finished loading.

## [0.16.1] - 2026-08-18

### Added
- EventSub chat messages now show a row of real emote images (up to 6 per message) beneath the
  message text, sourced from Twitch's public emote CDN (static, dark theme, 1x scale). IRC chat
  messages keep rendering as plain text exactly as before - the only shared side effect is that
  each message row is now taller to fit the new emote strip's space, so slightly fewer messages
  fit on screen at once for both chat engines.

## [0.16.0] - 2026-08-18

### Added
- New "Chat engine" setting (Settings > General): choose between the existing anonymous IRC chat
  (default, no login needed) and Twitch's officially-supported EventSub chat API (requires login).
  EventSub is available on Live Streams and Discover tabs; if broadcaster ID resolution fails,
  chat falls back to IRC automatically. If the EventSub subscription itself fails (e.g. a saved
  login predates this version's chat scope), chat stays empty and keeps retrying - use "Log in
  again" to refresh your login. Search results don't support EventSub (unauthenticated feature) -
  chat won't be shown when EventSub is selected for Search playback.

## [0.15.2] - 2026-08-14

### Fixed
- Chat overlay messages no longer get cut off mid-word. The skin's `wrapmultiline` label tag
  isn't honored on this Kodi build, so long chat messages now get manually wrapped and capped
  at a fixed number of lines (with a clean "..." if still too long) before being set on the
  label, instead of relying on the skin to wrap them.

## [0.15.1] - 2026-08-14

### Changed
- No functional change - re-deploy marker for kodi.local install.

## [0.15.0] - 2026-08-13

### Added
- New landing Menu view - the addon now opens (or returns, via Back) to a menu that lets you
  choose Live Streams, Discover, or Search, separating navigation from the followed-channel list
  that used to live on Home.

### Changed
- Rewired the whole UI onto a single persistent `MainWindow` that hosts every screen (Login,
  Menu, Live Streams, Discover, Search) as a toggle-able skin group, instead of constructing a
  brand-new `xbmcgui` window for each screen transition. This eliminates the native Kodi
  window-manager revert bug at its source - see the 2026-08-13 persistent-window-architecture
  design spec - which fully resolves the "Known issue" noted in the 0.14.1 entry below for
  Search, and the analogous issue previously tracked for Discover and re-login: a second-window
  activation reverting with no error is no longer possible when there is only ever one window.

### Fixed
- Keyboard/remote focus went nowhere after switching screens: the skin's `<defaultcontrol>` only
  applies once, natively, before `onInit` runs, so every later view switch left focus on a control
  belonging to the now-hidden group. Views can now declare a `DEFAULT_FOCUS_ID` that `MainWindow`
  claims on switch (before `activate()`, so a view's own more specific focus still wins).
- "Log in again" only worked once per session: the reused `LoginView` kept its old
  fresh-instance-per-login guards, so every later visit no-opped on a dead screen. Re-login now
  starts a genuinely fresh device-code flow each visit, while still absorbing Kodi re-firing
  activation within a single visit.
- Kodi re-firing `onInit` on the already-active window snapped the user back to the initial view
  (and tore down the view that was still running); it now resumes the active view instead.
- Input arriving before `onInit` raised `KeyError: None` instead of being ignored.
- Live Streams bounced to Menu on an error or an empty followed list, hiding the message it had
  just set. It now stays put and offers a "Log in again" button (skin control 204), matching
  Discover.
- The confirmed-quit path closes the window explicitly again before exiting.

## [0.14.1] - 2026-08-13

### Fixed
- Search window crashed immediately on open: `onInit` called `.setFocus(True)` on an edit
  control, but Kodi's `xbmcgui.ControlEdit` has no `setFocus` method (only `Window.setFocusId`
  exists for this). The uncaught `AttributeError` made Kodi's window manager silently revert to
  Home - looked like Search flashing open then bouncing back. `setFocusId` alone (already called
  on the line above) was sufficient; the broken line is removed. Added `tests/windows/test_search_window.py`,
  since `search.py` previously had no test coverage at all.

### Known issue
- Even with the crash fixed, opening Search from Home can still hit a separate, pre-existing
  Kodi window-manager bug where a second custom window activation gets natively reverted with no
  Python error - the same root cause already tracked for Discover and re-login. Confirmed live
  this isn't specific to `xbmcgui.WindowXML` vs `WindowXMLDialog` (Search already uses
  `WindowXMLDialog`); root cause is still open.

## [0.14.0] - 2026-08-13

### Added
- Addon icon (`icon.png`), wired via `addon.xml`'s `<assets>` block - shows in Kodi's addon
  browser and Add-ons list instead of the generic script placeholder.

## [0.12.0] - 2026-08-12

### Added
- Home's "Log in again" button is now always visible, not just shown on error - lets you
  voluntarily re-authorize or switch Twitch accounts on demand (e.g. after using the same account
  on two devices, since Twitch's device-code refresh tokens are single-use and one device
  refreshing can invalidate the other's session).

### Changed
- `website_token` is no longer masked in the settings dialog (was rendered as dots).

### Fixed
- Shortened the `website_token` setting's help text - the full paragraph wasn't rendering fully on
  a TV display (confirmed not overscan-related), likely wrapping past the settings dialog's
  fixed help-text height at that resolution/font size.

### Known issues
- Re-login from Home can hit a pre-existing, already-tracked Kodi window-activation bug (see
  project history) where a second custom addon window silently reverts to the previous screen
  instead of showing - confirmed live on this transition too. Not new in this release, and not
  specific to this feature; affects any second custom-window activation in this addon's process.

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
