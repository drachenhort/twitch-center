# VODs & Clips for Followed Channels

Date: 2026-08-27
Status: Approved for planning

## Problem

Twitch Center only ever surfaces *live* content (Live Streams, Discover). A followed
channel's past broadcasts (VODs) and short highlight clips (Clips) aren't reachable at
all, even though Twitch's Helix API exposes both.

## Goal

A new "VODs & Clips" screen, reachable from the main menu, scoped to the user's followed
Twitch channels only: pick a followed channel (live or not), see that channel's VODs and
Clips as two lists, newest first, and play either one, video-only.

## Scope

- Twitch only. Kick is explicitly deferred — see "Kick — backburner" below.
- VODs means Twitch's `archive` video type (past broadcasts) — not highlights or uploads.
- No VOD replay chat, no Clip chat (Clips never had chat). Video-only playback for both.
- No pagination beyond the first page (20 items) of each list in this iteration.
- The channel picker lists **all** followed channels regardless of current live status —
  VODs/Clips exist independent of whether the channel is live right now.

## Architecture

### Navigation

Two new screens, following this codebase's existing one-`<group>`-per-screen pattern
(`lib/windows/main_window.py`'s `GROUP_IDS` + a view class per screen):

- `vod_clips_channels` (new `MainWindow.GROUP_IDS` entry, skin group `700`): lists all
  followed channels. Selecting one switches to `vod_clips`, passing the selected
  channel's `broadcaster_id`/`broadcaster_login`/`broadcaster_name`.
- `vod_clips` (skin group `800`): shows the selected channel's VODs (list) and Clips
  (list) stacked on one screen. Selecting an item plays it.

New "VODs & Clips" button in the main menu (`lib/views/menu_view.py`), inserted right
after "Live Streams". The existing button ID sequence is `501, 502, [503 unused], 504,
505, 506` — `503` was already skipped, so the new button takes that ID with **no
renumbering of existing button IDs**, just a `posy` shift down for Discover/Settings/
Login-again/Kick-login and their `onup`/`ondown` nav chain updated to route through it.

### Back navigation generalization

Every existing screen is exactly one level deep from the menu, so
`MainWindow.onAction`'s `ACTION_PREVIOUS_MENU`/`ACTION_NAV_BACK` handler hardcodes
"anywhere except menu → go to menu". This feature adds a second level
(`vod_clips_channels` → `vod_clips`), so that handler needs one small generalization:
each view class gets an optional `BACK_TARGET` class attribute (defaulting to `"menu"`
when absent, so every existing view's behavior is unchanged); `vod_clips`'s
`BACK_TARGET` is `"vod_clips_channels"`. `onAction` reads
`getattr(view, "BACK_TARGET", "menu")` instead of the current hardcoded `"menu"`.

## Data / API layer

### `lib/twitch/api.py` — two new functions, following this file's existing
`_get`/pagination style (see `get_followed_channels`, `get_live_streams_by_game`):

```python
def get_videos(access_token, client_id, user_id, first=20):
    """Return the given broadcaster's VODs (Helix /videos, type=archive), newest first."""
```
Calls `GET /videos?user_id=&type=archive&sort=time&first=20`. `sort=time` is passed
explicitly even though it's Helix's default — so this doesn't silently change if Twitch
ever changes their default. Returns Helix's raw video dicts (`id`, `title`,
`created_at`, `duration`, `thumbnail_url`, `view_count`, ...).

```python
def get_clips(access_token, client_id, broadcaster_id, first=20):
    """Return the given broadcaster's Clips (Helix /clips), sorted newest first."""
```
Calls `GET /clips?broadcaster_id=&first=20`. Twitch's Clips endpoint does **not**
guarantee chronological order (it's view-count-biased) — the returned list is
re-sorted client-side by `created_at` descending before returning. Returns Helix's raw
clip dicts (`id`, `title`, `created_at`, `duration`, `thumbnail_url`, `view_count`, ...).

### VOD playback — `lib/twitch/gql.py` and `lib/twitch/stream.py`

`gql.py` gets `get_vod_playback_access_token(vod_id, website_token=None)`, reusing the
**same persisted-query hash** as `get_playback_access_token` (the existing live-stream
token function) with different variables: `isLive: False, isVod: True, vodID: vod_id,
login: ""`. Reads `data.videoPlaybackAccessToken` instead of
`data.streamPlaybackAccessToken`.

**Known limitation, matching this file's existing candor about unofficial-API
guesswork** (see `get_followed_live_games`'s docstring for precedent): the query
variables (`isVod`/`vodID`) are well-documented in Twitch's public web client and high
confidence, but this persisted query's *fixed response selection set* was captured for
the live-stream case — whether it actually includes `videoPlaybackAccessToken` for a VOD
request is unconfirmed until live-tested. If it doesn't, this degrades to
`StreamUnavailableError` the same as any other resolution failure — no crash, just VOD
playback not working until this is revisited.

`stream.py` gets `resolve_vod_url(vod_id, website_token=None)`, structurally identical
to `resolve_stream_url` but hitting `usher.ttvnw.net/vod/<vod_id>.m3u8` instead of
`/api/channel/hls/<login>.m3u8`.

### Clip playback — `lib/twitch/stream.py`, no GQL needed

Helix's Clips response already includes `thumbnail_url` (e.g.
`https://clips-media-assets2.twitch.tv/AB12CD34-preview-480x272.jpg`). The direct,
playable MP4 is that same URL with the `-preview-<W>x<H>.jpg` suffix replaced by
`.mp4` — a well-known, deterministic technique used by most third-party Twitch clients,
no authentication or additional request required.

```python
def resolve_clip_url(thumbnail_url):
    """Derive a clip's direct MP4 URL from its Helix thumbnail_url. Raises
    StreamUnavailableError if thumbnail_url doesn't match the expected
    "...-preview-<W>x<H>.jpg" pattern."""
```

### `lib/providers.py` — dispatch wrappers

Two new functions alongside the existing `resolve_stream_url`, raising the same shared
`providers.StreamUnavailableError` (never the underlying per-module exception), matching
that function's existing wrap-every-exception discipline:

```python
def resolve_vod_url(addon, vod_id):
    ...  # wraps twitch_stream.resolve_vod_url

def resolve_clip_url(addon, thumbnail_url):
    ...  # wraps twitch_stream.resolve_clip_url
```

## UI layer

### Skin controls (`resources/skins/Default/1080i/script-twitch-center-main.xml`)

New group `700` (`vod_clips_channels`), mirroring Live Streams' channel-grid layout:
- `701` channel list (tile grid, same style as Live Streams' `201`)
- `702` empty label ("You're not following anyone yet.")
- `703` error label
- `704` relogin button (token-expiry flow)

New group `800` (`vod_clips`):
- `801` VODs list (tile grid)
- `802` Clips list (tile grid), `onup`-wired from its top row to `801`'s bottom row and
  vice versa
- `803` title label (selected channel's display name)
- `804` error label
- `805` relogin button

Main menu (`lib/views/menu_view.py` + skin group `500`): new button `503` ("VODs &
Clips"), `onright`/`onleft` self-looping same as its siblings, `onup` = `501` (Live
Streams), `ondown` = `502` (Discover, unchanged ID). `501`'s `ondown` changes from `502`
to `503`. `502`, `504`, `505`, `506` each shift `posy` down by 100 and `502`'s `onup`
changes from `501` to `503` (all other `onup`/`ondown` references between `502`/`504`/
`505`/`506` are unchanged, since their IDs don't change).

### View classes

`lib/views/vod_clips_channels_view.py` (`VodClipsChannelsView`): loads
`api.get_followed_channels`, populates `701` (no live-status merge — every followed
channel is listed). Token-expiry handling identical to `LiveStreamsView`'s
`_handle_expired_token`. Selecting a channel calls
`self.window._switch_view("vod_clips", context={...})` (channel dict) — `MainWindow`
needs a small extension to pass an optional context payload through `_switch_view` to
the next view's `activate()`, since this codebase's existing views never needed
cross-view data before (every other view loads its own data fresh via Helix calls that
don't depend on "which item was selected on the previous screen").

`lib/views/vod_clips_view.py` (`VodClipsView`): on `activate(context)`, calls
`api.get_videos` and `api.get_clips` for the selected channel's `broadcaster_id`,
populates `801`/`802`. Selecting a VOD item resolves via
`providers.resolve_vod_url(addon, vod["id"])` then
`player.play_stream(url, vod["title"], platform="twitch_vod")`. Selecting a Clip item
resolves via `providers.resolve_clip_url(addon, clip["thumbnail_url"])` then
`player.play_stream(url, clip["title"], platform="twitch_clip")`. `BACK_TARGET =
"vod_clips_channels"`.

### Playback dispatch (`lib/windows/player.py::play_stream`)

`platform` already gates both special-cased branches to `platform == "twitch"` exactly
(the ad-skip relay and the chat overlay), so passing `platform="twitch_vod"` or
`"twitch_clip"` already skips both with no changes to those branches. The one real gap:
the current `else` branch (used whenever the ad-skip relay isn't active) unconditionally
builds an `inputstream.adaptive`/HLS `ListItem` — correct for `"twitch_vod"` (real
multi-bitrate HLS, same as live), wrong for `"twitch_clip"` (a plain direct `.mp4`
file). One new branch:

```python
elif platform == "twitch_clip":
    list_item = xbmcgui.ListItem(path=play_url)
    list_item.setMimeType("video/mp4")
    list_item.setContentLookup(False)
```

placed before the existing `else` (which stays the fallback for `"twitch"` live,
`"twitch_vod"`, and `"kick"`).

## Error handling

- Token expiry (401) on `get_followed_channels`/`get_videos`/`get_clips`: same
  relogin-button flow as `LiveStreamsView._handle_expired_token`.
- No followed channels: empty-state label on `vod_clips_channels`, same style as Live
  Streams'.
- A channel with zero VODs and/or zero Clips: that list renders empty, no dedicated
  empty-state graphic (YAGNI — Live Streams doesn't special-case its empty game-filter
  row either).
- VOD/Clip resolution failure (`StreamUnavailableError` from either
  `providers.resolve_vod_url` or `providers.resolve_clip_url`): caught in
  `VodClipsView`'s selection handler exactly the way `LiveStreamsView._play_channel`
  catches it today, shown via the same error-label mechanism.

## Testing

- `lib/twitch/api.py`'s `get_videos`/`get_clips`: pure-Python unit tests (mocked
  `requests`), matching `tests/twitch/test_api.py`'s existing style — including a test
  proving `get_clips`'s client-side `created_at` re-sort actually reorders an
  out-of-order fixture.
- `lib/twitch/gql.py`'s `get_vod_playback_access_token` and `lib/twitch/stream.py`'s
  `resolve_vod_url`/`resolve_clip_url`: matching `tests/twitch/test_gql.py` and
  `tests/twitch/test_stream.py`'s existing mocked-`requests` style.
- `lib/providers.py`'s `resolve_vod_url`/`resolve_clip_url`: matching
  `tests/test_providers.py`'s existing exception-wrapping-discipline tests for
  `resolve_stream_url`.
- `VodClipsChannelsView`/`VodClipsView`: matching `tests/views/test_live_streams_view.py`'s
  style (Kodi stubs, no real `xbmc*`).
- `tests/test_addon_manifest.py`: extended to assert the new control IDs (`701`-`704`,
  `801`-`805`, `503`) exist in the skin, and that the main menu's `onup`/`ondown` nav
  chain still forms a closed loop after the renumbering.
- `lib/windows/player.py`'s new `"twitch_clip"` branch: a test asserting the built
  `ListItem` has no `inputstream` property set and `video/mp4` mime type, alongside the
  existing HLS-branch tests.

## Kick — backburner

Not built now. Recorded in `TODO.md` (this repo's existing backlog file) and in a
project memory. For future reference, a Kick VOD/Clips version would need:

- `lib/kick/api.py` equivalents of `get_videos`/`get_clips` — Kick's public API surface
  for this is unconfirmed/unexplored (existing `lib/kick/api.py` only covers live
  streams, categories, and channel lookup).
- Kick's own playback resolution for VODs/Clips — `lib/kick/stream.py`'s existing
  `resolve_stream_url` is live-only (unauthenticated `kick.com/api/v2/channels/{slug}`);
  VOD/Clip playback on Kick is a different, unresearched mechanism, not a small
  extension of that function.
- `lib/providers.py`'s dispatch wrappers would need a `platform` branch each, following
  the same pattern as `resolve_stream_url`'s existing Twitch/Kick split.
