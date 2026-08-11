# Stream Playback: Design

Date: 2026-08-11

## What this is

Wires up the one thing every prior screen has deferred: clicking a **live** channel in Home's
followed-channels list or Discover's results list (browse-by-game or search) actually starts
playback in Kodi. Clicking an offline entry does nothing.

## Verification (real Twitch, not memory/community docs)

Captured directly from Twitch's own web client (same browser-hook technique used for the
followed-games design), against two real live channels (one plain, one mature-tagged, to confirm
the mature-content interstitial doesn't block API-level token issuance):

- **GraphQL:** `POST https://gql.twitch.tv/gql`, operation `PlaybackAccessToken`, persisted query
  hash `ed230aa1e33e07eebb8928504583da78a5173989fadfb1ac94be06a04f3cdbe9`, variables
  `{"isLive": true, "login": "<channel_login>", "isVod": false, "vodID": "", "playerType": "site",
  "platform": "web"}`. Auth: same `Client-Id: kimne78kx3ncx6brgo4mv6wki5h1ko` (Twitch's public web
  client ID) + `Authorization: OAuth <access_token>` pattern already established and verified for
  `gql.get_followed_live_games`.
- **Response:** `data.streamPlaybackAccessToken.{value, signature}`. `value` is an opaque JSON
  string (Twitch's own internal token payload) — treated as an opaque blob, never parsed.
- **Playable URL**, confirmed by directly fetching it and getting a real HTTP 200 HLS master
  playlist both times:
  ```
  https://usher.ttvnw.net/api/channel/hls/<channel_login>.m3u8
    ?token=<url-encoded value>&sig=<signature>&allow_source=true&fast_bread=true&player_backend=mediaplayer
  ```
  No additional auth needed for this request — it's a public, self-contained tokenized URL.
- The mature-content "gate" the user asked about is a **website-only UI overlay** (a "this content
  may not be for you" interstitial Twitch's web client shows before rendering its player). It does
  not block token issuance — both real-capture calls succeeded before any click-through. Since this
  addon never touches Twitch's web UI, there is nothing to bypass or auto-accept; the design already
  sidesteps it by construction.
- Confirmed the manifest contains real quality variants (`#EXT-X-STREAM-INF`/`#EXT-X-MEDIA` entries
  for 1080p60 down to 160p30 on the mature-tagged channel), so adaptive-bitrate playback has
  something to adapt across.

## Why inputstream.adaptive

Kodi's native FFmpeg-based demuxer can sometimes play a single HLS URL directly, but doesn't do
proper adaptive-bitrate variant switching for live multi-quality HLS the way `inputstream.adaptive`
does. `script.module.inputstreamhelper` (already present on the target system, and the standard,
widely-used pattern across Kodi video addons) handles checking whether `inputstream.adaptive` is
installed and prompts to install it if not — this addon should use that rather than reinventing
install-prompt logic.

## Components

### `lib/twitch/gql.py` (extended)

- `get_playback_access_token(access_token, channel_login) -> dict | None` — same best-effort/
  never-raises convention as `get_followed_live_games`: returns `None` on any failure (network
  error, non-200, unexpected response shape), never raises. Returns `{"value": ..., "signature":
  ...}` on success.

### `lib/twitch/stream.py` (replaces the stub)

- `StreamUnavailableError(Exception)` — **new**. Raised when a stream genuinely can't be resolved
  to a playable URL (the `gql` call came back `None` — channel not live, access denied, or Twitch
  rejected the request). Unlike `gql.py`'s best-effort convention, this module's whole purpose is
  "give me a URL or tell me why not" — a failure here is not decorative, it's the thing the user
  clicked expecting to work, so it must be surfaced rather than silently swallowed.
- `resolve_stream_url(access_token, channel_login) -> str` — calls
  `gql.get_playback_access_token`; raises `StreamUnavailableError` if it returns `None`; otherwise
  builds and returns the usher master-playlist URL exactly as verified above. `gql.py` itself
  already catches network errors internally and returns `None` for them (per its established
  never-raises contract), so from `stream.py`'s point of view a network failure and a genuinely
  unavailable stream are indistinguishable — both surface as `StreamUnavailableError`. This is an
  intentional simplification: the caller (a window's click handler) only needs one exception type
  to catch, and "couldn't reach Twitch" vs. "channel not available" both resolve to the same
  user-facing "couldn't play this" message anyway.

### `lib/windows/player.py` (replaces the stub)

- `play_stream(url) -> bool` — returns `True` if playback was started, `False` if the user declined
  the `inputstream.adaptive` install prompt (or it's otherwise unavailable). Uses
  `inputstreamhelper.Helper("hls").check_inputstream()` to ensure the dependency is present (this
  call itself handles the install-prompt UI), then builds a `xbmcgui.ListItem` with
  `inputstream`/`inputstream.adaptive.manifest_type`/mimetype properties set for HLS, and calls
  `xbmc.Player().play(url, list_item)`.

### `addon.xml` (extended)

New `<import addon="script.module.inputstreamhelper" version="0.4.6"/>` in `<requires>`.

### `lib/windows/home.py` / `lib/windows/discover.py` (extended)

- List items gain a `broadcaster_login` property (the channel's login/slug — required for the
  usher URL, distinct from its display name) and an `is_live` property (`"true"`/`"false"`) on top
  of what they already carry (`broadcaster_id`, art, labels).
  - Home's `_build_list_item`: `broadcaster_login` from `channel["broadcaster_login"]` (present in
    Helix's `/channels/followed` response, already used elsewhere in this codebase's `FOLLOWED`
    test fixtures); `is_live` is `"true"` when a `stream` was passed, `"false"` otherwise.
  - Discover's `_build_stream_item` (browse-by-game results, always live): `broadcaster_login` from
    `stream["user_login"]`; `is_live` always `"true"`.
  - Discover's `_build_channel_item` (search results): `broadcaster_login` from
    `channel["broadcaster_login"]`; `is_live` from the existing `channel.get("is_live")` this
    function already reads for its label text.
- `onAction` gains a branch for the channel/results list: `ACTION_SELECT_ITEM` while focused on
  `CHANNEL_LIST_ID` (Home) / `RESULTS_LIST_ID` (Discover) reads the selected item; if
  `is_live != "true"`, does nothing (silent, per your scope decision); if live, resolves via
  `stream.resolve_stream_url(token["access_token"], broadcaster_login)` and calls
  `player.play_stream(url)`.
- Failure of `resolve_stream_url` (raises `StreamUnavailableError`) is shown via the existing
  error-message pattern each window already has (`_show_results_error` on Discover; Home doesn't
  currently have a non-fatal results-error variant, so Home gets one added, mirroring Discover's —
  same reasoning as Discover's own fix from the final review of the previous plan: a failed
  playback attempt must not wipe the whole followed-channels list the user is browsing).
- `player.play_stream` returning `False` (user declined the inputstream install prompt) is treated
  the same as a resolution failure for messaging purposes — a brief "couldn't start playback"
  message, not a crash.

## Data flow

```
User selects a LIVE item in Home's channel list or Discover's results list
  -> read broadcaster_login + is_live from the ListItem's properties
  -> is_live != "true": no-op
  -> is_live == "true":
       auth.load_token(addon) -> token
       stream.resolve_stream_url(token["access_token"], broadcaster_login)
         -> gql.get_playback_access_token(...) -> usher URL, or raises StreamUnavailableError
       player.play_stream(url)
         -> inputstreamhelper.Helper("hls").check_inputstream()
              False -> return False (declined/unavailable)
              True -> xbmc.Player().play(url, list_item) -> return True
```

## Error handling

- Offline item clicked: silent no-op (already-established scope decision).
- `StreamUnavailableError` (channel not live / access denied / underlying network failure): brief
  error message via each window's non-fatal results-error path, list contents untouched.
- Missing/expired token at click-time: reuses each window's existing token-handling
  (`auth.load_token`, refresh-then-retry via `_handle_expired_token`, same pattern as game-select
  and search already use) — the retry replays the same playback attempt with the refreshed token,
  matching the "don't silently discard the user's action" fix from the Discover screen's final
  review.
- `player.play_stream` returns `False`: same brief error message as a resolution failure.

## Testing

- `gql.get_playback_access_token`: mocked-`requests` tests mirroring `get_followed_live_games`'s
  existing pattern — success, network error, non-200, malformed response, all returning `None`.
- `stream.resolve_stream_url`: tests with a fake/injected `gql.get_playback_access_token` (success
  returns the exact expected usher URL; `None` raises `StreamUnavailableError`).
- `player.play_stream`: tested against a new `tests/kodi_stubs/inputstreamhelper.py` stub (`Helper`
  class, `check_inputstream()` configurable to return `True`/`False`) plus extended `xbmc.py`
  (`Player` class recording `.play()` calls) and `xbmcgui.py` (`ListItem` gains `path`/mimetype/
  content-lookup support) stubs — covers both the install-accepted and install-declined paths, and
  asserts the correct `inputstream`/`manifest_type` properties were set on the `ListItem` passed to
  `Player.play()`.
- `home.py`/`discover.py`: click-to-play tested via existing `tests/kodi_stubs/` patterns — live
  item plays (mocked `stream.resolve_stream_url` + `player.play_stream`), offline item no-ops,
  resolution failure shows the results-error message without wiping the list, token-expiry-then-
  retry replays the same playback attempt (mirroring the existing game-select/search retry tests).
- No test hits Twitch's real API or Kodi's real player.

## Out of scope for this task

- Playback controls beyond what Kodi's native OSD already provides (no custom UI).
- Chat-during-playback (the original scaffold's `chat_overlay.py`/`chat_window.py` stay stubs).
- VOD/clip playback (`isVod`/`vodID` variables exist in the verified request shape but this task
  only wires up live playback, matching every other screen's live-only focus so far).
- Stream-quality manual selection UI (inputstream.adaptive handles adaptive switching
  automatically; no manual override control).
