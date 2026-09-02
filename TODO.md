# TODO

- ~~Notify when a followed streamer goes live~~ REMOVED (v0.28.0, 2026-08-27): shipped in
  v0.26.0 as `lib/live_notify_service.py` (`LiveNotifyClient` in `lib/twitch/eventsub.py`), then
  fully deleted after v0.27.1-0.27.6 all failed to keep its cold-start EventSub subscribe burst
  (one `stream.online` subscription per followed channel, 140 in testing) inside Twitch's
  per-`client_id` rate limit without breaking chat, which shares the same `client_id`'s budget.
  Fixed-delay throttling, reactive 429 backoff, a startup race fix, and proactive
  Ratelimit-Remaining throttling were each tried and each fell short on live re-test; the last
  attempt got Twitch's server to close the WebSocket session outright after repeated 429s. Do
  not reintroduce without a real fix for the underlying rate-limit problem (e.g. spreading the
  burst over minutes instead of ~70s, not just tuning the backoff further).

- ~~Clip playback~~ FIXED (v0.28.2, 2026-08-27): every clip failed silently ("Couldn't start
  playback", no log line) because Twitch moved clip thumbnails to a CDN path
  (`.../twitch-video-assets/.../landscape/thumb/...`) with no derivable video-file name, killing
  the old thumbnail-URL-to-MP4 suffix-substitution trick `lib/twitch/stream.py`'s
  `resolve_clip_url` relied on. Now resolves via Twitch's undocumented `VideoAccessToken_Clip`
  GQL query (`lib/twitch/gql.py`'s `get_clip_video_url`) - sent as a raw query string (a guessed
  persisted-query hash was rejected outright), with the returned MP4 URL's playbackAccessToken
  signature/value appended as `?sig=...&token=...` (its CDN path 401s bare). Confirmed live on
  kodi.local, both Clips and VODs. `vod_clips_view.py`'s VOD/clip selection handlers also now
  log `StreamUnavailableError` at `LOGERROR` instead of swallowing it - that silence is why the
  clip bug had no log trail in the first place.

- ~~Chat overlay blocking player OSD/Select~~ FIXED (v0.28.8, 2026-09-02): Enter/Select
  during chat overlay did nothing (or, after an interim fix attempt, looped forever) instead
  of opening the player's OSD - user had to close chat (Back) first to reach it. Root cause
  was two stacked bugs in `lib/windows/chat_overlay.py`'s `onAction`: (1)
  `xbmc.executebuiltin("Action(%d)" % id)` passed a numeric id where the `Action()` builtin
  wants a name string, failing silently; (2) even fixed to use the name, `Action()` routes to
  whatever window is currently active - which is the overlay itself (non-modal, stays
  topmost/focused) - so the forward just re-entered the overlay's own `onAction` and looped.
  Fixed by using `ActivateWindow(12901)` to push the OSD dialog directly onto the window
  stack instead, bypassing active-window routing; closing OSD pops back to the still-open
  overlay. `ACTION_CONTEXT_MENU` forwarding dropped (no fixed window id for it). Confirmed
  live on both the dev Kodi instance and kodi.local over the real CEC remote - the original
  reported symptom.

- ~~Tackle chat~~ DONE (v0.10.0): `lib/twitch/irc.py`'s `ChatClient` and `lib/windows/chat_overlay.py`
  are real and live-tested (Quin69, busy chat). The `chat_overlay_enabled` setting shows it
  automatically during playback; auto-reconnects, auto-scrolls, throttled rendering, closes on
  stop/end/error. The old "standalone" full-screen chat mode (never implemented beyond a stub) was
  removed - `chat_display_mode`'s three-way overlay/standalone/both choice is gone, replaced by
  this single boolean.

- Follow current streamer from the addon: NOT possible - Twitch removed the Create/Delete User
  Follow endpoints from the Helix API in Feb 2023. Third-party apps can no longer follow/unfollow
  programmatically; only Twitch's own web/app UI can. Dead end, don't attempt.

- ~~Follow raids~~ DONE (v0.29.0, 2026-09-02), confirmed working live on kodi.local: raid
  fired, prompt shown, auto-accepted after the countdown, playback switched cleanly to the
  raided-into channel with a fresh chat overlay, no errors. `follow_raids_enabled` setting
  (default on) - when
  the watched channel raids out, `lib/windows/raid_prompt.py`'s `RaidPromptDialog` shows a
  15s-countdown prompt (Decline to stay, countdown reaching zero or Select to switch),
  then `chat_overlay.py`'s `_handle_raid_out` resolves and plays the target channel via the
  same `providers.resolve_stream_url` + `player.play_stream` pattern
  `live_streams_view.py`'s `_play_channel` already uses. EventSub-only: `lib/twitch/
  eventsub.py` now subscribes to `channel.raid` with `from_broadcaster_user_id` (a second,
  separate subscription alongside the existing `to_broadcaster_user_id` one for incoming
  raids) and yields a `"raid_out"` event with the destination channel. IRC has no
  equivalent - Twitch's `USERNOTICE`/`msg-id=raid` only fires in the destination channel's
  chat, never the source's - so under the (default) `irc` chat engine this silently never
  fires, same as any other unhandled event type.

- ~~Migrate chat from IRC to EventSub~~ DONE (v0.16.0), as a selectable `chat_engine` setting
  rather than a full replacement - `lib/twitch/eventsub.py`'s `ChatClient` is available alongside
  `lib/twitch/irc.py`'s, chosen via Settings > General > "Chat engine" (default stays `irc`).
  Available on Live Streams and Discover tabs (authenticated); Search doesn't support EventSub
  (unauthenticated feature, so no OAuth token for EventSub ID resolution). Falls back to IRC on
  authenticated screens if broadcaster ID resolution fails.

- Playback resolution was low on one stream after the v0.6.5 anonymous-playback-token fix, but
  fine on another (DatModz) - confirmed per-streamer difference (source bitrate/quality choice),
  not a regression from going anonymous. Anonymous requests are still capped at FULL_HD/12500kbps
  by Twitch (`AUTHZ_NOT_LOGGED_IN` blocks QUAD_HD/ULTRA_HD) - fine for now, revisit only if a
  streamer's own source is above 1080p and that cap becomes the actual limiter.

- Kick version of VODs & Clips: deliberately deferred (2026-08-27) when VODs & Clips shipped for
  Twitch - see `docs/superpowers/specs/2026-08-27-vods-clips-design.md`. Would need: (1)
  `lib/kick/api.py` equivalents of `get_videos`/`get_clips` (Kick's API surface for this is
  unconfirmed/unexplored - existing `lib/kick/api.py` only covers live streams, categories, and
  channel lookup); (2) Kick's own VOD/Clip playback resolution (`lib/kick/stream.py`'s
  `resolve_stream_url` is live-only, unauthenticated `kick.com/api/v2/channels/{slug}` - VOD/Clip
  playback is a different, unresearched mechanism entirely); (3) a `platform` branch each in
  `lib/providers.py`'s `resolve_vod_url`/`resolve_clip_url`, mirroring `resolve_stream_url`'s
  existing Twitch/Kick split.
