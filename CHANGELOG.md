# Changelog

All notable changes to this project are documented here. Format loosely follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions follow the addon's own
`version` field in `addon.xml`.

## [0.28.8] - 2026-09-02

### Fixed
- Chat overlay swallowing the player's OSD/Select action instead of letting it reach the
  player. The old fix (`Action()` builtin) forwarded to whatever window is currently
  active - which is the overlay itself (a non-modal dialog that stays topmost/focused),
  so the forward re-entered the overlay's own `onAction` and looped forever instead of
  reaching the player. Now uses `ActivateWindow(12901)` to push the OSD dialog directly
  onto the window stack, bypassing active-window routing entirely; closing OSD pops back
  to the still-open chat overlay. `ACTION_CONTEXT_MENU` forwarding dropped - no fixed
  window id exists for it, so the same technique doesn't apply.

## [0.28.7] - 2026-08-29

### Changed
- Grew the channel thumbnail further (110px -> 160px) and moved to 3 rows (card height
  266px) as a middle ground between thumbnail size and row count. Column count is not a
  fixed number - the skin's panel control wraps by row count (from height) and grows
  columns to fit however many channels are actually live, so it will show more or fewer
  columns depending on how many channels are live at any given time.

## [0.28.6] - 2026-08-29

### Changed
- Grew the channel thumbnail in the Live Streams grid cards (100px -> 110px) by
  compacting the header/game/platform rows around it, after 0.28.5 shrank cards to
  fit 4 rows. No layout change to row/column count.

## [0.28.5] - 2026-08-29

### Changed
- Live Streams grid now shows 4 rows instead of 3 (card height 195px, panel unchanged at
  800px tall) - 12 cards visible at once (3 columns x 4 rows), still scrollable for more.
  Columns are stuck at 3 regardless of declared item width (tested 415/400/300/250px, all
  render exactly 3 columns while row count correctly tracks height) - root cause not found;
  shipping with 3 columns x 4 rows for now.

## [0.28.4] - 2026-08-29

### Fixed
- On-screen version label's build date was still 2026-08-27 (stale from the previous
  release) - bumped to match this release's actual date.

## [0.28.3] - 2026-08-29

### Changed
- Live Streams grid now shows 3 rows instead of 2 (card height 275px -> 260px, panel
  unchanged at 800px tall).
- Added a Refresh button to Live Streams (skin button id 206) so the user can re-pull
  followed/live status without leaving the view and going back to the main menu.
- Games filter pills and the Refresh button now use the card surface art (name_box.png /
  card_surface_focus.png) instead of bare text, matching the channel grid's card look.

## [0.28.2] - 2026-08-27

### Fixed
- v0.28.1's clip fix still 401'd on the actual video request, found via a direct live probe
  (not through the addon UI) of both the GQL call and the resulting MP4 URL: (1) the guessed
  persisted-query sha256 hash for `VideoAccessToken_Clip` was rejected outright by
  gql.twitch.tv ("persistedQuery does not have a valid sha256 hash") - `gql.py` now sends the
  query as a raw `query` string instead of a persisted query; (2) the clip's `sourceURL` alone
  401s - its CDN path (`.../nauth/...`) requires the accompanying `playbackAccessToken`
  signature/value appended as `?sig=...&token=...`, the same pattern live/VOD playback already
  uses via usher.ttvnw.net. `get_clip_video_url` now does both. Confirmed live on kodi.local:
  clips play.

## [0.28.1] - 2026-08-27

### Fixed
- Clip playback was completely broken: every clip failed with "Couldn't start playback. Try
  again." and no log line (the failure was caught silently). Root cause, confirmed live on
  kodi.local: `resolve_clip_url` derived a clip's MP4 URL by substituting its Helix
  `thumbnail_url`'s `-preview-WxH.jpg` suffix with `.mp4` - Twitch has since moved clip
  thumbnails to a new CDN path (`.../twitch-video-assets/.../landscape/thumb/thumb-0000000000-
  480x272.jpg`) with no derivable video-file name, so the substitution never matched for any
  clip. Replaced with Twitch's undocumented `VideoAccessToken_Clip` GQL query
  (`lib/twitch/gql.py`'s new `get_clip_video_url`), the same approach other Twitch clients use -
  returns a directly playable MP4 URL per clip id, no thumbnail parsing involved.
- `_on_vod_selected`/`_on_clip_selected` (`lib/views/vod_clips_view.py`) now log a `LOGERROR`
  line with the failing id/exception on `StreamUnavailableError` instead of swallowing it
  silently - this is what made the clip bug invisible in kodi.log in the first place.

## [0.28.0] - 2026-08-27

### Removed
- The live-notify feature (background EventSub subscriptions to followed channels'
  `stream.online` events, with a Kodi notification when one goes live). Live-tested
  extensively across v0.27.1-0.27.6 trying to make the cold-start subscribe burst for a
  large followed-channel list (140 in testing) fit within Twitch's per-`client_id`
  EventSub rate limit: a throttled delay wasn't enough, a Ratelimit-Reset-aware reactive
  backoff wasn't enough, and a startup race fix plus a proactive Ratelimit-Remaining
  throttle still weren't enough - the final live test saw Twitch's server close the
  WebSocket session outright after repeated 429s, risking a resubscribe-everything retry
  loop. Not worth the complexity or the risk of breaking chat (which shares the same
  `client_id`'s rate-limit budget) for a non-essential feature. Removed
  `lib/live_notify_service.py`, `LiveNotifyClient` (`lib/twitch/eventsub.py`), the
  `live_notify_enabled`/`live_notify_verbose_logging` settings, and the `xbmc.service`
  addon.xml extension.

## [0.27.6] - 2026-08-27

### Fixed
- `LiveNotifyClient`'s subscribe loop only backed off reactively, after a 429 already
  happened. Live-tested on kodi.local with v0.27.5's race fix in place: a clean cold-start
  140-channel burst still 429'd on ~126 of 140 calls partway through the single continuous
  subscribe loop, because Twitch's actual per-`client_id` token bucket is smaller than 140
  requests and the burst outran it before any 429 could trigger backoff. `api.py`'s
  `create_eventsub_subscription` now returns a dict subclass carrying the response's
  Ratelimit-* headers (`_RateLimitedResult`); `LiveNotifyClient._throttle_delay_for_result`
  reads `Ratelimit-Remaining` on every successful call and, once it drops to
  `_RATE_LIMIT_LOW_WATERMARK` (5) or below, waits for `Ratelimit-Reset` before the next call -
  proactively, before the bucket actually empties.

## [0.27.5] - 2026-08-27

### Fixed
- Root-caused the 429 storm that survived v0.27.4's Ratelimit-Reset-aware throttle: it wasn't
  a reconnect, it was a startup race in `live_notify_service.py`. The service called
  `client.connect()` (starting the background handshake thread) before
  `client.set_broadcasters(channels)`. If the thread reached its handshake's subscribe
  snapshot before `set_broadcasters()` landed, `set_broadcasters()` saw no session yet and
  silently no-op'd (only recording the desired list for later) - the service then logged
  "subscribed to N channels" immediately, before any subscription request had actually been
  made. The real subscribe burst ran ~70s late via the handshake's catchup path, landing right
  on top of chat's own EventSub subscribe when a stream was opened in the meantime, 429-storming
  both. Fixed by calling `set_broadcasters()` before `connect()` - already the documented,
  tested-correct order in `eventsub.py`'s own test suite, just not the order the service used.
- Added a 30s delay before live-notify's first connect attempt after Kodi boot
  (`_INITIAL_CONNECT_DELAY_SECONDS`), reducing the odds of the throttled subscribe burst
  colliding with a stream opened right at startup.

## [0.27.4] - 2026-08-27

### Fixed
- v0.27.1's fixed 0.1s subscribe throttle wasn't enough live: with the chat overlay's own
  EventSub subscription competing for the same per-`client_id` Twitch rate-limit bucket at
  the same time, a second live test still saw a full 140-channel resubscribe get 429'd on
  every request even with throttling. `LiveNotifyClient` now reads Twitch's documented
  `Ratelimit-Reset` header (a Unix timestamp for when the token bucket refills - see
  https://dev.twitch.tv/docs/api/guide/#rate-limits) on a 429 and waits until that exact
  time instead of a fixed guess, capped at 60s to bound a malformed/clock-skewed header.
  The fixed 0.5s delay (bumped from 0.1s) remains the floor for the normal, non-429 case.

## [0.27.3] - 2026-08-27

### Fixed
- Found via live re-test on kodi.local: v0.27.2's fix patched the wrong file. This addon has
  two chat overlay renderers - the plain `ChatOverlay` (fixed in v0.27.2) and a separate
  `VariableChatOverlay` (on by default for EventSub chat, via `chat_overlay_variable_height`)
  that reuses `ChatOverlay`'s pump thread but has its own independent `_render()`/
  `_message_metrics()`/`_build_block()` for laying out variable-height message blocks. That
  code called `event["text"]` unconditionally with no handling for "error"-typed events
  (ChatClient surfacing a connection/subscription failure) or malformed events at all -
  confirmed live as the actual `KeyError('text')` crash reported after v0.27.2 shipped,
  reproduced by opening a stream shortly after an EventSub subscription 429. Added the same
  normalize-before-render guard `ChatOverlay` already had, to `VariableChatOverlay`'s code
  path.

## [0.27.2] - 2026-08-27

### Fixed
- Chat overlay's pump thread now shows a visible "[CHAT ERROR]" item in the chat list itself
  if it hits an unexpected exception, instead of just logging to kodi.log (which nobody
  normally sees) and silently freezing on the last message shown.
- `_build_message_item` now defends against a "message"-typed event missing `display_name`
  or `text` - renders as a "[CHAT ERROR]" item instead of raising `KeyError` and killing the
  whole pump thread. Added after a live, unconfirmed-root-cause `KeyError('text')` crash was
  found on kodi.local shortly after a burst of EventSub subscription rate-limit errors; the
  exact producer of the malformed event wasn't pinned down, but the pump thread must degrade
  gracefully regardless of the cause.

## [0.27.1] - 2026-08-27

### Fixed
- Live-notify's `LiveNotifyClient` was subscribing every followed channel's `stream.online`
  event in a tight, unthrottled loop (one Helix POST per channel, no delay). With a large
  follow list this blew through Twitch's per-`client_id` EventSub rate limit almost instantly
  - confirmed live: a 139-channel burst produced a wall of `429 Too Many Requests`, and since
  the chat overlay's own EventSub subscription call shares the same `client_id`, it landed
  inside that same rate-limited window and got 429'd too, breaking chat until the window
  cleared. A small delay (`_SUBSCRIBE_THROTTLE_SECONDS`) between each subscribe/unsubscribe
  call now keeps live-notify's own burst from starving other features sharing the same
  Twitch app rate-limit budget.

## [0.27.0] - 2026-08-27

### Added
- New "VODs & Clips" screen, reachable from the main menu: pick any followed Twitch channel and
  browse its past broadcasts (VODs) and clips, then play either back. Video-only playback (no
  chat overlay, no ad-skip relay) - Twitch only for now.

## [0.26.4] - 2026-08-27

### Fixed
- Chat overlay now displays error messages when EventSub/IRC connection fails
  (e.g. rate limits, subscription cap hit from the live-notify service) instead of
  silently showing an empty list
- IRC ChatClient no longer silently swallows connection exceptions — errors are
  surfaced to the overlay just like EventSub
- VERSION_DATE updated to match addon.xml and CHANGELOG.md

## [0.26.3] - 2026-08-27

### Changed
- Renamed the addon's display name from "Twitch Center" to "SIGMA Streaming Hub" - everywhere
  it's shown to the user (Kodi's addon browser, notification headings, the quit-confirmation
  dialog, the skin's "Activate ..." label, README). The internal addon id
  (`script.twitch.center`), its folder name, and all `script.twitch.center:`-prefixed log lines
  are unchanged - this is a display-name-only rename, no reinstall or data migration needed.

## [0.26.2] - 2026-08-27

### Added
- Live-notify now also catches followed channels that were already live before the background
  service connected (e.g. right at Kodi startup, or immediately after enabling the setting).
  `stream.online` EventSub events only fire on the transition to live, so a stream already in
  progress at connect time previously never got a notification for it. A one-off
  `api.get_live_status` check now runs immediately after every successful initial connect to
  cover that gap.

## [0.26.1] - 2026-08-27

### Added
- New "Log live-notify activity" setting (off by default) gates INFO-level logging for the
  live-notify service: the subscribed followed-channel list (login names) at connect and each
  follow-refresh, and each notification shown. Connect/disconnect status and subscription-error
  events, previously only visible with Kodi debug logging enabled, are now logged at INFO under
  the same toggle. Added after live-testing on kodi.local exposed that a missed notification
  couldn't be diagnosed from the log as it stood - the service now leaves an audit trail when
  asked to.

## [0.26.0] - 2026-08-26

### Added
- New opt-in setting "Notify when followed streamers go live" enables a background Kodi service
  for live notifications. The service uses one EventSub WebSocket subscribed to your followed
  channels' `stream.online` events for near-instant (not polling) notifications when they go
  live - delivery follows the service's poll tick, up to 60 seconds after the event arrives.
  Runs separately from the main addon window and is off by default. Twitch only for now.

## [0.25.5] - 2026-08-25

### Changed
- Variable-height chat overlay's per-line/per-block padding trimmed (`_LINE_PITCH` 60->44,
  `_BLOCK_MARGIN` 34->16) - the original margin (added in v0.17.x to fix real cross-build text
  overlap) left a visible trailing blank-line gap below short/single-line messages, confirmed via
  screenshot. Still padded above the tightest value previously measured, not shrunk to it - flag
  it if this reintroduces any text overlap on real hardware.

## [0.25.4] - 2026-08-25

### Fixed
- Quitting the addon (or otherwise stopping playback) while the ad-skip relay was active could
  take up to 5 real seconds - `AdSkipRelay.stop()` was joining its background fetch thread with a
  5s timeout, blocking whichever thread called it (a Kodi player-callback thread). That thread is
  a daemon and dies with the interpreter regardless, so there was no correctness reason to wait
  for it - stop() no longer joins it.

## [0.25.3] - 2026-08-25

### Fixed
- Skip Twitch Ads relay never actually started playback on real hardware (kodi.local) - the
  generic stall-recovery watchdog fired during the relay's normal multi-fetch startup (master +
  variant + first-segment, three sequential round-trips, slower over a real connection than in
  local dev testing) and "recovered" by re-opening the same not-yet-fed relay URL, looping
  forever with video never starting (chat kept working since it's unaffected). The watchdog is
  now disabled for the relay path - it already retries network failures internally and doesn't
  need Kodi-side stall-recovery riding along.

## [0.25.2] - 2026-08-25

### Fixed
- Version-only bump - `v0.25.0` and `v0.25.1` GitHub releases from an earlier, since-reverted
  experiment (ISA-bypass/stream-quality-prompt settings) were still live and outranked the real
  `v0.25.0` (ad-skip relay, see below), risking Kodi's repo-based updater serving that stale
  build as "latest". No code change from `v0.25.0`.

## [0.25.0] - 2026-08-25

### Added
- **Experimental** "Skip Twitch Ads" setting (default off) - runs a small local relay
  (`lib/hls_ad_relay.py`) that does its own HLS segment-fetch loop against the live stream,
  detects Twitch's stitched-ad segments (same two signals streamlink uses: an
  `EXT-X-DATERANGE` tagged `CLASS="twitch-stitched-ad"`, or an `EXTINF` title containing
  "Amazon"), skips them outright, and re-serves the rest as one continuous MPEG-TS stream over
  `localhost` - Kodi just plays that plain HTTP URL, no inputstream.adaptive/HLS parsing on its
  end for this path. Live-tested on the local dev Kodi instance: over an hour combined across two
  different large channels with zero playback errors and no early termination, confirming the
  relay approach itself is stable (unlike the since-reverted ISA-bypass experiment) - no actual
  ad break was hit during that window, so the skip logic's real-world firing is still unconfirmed
  live, though it's covered by unit/integration tests (segment-level ad detection, and an
  end-to-end test that a real ad segment served over a real local socket gets dropped from the
  output).

## [0.24.10] - 2026-08-25

### Fixed
- Chat overlay now also forwards Select/Enter to the player - on some CEC remote setups that's
  the button that opens the player OSD, not a dedicated OSD/context-menu key, and the overlay
  was still swallowing it after the v0.24.9 fix.

## [0.24.9] - 2026-08-25

### Fixed
- Chat overlay (both fixed and variable-height renderers) no longer swallows the OSD /
  context-menu keys during playback - they now forward to the player, so player options can be
  opened without closing chat first.

## [0.24.8] - 2026-08-25

### Changed
- Wired `discover_view.py` and `live_streams_view.py` to actually use the shared ListItem
  builders in `lib/views/utils.py`, instead of each carrying its own duplicate copies.

## [0.24.7] - 2026-08-25

### Changed
- Added `lib/views/utils.py` with shared `xbmcgui.ListItem` builder helpers for Twitch/Kick
  stream entries, cutting duplicated property-setting code out of the view layer.

## [0.24.6] - 2026-08-25

### Changed
- README: Installation now points at the `drachenhort-repo`/`repository.drachenhort` Kodi
  repository, replacing the retired shared `jellyfin-kodi-plex` distribution. Folded the removed
  standalone Search screen into Discover in Features/Status. Kick section updated to reflect that
  browsing and watching work with no login required - only chat is still unimplemented.

## [0.24.4] - 2026-08-25

### Changed
- Kick login is no longer required for watching. `kick_client_id` now ships baked-in
  (hidden, like Twitch's) instead of asking every user to register their own app.
  Watching Kick streams and Kick Favorites now use the public, unauthenticated
  unofficial channel endpoint - no token needed at all. Discover's Kick category
  browse/search now uses a Kick App Access Token (`client_credentials` grant,
  `lib.kick.auth.get_app_access_token`) instead of the interactive PKCE user login -
  only needs `kick_client_secret` set in Settings, no "Log in to Kick" click.
  `resolve_stream_url`'s Kick branch no longer gates on a saved token.

## [0.24.3] - 2026-08-25

### Added
- Clock (`$INFO[System.Time]`) top right corner of Discover and Live Streams screens.

## [0.24.2] - 2026-08-23

### Changed
- New Menu screen background and logo (`resources/skins/Default/media/home_bg.jpg`,
  `logo_overlay.png`) - a streaming-setup photo and a "Sigma Streaming Hub" badge logo,
  replacing the previous plain background and Twitch Center wordmark.

## [0.24.1] - 2026-08-23

### Added
- Discover's search mode toggle now cycles through a third "Kick" mode - search Kick
  categories by name (e.g. "eve" finds "EVE Online") and jump straight to its live
  streams, same convention as the existing Twitch game-search mode. Uses
  `GET /public/v2/categories`'s `name` filter param (confirmed live 2026-08-23:
  case-insensitive substring match). Previously the Kick categories row only showed the
  first ~20 categories from Kick's default (non-popularity-sorted) ordering, so anything
  outside that page - like EVE Online - was unreachable without this.

## [0.24.0] - 2026-08-23

### Removed
- The standalone Search screen (menu button, `SearchView`, skin group 400) - live testing
  found its search box's on-screen keyboard reopened in a loop on the very first press,
  even before typing anything, unrelated to any recent change. Rather than chase an
  unexplained pre-existing bug, dropped the screen entirely: Discover's search-by-channel
  already covers the same need and works fine. Also removed the now-dead code this only
  existed to serve: `lib.twitch.gql.search()`, `providers.normalize_twitch_search_result`.

## [0.23.1] - 2026-08-23

### Changed
- Search results now render as the same card tiles as Live Streams/Discover (thumbnail,
  name box, game name, live-viewer chip) instead of a plain text list.
  `lib/views/search_view.py` now sets `game_name`/`viewer_count`/`is_live` as ListItem
  properties and thumbnail art, matching the shared card layout's bindings.

## [0.23.0] - 2026-08-23

### Changed
- Discover screen restyled to match Live Streams' card look: results now render as
  thumbnail tiles (name box, game name, live-viewer chip, platform badge) in a panel
  instead of a plain thumb+text list, and the games/Kick-categories filter rows became
  small card-style pills with `CardHeadline` text instead of plain list text.
- Both Discover and Live Streams' card tiles now show a colored platform badge/focus
  highlight - blue "TWITCH" / green "KICK" label on the tile, and the focus background
  itself tints per platform (blue for Twitch, green for Kick) instead of always blue.
- Discover's games/Kick-categories rows now have static "TWITCH:" / "KICK:" row labels,
  and each row's pill background is subtly tinted per platform even when not focused, so
  the two rows (and the currently-selected item) are distinguishable without guessing.

### Fixed (as part of the above)
- `lib/views/discover_view.py`'s three result-item builders now set `game_name` and
  `viewer_count` as ListItem properties (previously only baked into `Label2` text), which
  the new card layout's `$INFO[ListItem.Property(...)]` bindings need.

## [0.22.6] - 2026-08-23

### Fixed
- Kick playback never worked - `resolve_stream_url` assumed the official Public API's
  `channel["stream"]["url"]` held the HLS playback URL (flagged UNVERIFIED since the
  original implementation). Confirmed live 2026-08-23 against a real live channel: that
  field is always an empty string, even while live - the official API doesn't expose a
  playback URL at all. Switched to the unofficial `kick.com/api/v2/channels/{slug}`
  endpoint (public, no auth needed), whose `playback_url` field actually works.

## [0.22.5] - 2026-08-23

### Fixed
- Successful Kick login never switched back to the main menu - `lib/main.py`'s polling
  loop checked the Twitch login view's `login_succeeded` flag but never the Kick login
  view's, so the Kick login screen just sat on "Logged in!" until manually backed out of.

### Changed
- Menu's Twitch/Kick buttons now show actual login status instead of static text:
  "(Twitch) Logged in" (always, by the time Menu is reachable at all - still clickable to
  switch accounts) and "(Kick) Logged in" / "Log in to Kick" depending on whether a Kick
  token is saved.

## [0.22.4] - 2026-08-23

### Changed
- Kick login screen now shows/logs a short `http://127.0.0.1:<port>/start` link instead
  of Kick's much longer authorize URL - the addon's own loopback OAuth server now also
  serves that route, 302-redirecting straight to Kick. Same-machine use only (not a fix
  for logging in from a separate phone/device - that still needs the real long URL
  reachable over the LAN, which `127.0.0.1` never is from another device).

## [0.22.3] - 2026-08-23

### Fixed
- `kick_client_secret` setting was left `<visible>false</visible>` with no help text
  (unlike its `kick_client_id` sibling), so there was no way to enter/fix it via Kodi's
  Settings UI. Now visible with help text pointing to dev.kick.com, matching client_id.
- Kick PKCE login's generic "Connection error" message covered four different failure
  causes (state mismatch, token exchange failure, user-info fetch failure, or any other
  exception) with no way to tell which. `run_pkce_login` now passes the real exception/
  reason through to `on_status`, logged to kodi.log.
- Discover's Kick categories row switched from the client-side derive-from-livestreams
  workaround (added in 0.22.2 for Finding 3) to the real `GET /public/v2/categories`
  endpoint - confirmed live 2026-08-23 that, unlike the deprecated v1 endpoint, it needs
  no search query and genuinely supports browsing all categories.

### Changed
- Kick login screen's authorize URL is now also written to kodi.log (INFO level) and its
  on-screen label wraps across multiple lines instead of being clipped - both make it
  usable to actually copy/read instead of squinting at a single truncated line.

## [0.22.2] - 2026-08-23

### Fixed
- Kick's real API returns `thumbnail` as a flat URL string, not `{"url": ...}` as
  guessed during implementation - fixed `_normalize_kick_channel` and
  `_normalize_kick_live_stream_entry` in `lib/providers.py`. Previously crashed Live
  Streams and Discover's Kick category browsing as soon as any Kick data had a
  thumbnail (i.e. immediately, on any live channel).
- `_normalize_kick_channel` read `category` nested under `stream`, but the real
  `/channels` response has it as a top-level key - was silently making `game_name`
  always empty for every Kick favorite on Live Streams.
- Discover's Kick categories row called `GET /public/v1/categories`, which is
  deprecated and requires a mandatory search query - it always failed. Replaced with
  deriving categories client-side from a page of live streams (`GET /livestreams`,
  which supports unfiltered browsing), deduped and ordered by viewer count.

### Removed
- Kick results from Search. The guessed unofficial endpoint
  (`kick.com/api/v2/search/channels`) 404s, and live probing of the real
  `kick.com/api/search` route (which does exist) couldn't find a working parameter
  name after trying the obvious candidates - the route appears gated behind
  browser-session/bot-detection rather than a simple param mismatch, so this was
  dropped rather than kept as more unconfirmed-endpoint risk. Kick channels remain
  discoverable via Live Streams favorites and Discover's categories row.

## [0.22.1] - 2026-08-22

### Added
- Kick favorites are now manageable from within the addon: a context menu (remote's
  Context/Info button, or long-press) on any Kick channel in Discover, Search, or Live
  Streams offers "Add to Kick Favorites" / "Remove from Kick Favorites". Closes the gap
  from v0.22.0 where the favorites list existed but had no UI to populate it - Kick has
  no followed-channels API of its own to read from, so favorites stay addon-local.

## [0.22.0] - 2026-08-22

### Added
- Kick.com stream browsing and playback, wired into all three existing views alongside
  Twitch: Live Streams shows favorited Kick channels interleaved with followed Twitch
  channels by viewer count, Discover browses Kick's top categories in their own row, and
  Search merges Kick results into Twitch search results. Adds Kick PKCE login (a dedicated
  login view/flow) reachable from the Menu. Kick chat is explicitly out of scope for this
  release - Kick streams play without a chat overlay.

## [0.21.1] - 2026-08-22

### Fixed
- `chat_overlay_variable_height` setting now applies to the IRC chat engine too, not just
  EventSub. IRC is the default engine, so the fixed-height `ChatOverlay` item boxes (sized for
  the worst-case 5 wrapped lines) were leaving visible trailing blank space under most short
  messages for anyone on defaults. Enabling the setting now switches IRC to `VariableChatOverlay`
  as well, which sizes each message block to its actual line count.

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
