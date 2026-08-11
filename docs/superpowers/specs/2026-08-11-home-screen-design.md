# Home Screen: Design

Date: 2026-08-11

## What this is

Replaces `lib/windows/home.py`'s no-op stub with a real Home screen: the user's followed Twitch
channels, live ones surfaced first, using the token saved by the device-code login flow
(`docs/superpowers/specs/2026-08-11-device-code-login-design.md`). This also gives `lib/twitch/api.py`
its first real implementation, replacing its scaffold stubs.

Clicking a channel, the Discover/search screen, and periodic live-status refresh while Home stays
open are explicitly out of scope — see "Out of scope" below.

## Why token refresh is in scope here

Device-flow access tokens expire after ~4 hours (`expires_in`, typically 14400s). Twitch's
`refresh_token` issued alongside it is long-lived (valid until revoked or unused for an extended
period) — refreshing on expiry means logging in once rather than every few hours. Since this is the
first screen that actually calls Twitch's API after login and will be the first to hit an expired
token, token refresh is built in now rather than deferred further.

## Components

### `lib/twitch/api.py` (replaces stub logic)

All Helix calls need both an OAuth bearer token AND a `Client-Id` header — this is a signature
addition over the original scaffold's guessed signatures (`access_token, user_id` etc., with no
`client_id`), the same kind of deliberate supersession `poll_device_code_once` was to
`poll_for_token`.

- `get_current_user(access_token, client_id) -> dict` — `GET
  https://api.twitch.tv/helix/users` (no `login` param returns the token's own user). Returns
  `{"id": ..., "login": ..., "display_name": ...}` from the first element of Twitch's `data` array.
- `get_followed_channels(access_token, client_id, user_id) -> list[dict]` — `GET
  https://api.twitch.tv/helix/channels/followed?user_id=...`. Returns Twitch's `data` list as-is
  (each item has `broadcaster_id`, `broadcaster_login`, `broadcaster_name`, `followed_at`).
- `get_live_status(access_token, client_id, user_ids) -> list[dict]` — `GET
  https://api.twitch.tv/helix/streams?user_id=...` (repeated `user_id` params). Twitch caps this
  endpoint at 100 `user_id` params per request; `get_live_status` splits `user_ids` into chunks of
  100 and issues one request per chunk, concatenating the results, so a large followed-channel list
  is never silently truncated. Returns Twitch's `data` list (`user_id`, `user_login`, `user_name`,
  `game_name`, `title`, `viewer_count`, `thumbnail_url`, `started_at` for each currently-live
  channel — only live channels appear here at all).
- `TokenExpiredError(Exception)` — raised by any of the above on an HTTP 401. `api.py` has no
  knowledge of tokens, refresh, or storage; it only signals "this token no longer works." The
  caller (`lib/windows/home.py`) owns what happens next.

### `lib/twitch/auth.py` (extended)

- `run_device_code_login(...)`: after a successful token exchange and before `save_token`, calls
  `api.get_current_user(token["access_token"], client_id)` and merges `user_id`, `login`,
  `display_name` into the token dict. If that call fails (network error or unexpected response),
  treated as a login failure — same `on_status("error")` path as the flow's other failure modes —
  rather than saving a token with no cached user info.
- `refresh_access_token(client_id, refresh_token) -> dict | None` — `POST
  https://id.twitch.tv/oauth2/token` with `grant_type=refresh_token`. Returns the new token dict
  (`access_token`, `refresh_token`, `expires_in`, ...) on success, or `None` on any failure
  (network error, non-200, or a Twitch error body like `invalid_grant` for a revoked refresh
  token) — mirrors `poll_device_code_once`'s "never raises for expected failure modes" style rather
  than using exceptions for an expected "refresh didn't work" outcome.
- `clear_token(addon) -> None` — removes the saved token (`addon.setSetting("twitch_token", "")`),
  used when refresh itself fails and the user must log in again from scratch.

### `lib/windows/home.py` (replaces stub logic)

`onInit`:
1. Load the token via `auth.load_token(addon)`. (It should always be present — `lib/main.py` only
   routes here when a token exists — but treat a missing token defensively the same as an expired
   one: show the re-login prompt rather than crashing.)
2. Call `api.get_followed_channels` then `api.get_live_status` for those channel ids.
3. On `TokenExpiredError`: call `auth.refresh_access_token(client_id, token["refresh_token"])`.
   - On success: merge the cached `user_id`/`login`/`display_name` from the old token into the new
     one (the refresh response doesn't include them), `auth.save_token(new_token, addon)`, retry
     step 2 once with the new access token.
     - If the retry *also* raises `TokenExpiredError` (or refresh silently returned a token that
       still doesn't work): treat as a hard failure — `auth.clear_token(addon)`, show the re-login
       prompt. No further retries.
   - On failure (`refresh_access_token` returns `None`): `auth.clear_token(addon)`, show the
     re-login prompt.
4. Merge followed-channels data with live-status data (`user_id` == `broadcaster_id`): channels
   with a live entry are "live" (sorted by `viewer_count` descending), channels without one are
   "offline" (sorted alphabetically by name), live channels listed before offline ones.
5. Populate a Kodi `<list>` control: each item shows the channel name; live items additionally show
   game name, viewer count, and a thumbnail (`thumbnail_url` with its `{width}`/`{height}`
   placeholders substituted, e.g. `320x180` — Kodi loads/caches remote image URLs natively, no local
   download/caching code needed).
6. Empty followed list (not an error, just nobody followed): show "You're not following anyone
   yet" instead of an empty list.
7. Network failure (not 401 — a `requests.RequestException` bubbling up from `api.py`, e.g. Twitch
   unreachable): show an error message with a retry option, don't crash.
8. Re-login prompt (from step 3's failure paths): a message plus a button that opens `LoginWindow`
   directly, so an expired session mid-use doesn't require restarting the addon.

### Skin XML

Real list layout (item + focused layout) for the followed-channels list, plus the empty-state,
network-error, and re-login-prompt messages/button — all sharing the large-centered-text convention
established by the login screen's visual fix
(`docs/superpowers/specs/2026-08-11-device-code-login-design.md`'s follow-up polish).

## Data flow

```
HomeWindow.onInit
  -> auth.load_token(addon)
  -> api.get_followed_channels(token) -> api.get_live_status(token, ids)
       TokenExpiredError -> auth.refresh_access_token(...)
            success -> auth.save_token(merged) -> retry get_followed_channels/get_live_status once
                 still fails -> auth.clear_token(addon) -> show re-login prompt
            failure (None) -> auth.clear_token(addon) -> show re-login prompt
  -> merge live + followed data (live first by viewer_count desc, then offline alphabetically)
  -> populate list control (thumbnail, name, game, viewer count for live)
```

## Error handling

- HTTP 401 on any `api.py` call: `TokenExpiredError`, handled via the refresh-then-reprompt flow
  above.
- Network failure (non-401, e.g. connection error, Twitch unreachable): caught in `home.py`,
  generic error message + retry option, token untouched (this isn't an auth problem).
- Empty followed-channels list: not an error — friendly "not following anyone yet" state.
- Malformed/unexpected Twitch response shape: not specially handled (YAGNI, matches the login
  flow's precedent) — an uncaught `KeyError`/`ValueError` surfaces as a logged exception via
  `xbmc.log` from the windows layer, shown as a generic error state, same pattern as the login
  flow's Task 3/7 fix.

## Testing

- `tests/twitch/test_api.py`: `get_current_user`, `get_followed_channels`, `get_live_status` each
  tested with mocked `requests` for success and 401→`TokenExpiredError`; `get_live_status` tested
  for the >100-id batching behavior (e.g. 150 ids → 2 requests, results concatenated).
- `tests/twitch/test_auth.py`: `run_device_code_login`'s extended success path tested with an
  injected fake `get_current_user`-equivalent (via a new injectable parameter, mirroring
  `request_fn`/`poll_fn`); `refresh_access_token` tested for success/failure/network-error;
  `clear_token` tested for a round-trip with `save_token`/`load_token`.
- `tests/windows/test_home_window.py` (new): `onInit`'s list-population logic tested with
  `tests/kodi_stubs/`, all `api`/`auth` calls injected/faked — no real network. Covers: normal
  populated list (live-first ordering), empty followed list, 401→successful-refresh→retry-succeeds,
  401→refresh-fails→re-login prompt, network error→error state.
- No test hits Twitch's real API.

## Out of scope for this task

- Playback when a channel is clicked (`lib/twitch/stream.py` stays a stub).
- Discover/search screen.
- Periodic live-status refresh while Home stays open (loaded once in `onInit`).
- Batched/paginated followed-channel fetching beyond what's needed for correctness (Twitch's
  `/channels/followed` is already paginated by Twitch; this task follows the pagination cursor to
  completion but doesn't add its own UI-level pagination/infinite-scroll).
