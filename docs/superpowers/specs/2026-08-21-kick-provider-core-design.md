# Kick provider core — design spec

## Context

twitch-center is a Kodi addon for watching Twitch streams and chat
(`lib/twitch/`: `auth.py`, `api.py`, `gql.py`, `stream.py`, `irc.py`,
`eventsub.py`). This is the first of four planned sub-projects to add
Kick as a second platform:

1. **Kick provider core** (this spec) — auth, REST API client, stream
   URL resolution
2. Kick chat client (Pusher WebSocket protocol)
3. UI unification — merge Twitch+Kick results in Live/Discover/Search,
   platform tagging, settings entries
4. Playback/chat wiring — route `main_window`/`player`/`chat_overlay`
   to the correct provider per stream

Full platform parity is the goal: login, live streams, discover,
search, chat, playback for Kick alongside Twitch, presented as unified
lists (not separate menus or a single-platform toggle).

## Goals

- Add `lib/kick/` package providing auth, API, and stream-resolution
  functionality equivalent to `lib/twitch/auth.py` + `api.py` +
  `stream.py`, following the same architectural rule: no `xbmc*`
  imports, pure Python, pytest-testable.
- Kick login uses Kick's official Public API OAuth 2.1 Authorization
  Code + PKCE flow (Kick has no device-code flow), with a local
  loopback HTTP server catching the redirect.
- Match the existing Twitch module's external interface shape closely
  enough that sub-project 4 (playback/chat wiring) can dispatch to
  either provider with minimal branching.

## Non-goals

- Chat (sub-project 2).
- Any UI/view changes (sub-project 3) or main_window/player routing
  (sub-project 4) — this spec only adds the `lib/kick/` package and
  its tests, unused by the rest of the app until later sub-projects
  wire it in.
- Kick account features beyond what's needed for parity with current
  Twitch features (no follows-management, no clips, no VODs).

## Background: Kick Public API

- Base URL: `https://api.kick.com/public/v1`.
- OAuth 2.1. Two token types: App Access Tokens (Client Credentials,
  public data only) and User Access Tokens (Authorization Code +
  PKCE, scoped, needed for anything user-specific). This spec uses
  User Access Tokens throughout, for consistency with the Twitch flow
  (which always logs a user in) and because chat (sub-project 2) will
  need `chat:write`.
- Access tokens expire in ~1 hour; a refresh token is issued alongside
  and exchanged the same way as Twitch's refresh flow.
- Endpoints used here: `/channels` (by slug or broadcaster id),
  `/livestreams` (list, filterable by `category_id`, cursor
  pagination), `/categories` (list/top), `/users` (current user).
- No confirmed official free-text channel search endpoint. Handled as
  an isolated fallback — see `api.search_channels` below.

## Package layout: `lib/kick/`

Mirrors `lib/twitch/`'s split of concerns, one module per file.

### `lib/kick/auth.py`

Pure Python, no `xbmc*` imports (same discipline as `twitch/auth.py`).

- `generate_pkce_pair()` — returns `(code_verifier, code_challenge)`
  per RFC 7636 (S256).
- `build_authorize_url(client_id, redirect_uri, code_challenge, scopes, state)`
  — builds the Kick authorization URL the user opens in a browser.
- `_LoopbackCallbackServer` — a small `http.server.HTTPServer` bound
  to `127.0.0.1:<port>`, run on a background thread, that serves one
  request: capture `code` and `state` query params from the redirect,
  respond with a static "you can close this tab" HTML page, then shut
  itself down. Exposes the captured `(code, state)` (or a timeout/error)
  to the caller via a `queue.Queue` or equivalent — same pattern as
  `cancel_event` in the Twitch flow: the polling/waiting side owns
  cancellation.
- `exchange_code_for_token(client_id, redirect_uri, code, code_verifier)`
  — POST to Kick's token endpoint, returns the token dict. Raises
  `requests.RequestException` on network/HTTP failure (mirrors
  `request_device_code`).
- `refresh_access_token(client_id, refresh_token, on_error=None)` —
  same contract as `twitch/auth.py`'s function of the same name:
  returns `None` on any failure (never raises), calls `on_error` with
  a diagnostic string if given.
- `save_token(token, addon)` / `load_token(addon)` / `clear_token(addon)`
  — same shape as Twitch's, using a new `kick_token` hidden setting.
- `run_pkce_login(client_id, redirect_port, scopes, addon, on_code, on_status, cancel_event, ...)`
  — orchestrator mirroring `run_device_code_login`'s callback contract
  (`on_code(url_or_instructions, ...)`, `on_status("pending"/"success"/"expired"/"error")`,
  cooperative cancellation via `cancel_event`) so `login_view.py` can
  drive both flows through a common shape. Differences from the
  device-code flow: `on_code` is called once with the authorize URL to
  open (there's no separate user-facing code to display — the loopback
  server does the waiting instead of polling), and the "poll" step
  becomes "wait for the loopback server to receive a callback or for
  cancellation." Caches current-user info onto the token dict before
  saving, same as the Twitch flow, via a `get_current_user_fn` seam
  (defaults to `api.get_current_user`).

Open implementation question (resolve during coding, not blocking this
spec): fixed vs. OS-assigned loopback port. Kick's OAuth app
registration requires a redirect URI to be pre-registered; if it must
be exact, use a fixed port (documented in settings) rather than
`port=0`.

### `lib/kick/api.py`

Pure Python, no `xbmc*` imports.

- `TokenExpiredError` — same role as `twitch/api.py`'s: raised on
  HTTP 401.
- `_headers(access_token)` — Kick's Public API auth is `Authorization:
  Bearer <token>` only (no separate client-id header requirement like
  Helix).
- `get_current_user(access_token)` → `{id, login/slug, display_name}`
  shape matching Twitch's `get_current_user` return, field names
  translated (Kick uses `slug`/`username` naming — normalize to the
  same dict keys Twitch uses so callers in later sub-projects don't
  need to branch on platform for basic display).
- `get_channel(access_token, slug)` → channel info dict, including
  live status.
- `get_live_streams(access_token, category_id=None, first=20)` →
  list of live streams, matching Twitch's `get_live_streams_by_game`
  shape as closely as field-naming allows.
- `get_top_categories(access_token, first=20)` → list of
  `{"id", "name"}`, matching `get_top_games`.
- `search_channels(access_token, query, first=20)` — isolated in its
  own function specifically because it's the one call not confirmed
  against the official API; if no official endpoint exists, this
  function is the single place an unofficial fallback lives (same
  precedent as `twitch/gql.py`'s unofficial playback-token lookup).
  Implementation confirms against `docs.kick.com` at coding time.
- `get_user_by_login(access_token, slug)` → `{id, login, display_name}`
  or `None`, matching Twitch's shape.

### `lib/kick/stream.py`

- `StreamUnavailableError` — same role as `twitch/stream.py`'s.
- `resolve_stream_url(access_token, channel_slug)` — Kick's channel/
  livestream API response includes the HLS playback URL directly
  (no separate signed-access-token exchange like Twitch's usher/gql
  dance). This function calls `api.get_channel`, extracts the
  `.m3u8` URL, and raises `StreamUnavailableError` if the channel
  isn't live or the field is missing.

### `lib/kick/__init__.py`

Empty, matching `lib/twitch/__init__.py`.

## Settings

Add to `lib/settings.py` (new properties, following the existing
`Settings` class pattern):

- `kick_client_id` — read from addon settings (user provides their own
  Kick OAuth app client id, same as `twitch_client_id` presumably
  already works).
- `kick_redirect_port` — fixed loopback port for the PKCE redirect
  (default e.g. `8919`; documented in `addon.xml` settings so the user
  can register the matching redirect URI with Kick).

No `xbmc*` imports added outside `settings.py` itself — consistent
with the existing split (`lib/settings.py` is the one place allowed to
import `xbmcaddon`).

## Error handling

Same philosophy as the Twitch modules throughout:

- Network/HTTP failures during best-effort calls (refresh) are
  swallowed and reported via `on_error`/`None` return, never raised.
- Failures during calls the caller must react to (token exchange,
  API calls needed to render something) raise (`requests.RequestException`,
  `TokenExpiredError`, `StreamUnavailableError`) and are the caller's
  responsibility — this package stays free of UI/Kodi concerns.

## Testing

New `tests/kick/` directory mirroring `tests/twitch/` (or wherever the
existing Twitch tests live — match current structure). Covers:

- `auth.py`: PKCE pair generation (S256 correctness), authorize-URL
  building, loopback server capturing a simulated redirect request,
  token exchange (mocked `requests`), refresh success/failure paths,
  save/load/clear token round-trip, `run_pkce_login` orchestration
  (success, cancellation, error, mirroring the existing
  `run_device_code_login` test cases where the flow shape matches).
- `api.py`: each function against mocked `requests` responses,
  including the 401 → `TokenExpiredError` path.
- `stream.py`: URL resolution success and `StreamUnavailableError`
  paths.

No live network calls in tests, consistent with the existing suite.

## Risks / open items

- Kick's exact JSON field names for channels/livestreams/categories
  are not fully confirmed from documentation search alone — the
  `api.py` functions above describe shape and intent; exact field
  mapping gets nailed down against `docs.kick.com` (or a live request)
  during implementation, same as any API-wrapper code would.
- No confirmed official search endpoint (see `search_channels` above) —
  isolated so a future swap to/from an unofficial endpoint doesn't
  ripple into callers.
- Fixed vs. dynamic loopback port for the PKCE redirect — resolve
  during implementation per Kick's redirect-URI registration
  requirements.
