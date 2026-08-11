# Twitch Device-Code Login: Design

Date: 2026-08-11

## What this is

The first real (non-stub) feature on top of the `twitch-center` scaffold: logging into Twitch from
Kodi using Twitch's OAuth device-code flow, so the addon can hold a token, and so `lib/main.py` has
something real to route on (login screen vs. home screen).

This replaces the stub behavior of `lib/twitch/auth.py` and `lib/windows/login.py` from the
original scaffold (`docs/superpowers/specs/2026-08-11-project-scaffold-design.md`) with working
logic. It does not touch `lib/twitch/api.py`, `lib/twitch/stream.py`, `lib/twitch/irc.py`, or the
Home/Discover screens — those stay stubbed, per that scaffold's "Follow-up specs" list.

## Why device-code flow

Kodi has no convenient browser or keyboard for a normal OAuth redirect flow. Twitch's device-code
flow fits: the addon requests a short code, displays it plus `twitch.tv/activate`, and the user
authorizes on any other device (phone, PC) while Kodi polls in the background. No client secret is
stored on-device, and no embedded browser/webview is needed.

## Client ID

Twitch requires a registered app Client ID for the device-code flow. The user has registered one:
`f6exkvelsf4gmy83b8zat5i10t3gy6`. Client IDs are not secret (Twitch does not treat them as
confidential for public/device-flow clients) and are safe to commit as a default setting value.

It is stored as a new `client_id` string setting in `resources/settings.xml`, defaulted to the
value above, in a hidden category (not exposed in the visible Settings UI — a regular user never
needs to see or change it).

## Scopes

Requested scopes are fixed at `["user:read:follows"]` — the only scope the already-designed
follow-up features need (Home's followed-channels list, Discover's games-derived-from-followed-
channels). Defined as a `SCOPES` constant in `lib/twitch/auth.py` rather than a setting, since
there's no user-facing reason to configure it. Chat reading via IRC does not require a scope (Twitch
IRC accepts an OAuth token for identification but any valid user token works for reading; no
additional scope needed for the read-only chat use case this addon targets).

## Components

### `lib/twitch/auth.py` (replaces stub logic)

- `request_device_code(client_id, scopes)` — `POST https://id.twitch.tv/oauth2/device` with
  `client_id` and space-joined `scopes`. Returns a dict with `device_code`, `user_code`,
  `verification_uri`, `expires_in`, `interval`, taken directly from Twitch's JSON response.
- `poll_device_code_once(client_id, device_code)` — **replaces** the old `poll_for_token(client_id,
  device_code, interval)` stub signature. Makes exactly one
  `POST https://id.twitch.tv/oauth2/token` call with `client_id`, `device_code`, and
  `grant_type=urn:ietf:params:oauth:grant-type:device_code`. Returns one of:
  - `{"status": "success", "token": {access_token, refresh_token, expires_in, scope, token_type}}`
  - `{"status": "pending"}` — Twitch's `authorization_pending` error
  - `{"status": "slow_down"}` — Twitch's `slow_down` error
  - `{"status": "expired"}` — Twitch's `expired_token` error, or a non-2xx/network error Twitch
    surfaces as unrecoverable
  This is a single attempt, not a blocking loop — the caller (`lib/windows/login.py`) owns the
  polling loop, timing, and cancellation, so the UI thread stays responsive and the login screen
  can be canceled mid-poll. This is the one deliberate interface change from the original scaffold
  stub, made because a blocking `poll_for_token` can't be canceled or drive UI updates between
  attempts.
- `save_token(token)` — serializes the token dict to JSON and writes it via
  `xbmcaddon.Addon().setSetting("twitch_token", json_string)` — this touches `xbmcaddon`, so despite
  living in `lib/twitch/`, **this one function is an exception to the "lib/twitch/* has zero
  xbmc* imports" rule.**  See "Architectural boundary note" below for how this is handled.
- `load_token()` — reads and JSON-deserializes the same setting; returns `None` if unset or
  unparseable.

**Architectural boundary note:** the scaffold's hard rule is "`lib/twitch/*` must have zero
`xbmc*` imports." `save_token`/`load_token` need to persist somewhere, and the approved storage
choice is a hidden `xbmcaddon` setting. To keep the rule intact (and keep `tests/test_architecture.py`
meaningful), `save_token`/`load_token` take the storage object as a parameter rather than importing
`xbmcaddon` directly:

```python
def save_token(token, addon):
    addon.setSetting("twitch_token", json.dumps(token))

def load_token(addon):
    raw = addon.getSetting("twitch_token")
    if not raw:
        return None
    try:
        return json.loads(raw)
    except ValueError:
        return None
```

`lib/windows/login.py` (which already imports `xbmcaddon` via `lib/settings.py`'s pattern) passes
in a real `xbmcaddon.Addon()` instance; tests pass in the `tests/kodi_stubs/xbmcaddon.Addon` stub or
a plain fake object. This keeps `auth.py` importing nothing beyond `json` and `requests`, so
`tests/test_architecture.py`'s static AST check continues to hold with no changes needed.

### `resources/skins/Default/1080i/script-twitch-center-login.xml` (new)

A `WindowXML` layout with:
- a label for the user code (large, prominent)
- a label for the verification URL (`twitch.tv/activate`)
- a status label (e.g. "Waiting for authorization...", "Code expired", "Connection error")
- a "Cancel" button

This also fills the gap the final scaffold review flagged (Minor #4: `resources/skins/` directory
didn't exist yet).

### `lib/windows/login.py` (replaces stub logic)

`LoginWindow.onInit`:
1. Reads `client_id` from `lib.settings.Settings`.
2. Calls `auth.request_device_code(client_id, scopes)` on a background thread (network call must
   not block Kodi's UI thread).
3. On success, sets the code/URL labels, then loops: `time.sleep(interval)`,
   `auth.poll_device_code_once(...)`, update status label based on result.
   - `"pending"`: keep looping.
   - `"slow_down"`: increase the local `interval` and keep looping (Twitch's documented backoff
     contract), no UI change needed beyond continuing to show "waiting".
   - `"expired"`: stop, show an error status, re-show the Cancel/retry affordance.
   - `"success"`: call `auth.save_token(token, addon)`, stop the thread, close the window, and
     signal `lib/main.py` to proceed to `HomeWindow`.
4. `onAction` handles Back/Cancel: stops the background thread (a `threading.Event` the loop checks
   each iteration) and closes the window without saving anything.

### `lib/main.py` (replaces stub logic)

`run(argv)`:
```python
addon = xbmcaddon.Addon()
token = auth.load_token(addon)
if token is None:
    open LoginWindow
else:
    open HomeWindow
```
(`HomeWindow` stays a stub per the original scaffold — this task only wires the routing, not
Home's content.)

## Data flow

```
LoginWindow.onInit
  -> auth.request_device_code(client_id, scopes)
  -> display user_code + verification_uri
  -> loop: auth.poll_device_code_once(client_id, device_code)
       pending/slow_down -> keep looping
       expired -> show error, stop
       success -> auth.save_token(token, addon) -> close -> main.py opens HomeWindow
```

## Error handling

- Network failure on `request_device_code` (e.g. `requests.RequestException`): caught in
  `login.py`'s background thread, shown as a status-label error, loop does not start.
- Network failure on an individual `poll_device_code_once` call: treated the same as `"pending"` —
  log it, keep polling on the next interval, rather than aborting the whole flow on a single
  transient blip. (`poll_device_code_once` itself catches `requests.RequestException` and returns
  `{"status": "pending"}` in that case, so `login.py` doesn't need separate network-error handling
  from Twitch's own `authorization_pending`.)
- `expired_token` from Twitch: terminal — show error, let the user retry via a fresh Cancel-then-
  reopen (no in-place "restart" affordance in this task; re-invoking the addon restarts the flow).
- Malformed/missing fields in Twitch's JSON responses: not specially handled in this task — a
  `KeyError`/`ValueError` surfaces as an uncaught exception in the background thread, logged via
  `xbmc.log`, and the loop stops with a generic error status. Full response validation is out of
  scope for this task (YAGNI — Twitch's documented response shape is trusted).

## Testing

- `tests/twitch/test_auth.py` (rewritten from the current NotImplementedError-only tests):
  - `request_device_code`: mocked `requests.post` returning a realistic Twitch JSON body; asserts
    the returned dict and the request payload (client_id, scopes joined correctly).
  - `poll_device_code_once`: mocked `requests.post` for each of the four outcomes (success,
    `authorization_pending`, `slow_down`, `expired_token`) plus a `requests.RequestException` case.
  - `save_token`/`load_token`: use a plain fake object with `setSetting`/`getSetting` (not
    `tests/kodi_stubs/xbmcaddon`, to keep `lib/twitch/` tests independent of the Kodi-stub test
    fixture) — round-trip a token dict, and confirm `load_token` returns `None` for unset/garbage
    settings.
- `tests/test_architecture.py`: no changes needed — `auth.py` still imports no `xbmc*` modules.
- `lib/windows/login.py`: tested at the construction/label level using `tests/kodi_stubs/`, with the
  polling loop's network calls replaced by an injectable fake `poll_fn` so no real threading/sleep
  happens in tests (exact test list is left to the implementation plan, not fully enumerated here).
- No test hits Twitch's real API.

## Out of scope for this task

- Token refresh (Twitch's device-flow tokens include a `refresh_token`; refreshing is deferred until
  `lib/twitch/api.py` is implemented and needs to react to a 401).
- Multi-account support (single saved token only, per your earlier decision).
- `HomeWindow` content — routing to it is wired, but it stays the existing no-op stub.
- Any QR-code rendering of the verification URL (text only).
