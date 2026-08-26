# Live-Go Notifications for Followed Twitch Channels

Date: 2026-08-26
Status: Approved for planning

## Problem

Twitch Center has no way to tell the user a followed streamer just went live
unless they manually open the addon and check the Live Streams view
(`lib/views/live_streams_view.py`). The addon only registers a
`xbmc.python.script` extension point in `addon.xml` — it runs on demand and
exits when the user backs out, so there is no process running in the
background to notice a followed channel going live.

## Goal

When enabled, show a Kodi notification ("Twitch Center — `<display name>` is
live") shortly after a followed Twitch channel goes live, without the user
having the addon window open.

## Scope

- Twitch only. Kick favorites (`lib/views/kick_favorites_menu.py`) are out of
  scope — Kick has no live-status polling/notification infra yet and was
  explicitly deprioritized for this feature.
- Text-only Kodi notification popup. No click-through/action button — matches
  every other notification already in this codebase (`lib/player/audio.py`,
  `lib/views/kick_favorites_menu.py`), and Kodi's basic
  `xbmcgui.Dialog().notification()` has no click-action support anyway.
- Opt-in via a new Settings toggle, off by default. This introduces a new
  always-on background WebSocket connection; existing users should not get
  that sprung on them by an update.

## Architecture

### New service component

Kodi supports a single addon declaring both an `xbmc.python.script`
extension point (existing, `lib/main.py`) and an `xbmc.service` extension
point (new) side by side in one `addon.xml`. The service's library starts
automatically when Kodi boots and runs for Kodi's whole lifetime,
independent of whether the user ever opens the script.

Add:

```xml
<extension point="xbmc.service" library="lib/live_notify_service.py" start="startup"/>
```

New file `lib/live_notify_service.py`, entry point run directly by Kodi
(mirrors `lib/main.py`'s existing `sys.path` bootstrap pattern since Kodi
puts `lib/` itself on `sys.path`, not the addon root).

### Service loop

`lib/live_notify_service.py`:

1. On start, and every `_SETTING_POLL_INTERVAL` (e.g. 60s) via
   `xbmc.Monitor.waitForAbort()`, check
   `addon.getSettingBool("live_notify_enabled")`.
2. If disabled: do nothing (loop stays alive polling only the setting, so
   toggling it on takes effect without a Kodi restart).
3. If enabled and not already connected: load the stored token
   (`lib.twitch.auth.load_token`), fetch followed channels
   (`lib.twitch.api.get_followed_channels`), and start a
   `live_notify.LiveNotifyClient` (new class, see below).
4. If enabled and connected: every `_FOLLOW_REFRESH_INTERVAL` (e.g. 10
   minutes), re-fetch followed channels and diff against the client's
   current subscription set — subscribe newly-followed broadcasters,
   unsubscribe unfollowed ones. (EventSub subscriptions don't need to be
   torn down for a live client already connected to notice a follow-list
   change; the client just adds/removes subscriptions on its existing
   session.)
5. If the setting is toggled off, disconnect the client.
6. On `xbmc.Monitor.abortRequested()` (Kodi shutting down), disconnect and
   exit the loop.

### EventSub client

Twitch's chat client (`lib/twitch/eventsub.py::ChatClient`) is scoped to
exactly one broadcaster and two hardcoded subscription types
(`channel.chat.message`, `channel.raid`). It is not a fit for "many
broadcasters, one subscription type, set changes over time" — reshaping it
to cover both would tangle two different lifecycles into one class.

Add a new class in the same module, **reusing** its free-standing framing
helpers (`_build_handshake_key`, `_build_handshake_request`,
`_parse_handshake_response`, `_encode_client_frame`, `_decode_frame`,
`_parse_rfc3339_ms`) and its backoff/reconnect constants:

```python
class LiveNotifyClient:
    def __init__(self, access_token, client_id, user_id, socket_factory=None,
                 sleep_fn=None, create_subscription_fn=None, delete_subscription_fn=None,
                 time_fn=None):
        ...
    def connect(self):
        """Spawns background thread, opens WS, session_welcome handshake. No
        subscriptions yet - caller drives membership via set_broadcasters()."""
    def set_broadcasters(self, broadcaster_user_ids):
        """Diffs against currently-subscribed IDs; creates stream.online
        subscriptions for additions, deletes for removals."""
    def read_events(self):
        """Generator yielding {"type": "stream_online", "broadcaster_user_id",
        "broadcaster_user_login", "broadcaster_user_name"} dicts, plus the
        existing {"type": "status", ...} connect/disconnect events."""
    def disconnect(self):
        ...
```

- Subscription type: `stream.online`, condition
  `{"broadcaster_user_id": "<id>"}`, version `"1"`.
- `create_eventsub_subscription` (already in `lib/twitch/api.py`) is reused
  as-is. A new `delete_eventsub_subscription(access_token, client_id,
  subscription_id)` helper is added to `lib/twitch/api.py` (Twitch's
  `DELETE /helix/eventsub/subscriptions?id=...`) since nothing in this
  codebase deletes a subscription today.
- Reconnect/backoff behavior (exponential backoff, reset-after-30s-connected)
  is copied from `ChatClient._run`, since a dropped connection needs the same
  treatment and there's no shared base class to extract without adding
  ceremony neither client needs elsewhere.
- Twitch limits an EventSub WebSocket session to ~300 subscriptions; a
  followed-channel list realistically won't hit that. Not handled specially
  — if `create_eventsub_subscription` raises `HTTPError` for a single
  broadcaster (e.g. limit hit, or user unfollowed a nonexistent ID race), the
  service logs and skips that one broadcaster rather than tearing down the
  whole connection.

### Notification delivery

`lib/live_notify_service.py`'s main loop drains
`LiveNotifyClient.read_events()`; on a `stream_online` event, calls
`xbmcgui.Dialog().notification("Twitch Center", "<broadcaster_user_name> is live")`.

### Settings

Add to `resources/settings.xml`, `general` category:

```xml
<setting id="live_notify_enabled" type="boolean" label="30030">
  <level>0</level>
  <default>false</default>
  <control type="toggle"/>
</setting>
```

New string ID `30030` added to `resources/language/resource.language.en_gb/strings.po`
(e.g. "Notify when followed streamers go live").

## Error handling

- No stored token / token invalid at service start: skip silently (same as
  `lib/main.py`'s existing `initial_view = "login"` fallback — this is a
  background service, it must never pop a login prompt on its own). Retry on
  the next setting-poll tick in case the user logs in later.
- `get_followed_channels` failure (network blip): log, retry next
  follow-refresh tick. Don't tear down an already-connected WS session over
  a transient Helix failure.
- WS disconnects: handled by the existing backoff/reconnect loop shape
  copied from `ChatClient`.

## Testing

- `LiveNotifyClient` is pure-Python (no `xbmc*` imports), pytest-testable
  the same way `eventsub.ChatClient` already is: injected `socket_factory`,
  `sleep_fn`, `create_subscription_fn`, `delete_subscription_fn`, `time_fn`.
  Tests cover: `set_broadcasters` diff logic (subscribe additions, delete
  removals, no-op on unchanged set), `stream_online` event parsing, backoff
  on disconnect.
- `lib/live_notify_service.py` itself (the `xbmc*`-importing loop) is
  exercised the way `lib/main.py::run()` is — via injected fakes for
  `addon`, `monitor_cls`, and a constructible client — verifying the
  setting-off/on transitions and follow-list diffing, not a real Kodi
  runtime.
- `lib/twitch/api.py::delete_eventsub_subscription` tested the same way
  neighboring `api.py` functions are (mocked `requests`).

## Out of scope / explicitly deferred

- Kick live-go notifications.
- Click-through notification actions.
- On-by-default enablement.
- Any UI surface inside the addon window itself beyond the new Settings
  toggle (no in-app notification history/log).
