# Chat Engine: Add EventSub, Selectable Alongside IRC: Design

Date: 2026-08-18

## What this is

Adds a second chat transport, `lib/twitch/eventsub.py`'s `ChatClient`, backed by Twitch's EventSub
WebSocket (`wss://eventsub.wss.twitch.tv/ws`) and subscribed to `channel.chat.message` (and
`channel.raid`, EventSub's equivalent of IRC's `USERNOTICE`/`msg-id=raid`). Per `TODO.md`'s existing
backlog entry for this migration - revised per user direction during planning: **not** a replacement.
`lib/twitch/irc.py` stays as-is and remains the default; a new Settings > General > "Chat engine"
option (`chat_engine`: `"irc"` default, `"eventsub"`) lets the user opt into EventSub per-install.

Scope: the chat *transport* only, plus the settings/wiring needed to pick one at connect time.
`lib/windows/chat_overlay.py`'s rendering/throttling logic is unchanged - it already consumes a
transport-agnostic event shape (`{"type": "message", "display_name", "text", "timestamp"}` /
`{"type": "raid", ...}` / `{"type": "status", "state": ...}`), and both `ChatClient` implementations
now share one constructor signature, so the overlay only needs to know which class to instantiate,
not how either one works internally.

## Why this shape

EventSub is Twitch's officially supported chat-reading path; anonymous IRC (`justinfan<N>`) is
undocumented and can be rate-limited or cut off without notice - but it also needs no login at all,
which is a real usability advantage for a "just watch chat" viewer. Rather than pick a winner, both
stay available and the user decides via a setting. The tradeoff EventSub brings when chosen: an
authenticated user token (`user:read:chat` scope) and a WebSocket session-management handshake
(welcome/keepalive/reconnect messages) that plain IRC didn't need.

No third-party WebSocket library is added. This codebase already hand-rolls IRC's raw-socket protocol
in `lib/twitch/irc.py` rather than depending on an IRC library, and `addon.xml` only declares
`script.module.requests` and `script.module.inputstreamhelper` as dependencies - consistent with that,
`lib/twitch/eventsub.py` hand-rolls the WebSocket handshake (RFC 6455 opening handshake) and frame
codec (text/ping/pong/close, client-to-server masking) directly over `ssl`-wrapped `socket`, same as
`irc.py` does for its TLS socket. This keeps the dependency footprint and threading model (background
thread + `queue.Queue`, `threading.Event` cancellation, `sleep_fn`-injectable backoff) identical
between the two engines.

## Scope decisions

- **Selectable, not a replacement**: new `chat_engine` setting (`"irc"` default, `"eventsub"`),
  `VALID_CHAT_ENGINES = ("irc", "eventsub")` in `lib/settings.py`, same pattern as the existing
  `chat_display_mode` setting. `lib/twitch/irc.py` and its tests are untouched - anonymous,
  no-login chat viewing stays the default and keeps working exactly as it does today. Users who
  want EventSub's richer/official-path data opt in explicitly; nothing breaks for anyone who
  doesn't touch the new setting.
- **Auth**: mandatory only when `chat_engine == "eventsub"`. `channel.chat.message` has no anonymous
  mode. Adds `"user:read:chat"` to `SCOPES` in `lib/twitch/auth.py` so newly-issued tokens carry it,
  but since IRC remains the default engine, this doesn't force existing users to re-login
  immediately - only someone who switches `chat_engine` to `"eventsub"` needs a token with the new
  scope. If the currently-saved token predates this scope (Twitch has no "does my token have scope
  X" introspection short of trying the call and getting a `401`/`403`), `player.py`'s EventSub path
  treats a subscription-create failure exactly like any other connect failure: log it, skip the
  overlay for this session (see "player.py" below) - the user then needs the existing "Log in
  again" button (from `2026-08-12-settings-relogin-and-token-visibility-design.md`) to pick up the
  new scope, same recovery path as any other expired/invalid-token case elsewhere in this app. No
  new UI needed for this, but call it out in the `chat_engine` setting's help text and in
  `CHANGELOG.md`/`addon.xml`'s `<news>`.
- **ID resolution**: EventSub subscribes by numeric Twitch user ID, not login name. `play_stream`
  currently only has the channel's login string (from `search_view.py`/`discover_view.py`/
  `live_streams_view.py`, none of which currently carry the numeric id through to `play_stream`).
  Adds `api.get_user_by_login` (Helix `/users?login=`) to resolve `broadcaster_user_id` at
  `play_stream` time. The token owner's own `user_id` (needed as the subscription's `user_id`
  condition field) is already cached on the saved token dict (`token["user_id"]`, set at login -
  see `auth.py`'s `run_device_code_login`).
- **Delivery model**: unchanged from IRC - background thread + `queue.Queue`, non-blocking
  `connect()`, generator `read_messages()`, `disconnect()` sets a cancel event and joins the thread.
- **Event shape**: unchanged (see "What this is"). `chat_overlay.py` needs zero rendering changes.
- **Reconnect**: Twitch's `session_reconnect` message (sent proactively before Twitch closes a
  session, e.g. for load balancing) is handled as a **full reconnect**, not the zero-downtime
  dual-connection handoff Twitch's docs describe (open new session, migrate subscriptions, then
  close old) - simpler, consistent with this being a read-only convenience feature tier (per
  `2026-08-12-irc-chat-client-design.md`'s "authenticated chat... revisit only if a future feature
  requires it" framing), at the cost of a brief reconnect gap instead of none. Socket-level errors
  and missed keepalives reuse IRC's existing exponential-backoff reconnect loop unchanged (1s → 2s
  → 4s → ... capped at 30s, reset after >30s connected).
- **Keepalive**: EventSub sends `session_keepalive` messages at a negotiated interval (requested as
  10s at subscribe time). If no message of any kind (keepalive or otherwise) arrives within
  `2 * keepalive_timeout_seconds`, the connection is treated as stalled and torn down to trigger
  reconnect - EventSub gives no lower-level heartbeat to rely on instead.
- **Subscriptions**: two, created via `POST /helix/eventsub/subscriptions` right after
  `session_welcome` is received: `channel.chat.message` (condition
  `{broadcaster_user_id, user_id}`) and `channel.raid` (condition `{to_broadcaster_user_id:
  broadcaster_user_id}`), both `transport: {method: "websocket", session_id}`. A subscription
  request failing (bad scope, revoked token, etc.) surfaces as a `{"type": "status", "state":
  "disconnected"}` event and follows the same backoff-retry loop as a socket error - no special-cased
  failure path, since retrying is exactly the right recovery for a transient 401 too (caller already
  has an expired-token refresh path elsewhere, e.g. `live_streams_view.py`'s
  `_handle_expired_token`).

## Components

### Shared `ChatClient` constructor shape

`chat_overlay.py` picks a class (`irc.ChatClient` or `eventsub.ChatClient`) based on
`settings.chat_engine` and constructs it without needing to know which one it got - so both classes
now accept the **same keyword surface**, each ignoring the arguments it doesn't need:

```python
def __init__(self, channel_login, access_token=None, client_id=None, broadcaster_user_id=None,
             user_id=None, socket_factory=None, sleep_fn=None, **kwargs):
```

`irc.ChatClient` gains `access_token=None, client_id=None, broadcaster_user_id=None, user_id=None`
as accepted-but-unused keyword params (it stays anonymous internally - this is purely so the caller
doesn't need an `if engine == ...` branch at construction time). `eventsub.ChatClient` requires
`access_token`, `client_id`, and `broadcaster_user_id` to be non-`None` at `connect()` time (raises
`ValueError` immediately, not after spawning the background thread, if any are missing - a
programmer error in the caller, not a runtime condition worth a reconnect loop) and defaults
`user_id` from... no, `user_id` has no sane default, so `chat_overlay.py`/`player.py` are
responsible for always supplying it when `chat_engine == "eventsub"` (see "player.py" below).

### `lib/twitch/eventsub.py` (new, alongside `lib/twitch/irc.py`)

Stays pure Python - **no `xbmc*` imports** (enforced by `tests/test_architecture.py`, unchanged).
May import `requests` (for the Helix subscribe call) and `lib.twitch.api` - both already xbmc-free.

```python
class ChatClient:
    def __init__(self, channel_login, access_token=None, client_id=None, broadcaster_user_id=None,
                 user_id=None, socket_factory=None, sleep_fn=None, create_subscription_fn=None):
        """channel_login: kept only for logging/parity with irc.ChatClient - EventSub itself
          subscribes by ID, not login.
        access_token, client_id, broadcaster_user_id, user_id: required (raises ValueError from
          connect() if any is None) - see "Shared ChatClient constructor shape" above for why
          they're still keyword/defaultable at the signature level.
        socket_factory: callable() -> object with connect/recv/sendall/close, defaults to a real
          TLS-wrapped socket.socket to eventsub.wss.twitch.tv:443. Injectable for tests.
        sleep_fn: callable(seconds), defaults to time.sleep. Injectable for backoff tests.
        create_subscription_fn: callable(access_token, client_id, session_id, sub_type, condition),
          defaults to api.create_eventsub_subscription. Injectable for tests."""

    def connect(self):
        """Spawns the background thread and returns immediately."""

    def read_messages(self):
        """Generator: pops events off the internal queue.Queue and yields them. Same shape/behavior
        as irc.ChatClient.read_messages - short poll timeout, stops once disconnect() has been
        called and the queue is drained."""

    def disconnect(self):
        """Sets the internal cancel_event, closes the socket, joins the background thread."""
```

Internal background-thread loop (`_run`), same skeleton as `irc.py`'s:
1. Open a TLS connection to `eventsub.wss.twitch.tv:443` via `socket_factory()`.
2. Perform the WebSocket opening handshake (`_ws_handshake`): send an HTTP `GET /ws` upgrade
   request with a random `Sec-WebSocket-Key`, read the HTTP response, verify `101` status and that
   `Sec-WebSocket-Accept` matches the expected computed value (RFC 6455 §1.3). Handshake failure
   raises, caught by `_run`'s existing try/except, triggering backoff-retry like any other connect
   failure.
3. Read frames (`_read_ws_frame`) until a text frame arrives; parse it as JSON. Expect
   `session_welcome`; extract `payload.session.id` and `payload.session.keepalive_timeout_seconds`.
4. Call `create_subscription_fn` twice (`channel.chat.message`, `channel.raid`) with that session id.
   Either call raising/failing is treated as a connect failure (caught, logged via a `"raw"` event
   passthrough is NOT appropriate here since there's no line to pass through - instead re-raise to
   let `_run`'s existing except-and-backoff handle it).
5. Push `{"type": "status", "state": "connected"}` onto the queue.
6. Loop: read a WS frame, decode its JSON payload, dispatch on `payload["metadata"]["message_type"]`:
   - `"session_keepalive"` → update `last_message_at`, nothing queued.
   - `"notification"` → dispatch on `payload["metadata"]["subscription_type"]`:
     - `"channel.chat.message"` → queue `{"type": "message", "username":
       event["chatter_user_login"], "display_name": event["chatter_user_name"], "text":
       event["message"]["text"], "timestamp": <parsed from payload["metadata"]["message_timestamp"],
       an RFC3339 string - converted to ms epoch int>}`.
     - `"channel.raid"` → queue `{"type": "raid", "from_channel": event["from_broadcaster_user_login"],
       "display_name": event["from_broadcaster_user_name"], "viewer_count": event["viewers"],
       "timestamp": <same timestamp parsing>}`.
     - anything else → queue `{"type": "raw", "line": <raw JSON text>}` (parity with IRC's
       passthrough-everything-unrecognized behavior).
   - `"session_reconnect"` → raise a dedicated internal exception to force the outer loop to
     reconnect from scratch (see "session_reconnect" scope decision above) rather than following
     Twitch's dual-connection handoff.
   - a WS-level ping frame (opcode `0x9`, handled below `_read_ws_frame`, not at the JSON layer) →
     reply with a masked pong frame directly on the socket, not surfaced to the queue (mirrors IRC's
     `PING`/`PONG` handling).
   - if `time.time() - last_message_at > 2 * keepalive_timeout_seconds` → raise, triggering
     reconnect (checked on each read-loop iteration via the socket's recv timeout, not a separate
     timer thread).
7. On any error (socket, JSON, handshake, subscription-create, stall) and the loop isn't cancelled:
   push `{"type": "status", "state": "disconnected"}`, sleep via `sleep_fn(backoff)`, increase
   backoff exactly as `irc.py` does, go back to step 1.
8. Loop exits only when `cancel_event.is_set()` (set by `disconnect()`).

### WebSocket primitives (module-level functions, no `ChatClient` needed to test)

- `_build_handshake_request(host, path, key)` → raw HTTP request bytes.
- `_parse_handshake_response(raw_bytes, key)` → `True`/raises `ConnectionError` with a diagnostic
  message on non-101 status or `Sec-WebSocket-Accept` mismatch.
- `_encode_client_frame(payload_bytes, opcode)` → masked WS frame bytes (client→server frames MUST
  be masked per RFC 6455 §5.1; this client never sends anything except pong control frames, so only
  small payloads need supporting - no need to implement frame fragmentation on the send side).
- `_decode_frame(buffer)` → `(frame_or_None, remaining_buffer)`, handling short/extended/64-bit
  payload lengths and unmasked server→client frames (servers never mask). Returns `None` for the
  frame half of the tuple when the buffer doesn't yet contain a complete frame, so the read loop's
  buffering logic mirrors `irc.py`'s `\r\n`-line buffering.

### `lib/twitch/api.py` (additions)

```python
def get_user_by_login(access_token, client_id, login):
    """Return {"id", "login", "display_name"} for the given login name, or None if no such user
    (Twitch returns an empty data list rather than a 404)."""

def create_eventsub_subscription(access_token, client_id, session_id, sub_type, condition, version="1"):
    """POST /helix/eventsub/subscriptions with transport {method: websocket, session_id}. Raises
    requests.HTTPError (via response.raise_for_status()) on failure - unlike this module's other
    best-effort-on-decoration functions, a failed chat subscription is not decoration, so the
    caller (eventsub.ChatClient._run) needs to see the failure and go through its existing
    backoff-retry path rather than silently returning an empty/None result."""
```

### `lib/twitch/auth.py`

`SCOPES = ["user:read:follows", "user:read:chat"]` - added unconditionally (every new/refreshed
login gets the scope, whether or not that user ever turns on `chat_engine=eventsub`; simpler than
conditionally requesting scopes per-setting, and an unused granted scope is harmless).

### `lib/settings.py`

```python
VALID_CHAT_ENGINES = ("irc", "eventsub")
DEFAULT_CHAT_ENGINE = "irc"

# Settings class gains:
@property
def chat_engine(self):
    value = self._addon.getSetting("chat_engine")
    if value in VALID_CHAT_ENGINES:
        return value
    return DEFAULT_CHAT_ENGINE
```

`resources/settings.xml` gains a `chat_engine` string-list setting (same `<control type="list"
format="string"/>` + `<options>` shape as the existing `chat_display_mode` setting), and
`resources/language/resource.language.en_gb/strings.po` gains the label/option/help strings
(`#30014`-`#30016`, next free ids after the existing `#30013`).

### `lib/windows/chat_overlay.py`

No rendering changes. `ChatOverlay.__init__`/`onInit` gain the additional constructor args
(`access_token=None`, `client_id=None`, `broadcaster_user_id=None`, `user_id=None`, alongside the
existing `channel`/`chat_client_cls`) and forward all of them to `chat_client_cls(...)` - which
class that is (`irc.ChatClient` vs `eventsub.ChatClient`) is decided by the caller (`player.py`), not
by `ChatOverlay` itself, per the shared constructor shape above. `chat_client_cls` stays an
injectable constructor arg for tests, unchanged in spirit.

### `lib/windows/player.py`

`play_stream` gains `access_token=None`, `client_id=None` parameters (currently has neither - only
`settings`). New helper `_chat_client_cls_for_engine(engine)` returns `irc.ChatClient` or
`eventsub.ChatClient` (module-level constant map, not an if/else repeated at each call site).
Before constructing `ChatOverlay`, when `settings.chat_engine == "eventsub"`:
1. Resolve `broadcaster_user_id = api.get_user_by_login(access_token, client_id, channel)["id"]`.
   On `None`/any failure, log and fall back to the `irc` engine for this session rather than
   skipping chat entirely (a stream can still show *some* chat, and this is exactly the recovery
   path an unscoped/expired token needs - see "Auth" above) - `chat_engine="eventsub"` is a
   preference, not a hard requirement.
2. Otherwise pass `access_token`, `client_id`, `broadcaster_user_id`, and `token["user_id"]` (the
   token owner's own numeric id, already cached at login) through to `ChatOverlay`'s constructor
   alongside `chat_client_cls=eventsub.ChatClient`.

When `settings.chat_engine == "irc"` (the default) or the eventsub fallback above triggered,
`play_stream` behaves exactly as it does today: `chat_client_cls=irc.ChatClient`, no token/id
plumbing needed.

`play_stream` itself doesn't have `token`/`client_id` today, so its three callers
(`search_view.py:118`, `discover_view.py:275`, `live_streams_view.py:335`) are updated to pass
`token["access_token"]`, `client_id` through - each already has both in scope at its call site
(from `auth.load_token(addon)` / `addon.getSetting("client_id")`, used earlier in the same view
method for its own Helix calls).

## Data flow

```
consumer.connect()
  -> spawns background thread
     -> TLS connect to eventsub.wss.twitch.tv:443
     -> WS opening handshake (HTTP upgrade, verify 101 + Sec-WebSocket-Accept)
     -> read frames until session_welcome -> extract session_id, keepalive_timeout_seconds
     -> POST /helix/eventsub/subscriptions x2 (channel.chat.message, channel.raid)
     -> queue: {"type": "status", "state": "connected"}
     -> loop: read WS frame -> decode JSON
          ping frame -> reply pong directly (not queued)
          session_keepalive -> update last_message_at, not queued
          notification/channel.chat.message -> queue: {"type": "message", ...}
          notification/channel.raid -> queue: {"type": "raid", ...}
          notification/other -> queue: {"type": "raw", "line": ...}
          session_reconnect -> raise -> reconnect from scratch
          stall (no message within 2x keepalive timeout) -> raise -> reconnect
        on any error -> queue: {"type": "status", "state": "disconnected"}
                      -> backoff sleep -> reconnect (repeat until cancelled)
consumer.read_messages()  # generator, drains the queue - unchanged from irc.py
consumer.disconnect()  # cancel_event.set(), close socket, join thread - unchanged from irc.py
```

## Error handling

Same posture as `irc.py`: transient failures (socket errors, handshake failures, subscription-create
failures, JSON decode errors, stalls) are all recoverable and funnel into the existing
backoff-reconnect loop rather than raising to the consumer. `disconnect()` stays idempotent.
Malformed/unrecognized JSON payloads fall through to the `"raw"` passthrough case where structurally
possible (valid JSON, unrecognized `message_type`/`subscription_type`) or are treated as a decode
error triggering reconnect where not (invalid JSON entirely) - a genuinely malformed frame from
Twitch is different from IRC's "one weird but well-formed line", so reconnecting is the safer default
here rather than guessing at a partial parse.

## Testing

`tests/twitch/test_eventsub.py` (new, modeled on `test_irc.py`, which is untouched):

- **WS primitive unit tests** (no threading, no sockets): `_build_handshake_request` produces a
  well-formed upgrade request with a valid base64 `Sec-WebSocket-Key`; `_parse_handshake_response`
  accepts a correct `101` response and raises on a `200`/missing-`Accept`/mismatched-`Accept`
  response; `_encode_client_frame`/`_decode_frame` round-trip small and boundary-length (125, 126,
  65536 byte) text payloads.
- **JSON event-mapping unit tests** (no threading, no sockets): realistic captured-shape
  `session_welcome`, `channel.chat.message` notification, `channel.raid` notification,
  `session_keepalive`, an unrecognized notification subtype (→ raw), and a `session_reconnect`
  message each map to the right internal outcome.
- **`ChatClient` threaded-loop tests** via an injected fake socket (canned `recv()` byte chunks
  covering a full WS handshake + welcome + notification frames) and a fake
  `create_subscription_fn` (records calls, can be made to raise):
  - connecting performs the WS handshake, then calls `create_subscription_fn` for both
    `channel.chat.message` and `channel.raid` with the right condition dicts, before any
    `"connected"` status is queued.
  - a `channel.chat.message` notification frame results in the right `"message"` event.
  - a `channel.raid` notification frame results in the right `"raid"` event.
  - a WS ping frame results in a masked pong frame being sent and is not yielded from
    `read_messages()`.
  - `create_subscription_fn` raising results in a `"disconnected"` status event and a retry
    (via injected `sleep_fn`, same backoff-assertion style as the old IRC tests).
  - a `session_reconnect` message results in a full reconnect (new handshake + new
    subscriptions), not a raise to the consumer.
  - simulating a stalled connection (no frames within `2 * keepalive_timeout_seconds`, using an
    injected `time_fn`) results in a `"disconnected"` status event and reconnect.
  - `disconnect()` stops the background thread promptly and is safe to call twice.
- `tests/test_architecture.py`: no changes needed - `eventsub.py` still imports no `xbmc*` modules.
- `tests/twitch/test_api.py`: add cases for `get_user_by_login` (found/not-found) and
  `create_eventsub_subscription` (success, raises on non-200).
- `tests/windows/test_chat_overlay.py`: update `ChatOverlay(...)` construction/`FakeChatClient` to
  accept the new optional constructor args (default `None`, matching production); assert they're
  forwarded to `chat_client_cls(...)` unchanged, since rendering logic itself isn't touched.
- `tests/windows/test_player.py`: add cases for `chat_engine="eventsub"` (right `chat_client_cls`,
  right ids/token passed to `ChatOverlay`) and for the "ID resolution fails, falls back to irc
  engine" path, alongside the existing `chat_engine="irc"`/default tests (unchanged - still
  construct `irc.ChatClient` with no token/id args, exactly as today).
- `tests/settings/test_settings.py` (or wherever `test_settings.py` lives - confirm at
  implementation time): add cases for `chat_engine` mirroring the existing `chat_display_mode`
  tests (valid value round-trips, invalid/empty value falls back to `DEFAULT_CHAT_ENGINE`).
- No test hits Twitch's real EventSub/Helix endpoints.

## Out of scope for this task

- Zero-downtime `session_reconnect` handling (dual-connection handoff) - accepted simplification,
  see "Reconnect" above.
- Emote/badge/fragment rendering (EventSub's `message.fragments` carries structured emote/mention
  data IRC never had) - `chat_overlay.py` still renders plain wrapped text; a richer-rendering
  follow-up can consume `fragments` later without touching the transport again.
- Raid-*following* behavior (auto-switching playback) - unchanged from the IRC-era backlog item,
  still a separate follow-up; this task only preserves the existing `"raid"` event shape, now
  from either engine.
- `lib/windows/chat_window.py` (standalone full-screen chat) - still a stub, untouched by this task
  same as it was untouched by the original IRC client task.
- Removing `lib/twitch/irc.py` - explicitly staying, as the default engine (see "Selectable, not a
  replacement" above). Revisit only if EventSub proves reliable enough in practice that anonymous
  IRC stops earning its keep as a fallback - not part of this task.
