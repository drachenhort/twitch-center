# Live-Go Notifications for Followed Twitch Channels Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Show a Kodi notification when a followed Twitch channel goes live, via a new opt-in background service.

**Architecture:** A new `xbmc.service` addon component (`lib/live_notify_service.py`) runs alongside the existing `xbmc.python.script` entry point. It polls a settings toggle, and when enabled, drives a new `LiveNotifyClient` (added to `lib/twitch/eventsub.py`, reusing that module's WebSocket framing helpers) that opens one EventSub WebSocket subscribed to `stream.online` for every followed broadcaster, and diffs the followed-channel list periodically to keep subscriptions current.

**Tech Stack:** Python 3, Kodi `xbmc`/`xbmcaddon`/`xbmcgui` stubs (pytest), `requests`, Twitch Helix + EventSub WebSocket APIs.

**Spec:** `docs/superpowers/specs/2026-08-26-live-go-notifications-design.md`

## Global Constraints

- Twitch only — no Kick in this feature.
- Notification is text-only (`xbmcgui.Dialog().notification(...)`) — no click-through action.
- New setting `live_notify_enabled` defaults to `false` (opt-in).
- `lib/twitch/*`, `lib/kick/*`, and `lib/providers.py` must never import `xbmc*` modules (enforced by `tests/test_architecture.py`) — `LiveNotifyClient` goes in `lib/twitch/eventsub.py` and stays free of them; `lib/live_notify_service.py` is the one file allowed to import `xbmc*` for this feature, mirroring `lib/main.py`.
- Follow this repo's changelog/versioning convention: bump `addon.xml` version and add a `CHANGELOG.md` + `addon.xml` `<news>` entry for this feature (see Task 5).

---

### Task 1: `delete_eventsub_subscription` Helix helper

**Files:**
- Modify: `lib/twitch/api.py` (add function after `create_eventsub_subscription`, currently ending around line 155)
- Test: `tests/twitch/test_api.py`

**Interfaces:**
- Produces: `delete_eventsub_subscription(access_token, client_id, subscription_id)` — `DELETE /helix/eventsub/subscriptions?id=<subscription_id>`. Raises `requests.HTTPError` on failure (same "not decoration" reasoning as `create_eventsub_subscription`— a caller that thinks it removed a subscription needs to know if it didn't). Returns `None` on success (Twitch returns 204 No Content).

- [ ] **Step 1: Write the failing test**

Add to `tests/twitch/test_api.py`:

```python
def test_delete_eventsub_subscription_sends_id_as_query_param():
    response = MagicMock()
    response.status_code = 204
    response.raise_for_status.side_effect = None
    with patch.object(api.requests, "delete", return_value=response) as mock_delete:
        result = api.delete_eventsub_subscription("token", "client-id", "sub-123")
    assert result is None
    assert mock_delete.call_args.kwargs["headers"]["Authorization"] == "Bearer token"
    assert mock_delete.call_args.kwargs["headers"]["Client-Id"] == "client-id"
    assert mock_delete.call_args.kwargs["params"] == {"id": "sub-123"}


def test_delete_eventsub_subscription_propagates_http_errors():
    response = MagicMock()
    response.status_code = 404
    response.raise_for_status.side_effect = requests.HTTPError(response=response)
    with patch.object(api.requests, "delete", return_value=response):
        with pytest.raises(requests.RequestException):
            api.delete_eventsub_subscription("token", "client-id", "sub-123")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/twitch/test_api.py -k delete_eventsub_subscription -v`
Expected: FAIL with `AttributeError: module 'lib.twitch.api' has no attribute 'delete_eventsub_subscription'`

- [ ] **Step 3: Write minimal implementation**

Add to `lib/twitch/api.py`, directly after `create_eventsub_subscription`:

```python
def delete_eventsub_subscription(access_token, client_id, subscription_id):
    """DELETE /helix/eventsub/subscriptions?id=... Raises requests.HTTPError on failure - same
    reasoning as create_eventsub_subscription: a caller relying on this to actually remove a
    stale subscription needs to see a failure, not a silently-ignored one."""
    response = requests.delete(
        HELIX_BASE + "/eventsub/subscriptions",
        headers=_headers(access_token, client_id),
        params={"id": subscription_id},
        timeout=10,
    )
    response.raise_for_status()
    return None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/twitch/test_api.py -k delete_eventsub_subscription -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add lib/twitch/api.py tests/twitch/test_api.py
git commit -m "Add delete_eventsub_subscription Helix helper"
```

---

### Task 2: `LiveNotifyClient` EventSub client

**Files:**
- Modify: `lib/twitch/eventsub.py` (add class at end of file, after `ChatClient`)
- Test: `tests/twitch/test_eventsub.py`

**Interfaces:**
- Consumes: `api.create_eventsub_subscription(access_token, client_id, session_id, sub_type, condition, version="1")` → dict with `["data"][0]["id"]` (Task 1's neighbor, already in `lib/twitch/api.py`); `api.delete_eventsub_subscription(access_token, client_id, subscription_id)` (Task 1).
- Produces: `LiveNotifyClient(access_token, client_id, socket_factory=None, sleep_fn=None, create_subscription_fn=None, delete_subscription_fn=None, time_fn=None)` with methods `connect()`, `set_broadcasters(broadcaster_user_ids)`, `read_events()` (generator yielding dicts), `disconnect()`.
  - Event shapes yielded by `read_events()`:
    - `{"type": "status", "state": "connected"}` / `{"type": "status", "state": "disconnected", "error": "..."}" (optional "error" key, same as `ChatClient`)
    - `{"type": "stream_online", "broadcaster_user_id": str, "broadcaster_user_login": str, "broadcaster_user_name": str}`

**Design notes for the implementer:**

`ChatClient` subscribes to exactly one broadcaster's two fixed subscription types inside `_handshake_and_subscribe`, called once per connection. `LiveNotifyClient` instead has a *settable* desired broadcaster set (`set_broadcasters`), which can change while connected. Keep this tractable:

- `self._lock = threading.Lock()` guards `self._desired_ids` (set of broadcaster_user_id strings), `self._session_id` (str or None — None means "no live session right now"), and `self._active_subs` (dict broadcaster_user_id → subscription_id, representing subscriptions that exist on the *current* session).
- On every new session (initial connect, and every reconnect after a drop), the background thread's handshake subscribes the *entire* current `self._desired_ids` from scratch (mirrors `ChatClient`'s pattern exactly — reconnecting naturally means re-subscribing everyone, since a new session has zero subscriptions). This makes reconnect handling trivial: no diffing needed there.
- `set_broadcasters(ids)` (called from the service's thread, not the background thread) updates `self._desired_ids`, and if a session is currently live (`self._session_id is not None`), diffs against `self._active_subs` and calls `create_subscription_fn`/`delete_subscription_fn` directly (synchronously, holding the lock for the diff bookkeeping but not for the network calls themselves — a slow HTTP call blocking the lock would also block the background thread from setting a fresh `self._session_id` after a reconnect race; this is an accepted YAGNI trade-off since this only runs on a ~10-minute cadence, not hot-path).
- Reuse `_BACKOFF_START`, `_BACKOFF_MAX`, `_BACKOFF_RESET_AFTER`, `_DISCONNECT_GRACE`, `_QUEUE_POLL_TIMEOUT`, `_QUEUE_MAXSIZE`, `_SOCKET_RECV_TIMEOUT`, `_REQUESTED_KEEPALIVE_SECONDS`, `_default_socket_factory`, and the module-level framing functions (`_build_handshake_key`, `_build_handshake_request`, `_parse_handshake_response`, `_encode_client_frame`, `_decode_frame`, `_parse_rfc3339_ms`) already in this file — do not duplicate them.
- Subscription type: `"stream.online"`, condition `{"broadcaster_user_id": <id>}`, version `"1"` (the default).

- [ ] **Step 1: Write the failing tests**

Add to `tests/twitch/test_eventsub.py` (reuses `FakeSocket`, `_server_text_frame`, `_handshake_response_bytes`, `_WELCOME` already defined in that file):

```python
from lib.twitch.eventsub import LiveNotifyClient


def _live_notify_kwargs(**overrides):
    kwargs = dict(
        access_token="tok",
        client_id="cid",
        sleep_fn=lambda s: None,
        create_subscription_fn=lambda *a, **kw: {"data": [{"id": "sub-" + a[4]["broadcaster_user_id"]}]},
        delete_subscription_fn=lambda *a, **kw: None,
    )
    kwargs.update(overrides)
    return kwargs


def _connectable_socket_factory():
    """Returns a socket_factory that completes the handshake with whatever key the client
    sends, then serves nothing further (idle connected session)."""
    def factory():
        fake = FakeSocket()

        def sendall(data):
            fake.sent.append(data)
            if data.startswith(b"GET "):
                text = data.decode("ascii")
                key_line = [l for l in text.split("\r\n") if l.startswith("Sec-WebSocket-Key:")][0]
                key = key_line.split(":", 1)[1].strip()
                fake._recv_queue.insert(0, _server_text_frame(_WELCOME))
                fake._recv_queue.insert(0, _handshake_response_bytes(key))

        fake.sendall = sendall
        return fake
    return factory


def test_live_notify_connect_with_no_desired_broadcasters_subscribes_nothing():
    subscribe_calls = []
    client = LiveNotifyClient(**_live_notify_kwargs(
        socket_factory=_connectable_socket_factory(),
        create_subscription_fn=lambda *a, **kw: subscribe_calls.append(a) or {"data": [{"id": "x"}]},
    ))
    client.connect()
    events = []
    for event in client.read_events():
        events.append(event)
        break
    client.disconnect()
    assert events[0] == {"type": "status", "state": "connected"}
    assert subscribe_calls == []


def test_live_notify_set_broadcasters_before_connect_subscribes_on_handshake():
    subscribe_calls = []

    def create_subscription_fn(access_token, client_id, session_id, sub_type, condition):
        subscribe_calls.append((sub_type, condition))
        return {"data": [{"id": "sub-" + condition["broadcaster_user_id"]}]}

    client = LiveNotifyClient(**_live_notify_kwargs(
        socket_factory=_connectable_socket_factory(),
        create_subscription_fn=create_subscription_fn,
    ))
    client.set_broadcasters(["111", "222"])
    client.connect()
    events = []
    for event in client.read_events():
        events.append(event)
        break
    client.disconnect()

    assert events[0] == {"type": "status", "state": "connected"}
    assert sorted(subscribe_calls) == [
        ("stream.online", {"broadcaster_user_id": "111"}),
        ("stream.online", {"broadcaster_user_id": "222"}),
    ]


def test_live_notify_set_broadcasters_after_connect_diffs_against_active():
    subscribe_calls = []
    delete_calls = []

    def create_subscription_fn(access_token, client_id, session_id, sub_type, condition):
        subscribe_calls.append(condition["broadcaster_user_id"])
        return {"data": [{"id": "sub-" + condition["broadcaster_user_id"]}]}

    def delete_subscription_fn(access_token, client_id, subscription_id):
        delete_calls.append(subscription_id)

    client = LiveNotifyClient(**_live_notify_kwargs(
        socket_factory=_connectable_socket_factory(),
        create_subscription_fn=create_subscription_fn,
        delete_subscription_fn=delete_subscription_fn,
    ))
    client.set_broadcasters(["111"])
    client.connect()
    for event in client.read_events():
        if event["type"] == "status" and event["state"] == "connected":
            break

    client.set_broadcasters(["222"])  # drop 111, add 222
    # give the (synchronous) diff a moment to run - set_broadcasters itself is synchronous,
    # no sleep needed, but assert immediately after the call returns
    client.disconnect()

    assert subscribe_calls == ["111", "222"]
    assert delete_calls == ["sub-111"]


def test_stream_online_notification_yields_stream_online_event():
    notification = {
        "metadata": {
            "message_type": "notification",
            "subscription_type": "stream.online",
            "message_timestamp": "2026-08-26T00:00:00Z",
        },
        "payload": {
            "event": {
                "broadcaster_user_id": "111",
                "broadcaster_user_login": "someuser",
                "broadcaster_user_name": "SomeUser",
            }
        },
    }

    def factory():
        fake = FakeSocket()

        def sendall(data):
            fake.sent.append(data)
            if data.startswith(b"GET "):
                text = data.decode("ascii")
                key_line = [l for l in text.split("\r\n") if l.startswith("Sec-WebSocket-Key:")][0]
                key = key_line.split(":", 1)[1].strip()
                fake._recv_queue.insert(0, _server_text_frame(notification))
                fake._recv_queue.insert(0, _server_text_frame(_WELCOME))
                fake._recv_queue.insert(0, _handshake_response_bytes(key))

        fake.sendall = sendall
        return fake

    client = LiveNotifyClient(**_live_notify_kwargs(socket_factory=factory))
    client.connect()
    events = []
    for event in client.read_events():
        events.append(event)
        if event["type"] == "stream_online":
            break
    client.disconnect()

    assert events[-1] == {
        "type": "stream_online",
        "broadcaster_user_id": "111",
        "broadcaster_user_login": "someuser",
        "broadcaster_user_name": "SomeUser",
    }
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/twitch/test_eventsub.py -k live_notify -v` and `pytest tests/twitch/test_eventsub.py -k stream_online -v`
Expected: FAIL with `ImportError: cannot import name 'LiveNotifyClient'`

- [ ] **Step 3: Write minimal implementation**

Add to `lib/twitch/eventsub.py`, after the end of `ChatClient`:

```python
class LiveNotifyClient:
    """EventSub client for stream.online notifications across an arbitrary, changeable set of
    broadcasters - unlike ChatClient, which is scoped to one broadcaster and two fixed
    subscription types. See docs/superpowers/specs/2026-08-26-live-go-notifications-design.md."""

    def __init__(self, access_token, client_id, socket_factory=None, sleep_fn=None,
                 create_subscription_fn=None, delete_subscription_fn=None, time_fn=None):
        self._access_token = access_token
        self._client_id = client_id
        self._socket_factory = socket_factory or _default_socket_factory
        self._sleep_fn = sleep_fn or time.sleep
        self._create_subscription_fn = create_subscription_fn or api.create_eventsub_subscription
        self._delete_subscription_fn = delete_subscription_fn or api.delete_eventsub_subscription
        self._time_fn = time_fn or time.time
        self._queue = Queue(maxsize=_QUEUE_MAXSIZE)
        self._cancel_event = threading.Event()
        self._thread = None
        self._sock = None
        self._recv_buffer = b""
        self._keepalive_timeout = _REQUESTED_KEEPALIVE_SECONDS
        self._last_message_at = 0

        self._lock = threading.Lock()
        self._desired_ids = set()
        self._session_id = None
        self._active_subs = {}  # broadcaster_user_id -> subscription_id

    def connect(self):
        if self._thread is not None and self._thread.is_alive():
            return
        self._cancel_event.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def set_broadcasters(self, broadcaster_user_ids):
        new_ids = set(broadcaster_user_ids)
        with self._lock:
            self._desired_ids = new_ids
            session_id = self._session_id
            if session_id is None:
                return
            to_add = new_ids - set(self._active_subs)
            to_remove = set(self._active_subs) - new_ids

        for broadcaster_id in to_add:
            body = self._create_subscription_fn(
                self._access_token, self._client_id, session_id, "stream.online",
                {"broadcaster_user_id": broadcaster_id},
            )
            with self._lock:
                if self._session_id == session_id:
                    self._active_subs[broadcaster_id] = body["data"][0]["id"]
        for broadcaster_id in to_remove:
            with self._lock:
                subscription_id = self._active_subs.pop(broadcaster_id, None)
            if subscription_id is not None:
                self._delete_subscription_fn(self._access_token, self._client_id, subscription_id)

    def read_events(self):
        while not (self._cancel_event.is_set() and self._queue.empty()):
            try:
                yield self._queue.get(timeout=_QUEUE_POLL_TIMEOUT)
            except Empty:
                continue

    def _enqueue(self, event):
        try:
            self._queue.put_nowait(event)
        except Full:
            try:
                self._queue.get_nowait()
            except Empty:
                pass
            self._queue.put_nowait(event)

    def disconnect(self):
        self._cancel_event.set()
        sock = self._sock
        if sock is not None:
            try:
                sock.close()
            except OSError:
                pass
        if self._thread is not None:
            self._thread.join(timeout=5)

    def _run(self):
        backoff = _BACKOFF_START
        while not self._cancel_event.is_set():
            connected_at = None
            self._recv_buffer = b""
            with self._lock:
                self._session_id = None
                self._active_subs = {}
            try:
                self._sock = self._socket_factory()
                self._handshake_and_subscribe()
                connected_at = time.time()
                self._enqueue({"type": "status", "state": "connected"})
                self._read_loop()
            except Exception as exc:
                last_error = repr(exc)
            else:
                last_error = None
            finally:
                with self._lock:
                    self._session_id = None
                if self._sock is not None:
                    try:
                        self._sock.close()
                    except OSError:
                        pass
                    self._sock = None

            if self._cancel_event.wait(_DISCONNECT_GRACE):
                break

            status_event = {"type": "status", "state": "disconnected"}
            if last_error is not None:
                status_event["error"] = last_error
            self._enqueue(status_event)
            if connected_at is not None and (time.time() - connected_at) > _BACKOFF_RESET_AFTER:
                backoff = _BACKOFF_START
            self._sleep_fn(backoff)
            backoff = min(backoff * 2, _BACKOFF_MAX)

    def _handshake_and_subscribe(self):
        key = _build_handshake_key()
        self._sock.sendall(_build_handshake_request(EVENTSUB_HOST, EVENTSUB_PATH, key))
        raw_response = self._read_handshake_response()
        _parse_handshake_response(raw_response, key)

        while True:
            frame = self._read_one_frame_blocking()
            if frame["opcode"] == _OPCODE_PING:
                self._sock.sendall(_encode_client_frame(frame["payload"], opcode=_OPCODE_PONG))
                continue
            if frame["opcode"] == _OPCODE_CLOSE:
                raise ConnectionError("EventSub server closed the connection")
            if frame["opcode"] != _OPCODE_TEXT:
                continue
            if not frame["fin"]:
                raise ConnectionError("EventSub: fragmented messages are not supported")
            payload = json.loads(frame["payload"].decode("utf-8"))
            if payload["metadata"]["message_type"] == "session_welcome":
                session = payload["payload"]["session"]
                session_id = session["id"]
                self._keepalive_timeout = session.get(
                    "keepalive_timeout_seconds", _REQUESTED_KEEPALIVE_SECONDS
                )
                break

        with self._lock:
            desired_ids = set(self._desired_ids)
        active_subs = {}
        for broadcaster_id in desired_ids:
            body = self._create_subscription_fn(
                self._access_token, self._client_id, session_id, "stream.online",
                {"broadcaster_user_id": broadcaster_id},
            )
            active_subs[broadcaster_id] = body["data"][0]["id"]
        with self._lock:
            self._session_id = session_id
            self._active_subs = active_subs
        self._last_message_at = self._time_fn()

    def _read_handshake_response(self):
        buffer = b""
        while b"\r\n\r\n" not in buffer:
            chunk = self._sock.recv(4096)
            if not chunk:
                raise ConnectionError("connection closed during handshake")
            buffer += chunk
        header_end = buffer.index(b"\r\n\r\n") + 4
        self._recv_buffer = buffer[header_end:]
        return buffer[:header_end].decode("iso-8859-1")

    def _recv_more(self):
        try:
            data = self._sock.recv(4096)
        except socket_module.timeout:
            if self._time_fn() - self._last_message_at > 2 * self._keepalive_timeout:
                raise ConnectionError("EventSub connection stalled: no messages received")
            return b""
        if not data:
            raise ConnectionError("connection closed by server")
        return data

    def _read_one_frame_blocking(self):
        while True:
            frame, self._recv_buffer = _decode_frame(self._recv_buffer)
            if frame is not None:
                return frame
            self._recv_buffer += self._recv_more()

    def _read_loop(self):
        while not self._cancel_event.is_set():
            frame = self._read_one_frame_blocking()
            self._last_message_at = self._time_fn()
            if frame["opcode"] == _OPCODE_PING:
                self._sock.sendall(_encode_client_frame(frame["payload"], opcode=_OPCODE_PONG))
                continue
            if frame["opcode"] == _OPCODE_CLOSE:
                raise ConnectionError("EventSub server closed the connection")
            if frame["opcode"] != _OPCODE_TEXT:
                continue
            if not frame["fin"]:
                raise ConnectionError("EventSub: fragmented messages are not supported")
            payload = json.loads(frame["payload"].decode("utf-8"))
            self._handle_payload(payload)

    def _handle_payload(self, payload):
        message_type = payload["metadata"]["message_type"]
        if message_type == "session_keepalive":
            return
        if message_type == "session_reconnect":
            raise ConnectionError("EventSub requested reconnect")
        if message_type != "notification":
            self._enqueue({"type": "raw", "line": json.dumps(payload)})
            return

        subscription_type = payload["metadata"]["subscription_type"]
        event = payload["payload"]["event"]
        if subscription_type == "stream.online":
            self._enqueue({
                "type": "stream_online",
                "broadcaster_user_id": event["broadcaster_user_id"],
                "broadcaster_user_login": event["broadcaster_user_login"],
                "broadcaster_user_name": event["broadcaster_user_name"],
            })
        else:
            self._enqueue({"type": "raw", "line": json.dumps(payload)})
```

Note: this duplicates several private methods verbatim from `ChatClient` (`_read_handshake_response`, `_recv_more`, `_read_one_frame_blocking`, `_read_loop`, the `_run` skeleton). This is intentional — extracting a shared base class isn't worth the indirection for two classes with different subscription-membership models (see spec's "Reconnect/backoff behavior... copied from ChatClient" note). Do not refactor this into a shared base as part of this task.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/twitch/test_eventsub.py -v`
Expected: PASS (all existing `ChatClient` tests plus the new `LiveNotifyClient` tests)

- [ ] **Step 5: Run the full test suite to confirm no architecture-boundary violation**

Run: `pytest tests/test_architecture.py -v`
Expected: PASS (`lib/twitch/eventsub.py` still has no `xbmc*` imports)

- [ ] **Step 6: Commit**

```bash
git add lib/twitch/eventsub.py tests/twitch/test_eventsub.py
git commit -m "Add LiveNotifyClient for stream.online EventSub notifications"
```

---

### Task 3: Settings toggle and service extension point

**Files:**
- Modify: `resources/settings.xml` (add setting inside `general` category's `group id="1"`, after the `skip_twitch_ads` setting block, around line 30-34)
- Modify: `resources/language/resource.language.en_gb/strings.po` (append after the `#30029` entry, around line 116)
- Modify: `addon.xml` (add `xbmc.service` extension point, after the existing `xbmc.python.script` extension)
- Modify: `lib/settings.py` (add `live_notify_enabled` property, after `skip_twitch_ads`)
- Test: `tests/test_addon_manifest.py`, `tests/test_settings.py`

**Interfaces:**
- Produces: setting id `live_notify_enabled` (boolean, default `false`); `Settings.live_notify_enabled` property; `addon.xml` extension point `xbmc.service` pointing at `lib/live_notify_service.py` (file created in Task 4 — this task only wires the manifest; Kodi does not require the target file to exist yet for XML parsing, and the test suite only checks the manifest, not that Kodi can import it).

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_addon_manifest.py`:

```python
def test_addon_xml_declares_service_extension():
    tree = ET.parse(ADDON_XML)
    root = tree.getroot()
    extensions = root.findall("extension")
    points = [ext.attrib.get("point") for ext in extensions]
    assert "xbmc.service" in points


def test_addon_xml_service_extension_targets_live_notify_service():
    tree = ET.parse(ADDON_XML)
    root = tree.getroot()
    service_ext = next(e for e in root.findall("extension") if e.attrib.get("point") == "xbmc.service")
    assert service_ext.attrib.get("library") == "lib/live_notify_service.py"


def test_settings_xml_declares_live_notify_enabled_defaulting_to_false():
    tree = ET.parse(SETTINGS_XML)
    root = tree.getroot()
    setting_ids = {s.attrib["id"]: s for s in root.iter("setting")}
    assert "live_notify_enabled" in setting_ids
    default = setting_ids["live_notify_enabled"].find("default")
    assert default is not None
    assert default.text == "false"
```

Add to `tests/test_settings.py` (matching the existing style — check the file first for the fake-addon fixture pattern used by `test_skip_twitch_ads`-style tests and follow it):

```python
def test_live_notify_enabled_reads_bool_setting():
    settings = Settings(addon=FakeAddon({"live_notify_enabled": "true"}))
    assert settings.live_notify_enabled is True
```

(If `tests/test_settings.py`'s `FakeAddon` takes a different construction shape than a single dict, match whatever `test_skip_twitch_ads`'s existing test uses instead of the snippet above — read that test first.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_addon_manifest.py tests/test_settings.py -k live_notify -v`
Expected: FAIL (setting/extension not found; `AttributeError` on `Settings.live_notify_enabled`)

- [ ] **Step 3: Write minimal implementation**

In `resources/settings.xml`, add immediately after the `skip_twitch_ads` setting block:

```xml
        <setting id="live_notify_enabled" type="boolean" label="30030">
          <level>0</level>
          <default>false</default>
          <control type="toggle"/>
        </setting>
```

In `resources/language/resource.language.en_gb/strings.po`, append after the `#30029` entry:

```
msgctxt "#30030"
msgid "Notify when followed streamers go live"
msgstr ""
```

In `addon.xml`, add after the existing `xbmc.python.script` extension block:

```xml
  <extension point="xbmc.service" library="lib/live_notify_service.py" start="startup"/>
```

In `lib/settings.py`, add after the `skip_twitch_ads` property:

```python
    @property
    def live_notify_enabled(self):
        return self._addon.getSettingBool("live_notify_enabled")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_addon_manifest.py tests/test_settings.py -v`
Expected: PASS (all manifest and settings tests)

- [ ] **Step 5: Commit**

```bash
git add resources/settings.xml resources/language/resource.language.en_gb/strings.po addon.xml lib/settings.py tests/test_addon_manifest.py tests/test_settings.py
git commit -m "Add live_notify_enabled setting and xbmc.service extension point"
```

---

### Task 4: `live_notify_service.py` background service loop

**Files:**
- Create: `lib/live_notify_service.py`
- Test: `tests/test_live_notify_service.py`

**Interfaces:**
- Consumes: `lib.twitch.auth.load_token(addon)` → dict or `None`; `lib.twitch.api.get_followed_channels(access_token, client_id, user_id)` → list of dicts with `broadcaster_id` (Task 2's `LiveNotifyClient` uses `broadcaster_user_id` as the dict key name in its own API — the service maps `channel["broadcaster_id"]` from `get_followed_channels` into the list passed to `set_broadcasters`); `LiveNotifyClient(access_token, client_id)` with `.connect()`, `.set_broadcasters(ids)`, `.read_events()`, `.disconnect()` (Task 2); `Settings(addon).live_notify_enabled` (Task 3); `xbmcgui.Dialog().notification(heading, message)`.
- Produces: `run(addon=None, monitor_cls=None, client_cls=None, settings_cls=None)` — the service's entry point, structured for injection the same way `lib/main.py::run()` is. Module-level `if __name__ == "__main__": run()` at the bottom, matching how Kodi invokes a service library directly.

**Design notes for the implementer:**

- This file is the one place besides `lib/main.py` (and `lib/windows/*`, `lib/player/audio.py`) allowed to import `xbmc*` — it lives outside `lib/twitch/`, `lib/kick/`, so `tests/test_architecture.py` doesn't restrict it.
- Kodi runs a service library's module top-level code once at Kodi startup, then expects it to either return quickly or run its own loop until `xbmc.Monitor.abortRequested()` — mirror `lib/main.py`'s `monitor_cls` injection pattern for testability.
- Loop shape: use `monitor.waitForAbort(timeout)` as the sleep primitive (it returns `True` immediately if Kodi is shutting down, `False` after `timeout` seconds otherwise — this is the idiomatic Kodi service loop, and the existing `tests/kodi_stubs/xbmc.py::Monitor.waitForAbort` already returns `False`, so tests can drive iteration count via a fake that returns `True` after N calls).
- Track `enabled` (from `settings.live_notify_enabled`), `client` (the running `LiveNotifyClient` or `None`), and a `next_follow_refresh_at` timestamp. Every loop tick (interval: use `_SETTING_POLL_INTERVAL_SECONDS = 60` as the `waitForAbort` timeout):
  1. Re-read `settings.live_notify_enabled`.
  2. If disabled and a client is running: `client.disconnect()`, `client = None`.
  3. If enabled and no client running: try `auth.load_token(addon)`; if `None`, skip this tick (retry next tick). Otherwise construct and `.connect()` a new client, immediately call `.set_broadcasters(...)` with the current followed list, and schedule the next follow-refresh.
  4. If enabled and a client is running: drain `client.read_events()` non-blockingly for this tick (bound the drain — see below) and call `xbmcgui.Dialog().notification("Twitch Center", "<name> is live")` for each `stream_online` event. If it's time for a follow-list refresh (10 minutes since the last one), re-fetch followed channels and call `set_broadcasters` again.
  5. On `monitor.abortRequested()` (checked via `waitForAbort`'s return value), disconnect any running client and exit the loop.
- `read_events()` is a blocking generator (`Queue.get(timeout=...)` internally) — draining it "for this tick" means iterating with a short per-call budget, not calling it in a way that blocks the whole service loop indefinitely. Use `client.read_events()`'s existing internal timeout behavior: since `_QUEUE_POLL_TIMEOUT` is 0.5s per `Empty` retry and the generator only stops yielding when `_cancel_event` is set, draining it directly in a `for` loop would block the service forever waiting for the *next* event. Instead, poll the client's internal queue with a non-blocking pattern: add a small helper on `LiveNotifyClient` is out of scope for this task (YAGNI — don't touch Task 2's class again). Instead, run the drain in a bounded loop using `itertools.islice` is not applicable to a blocking generator either — the correct approach: spawn `client.read_events()` consumption on its own dedicated thread inside the service (a `threading.Thread` that loops `for event in client.read_events(): out_queue.put(event)`), and have the main service loop only ever touch `out_queue.get_nowait()` in a `while True: try/except Empty: break` drain each tick. Use a plain `queue.Queue()` for `out_queue`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_live_notify_service.py`:

```python
import queue
import threading

from lib import live_notify_service


class FakeAddon:
    def __init__(self, settings=None):
        self._settings = settings or {}

    def getSetting(self, id):
        return self._settings.get(id, "")

    def getSettingBool(self, id):
        return self._settings.get(id, "false") == "true"

    def getAddonInfo(self, id):
        return ""


class FakeMonitor:
    """abortRequested() flips true after `ticks` calls to waitForAbort."""

    def __init__(self, ticks):
        self._remaining = ticks
        self.abort = False

    def waitForAbort(self, timeout=None):
        if self._remaining <= 0:
            self.abort = True
            return True
        self._remaining -= 1
        return False


class FakeSettings:
    def __init__(self, addon):
        self.live_notify_enabled = addon.getSettingBool("live_notify_enabled")


class FakeClient:
    instances = []

    def __init__(self, access_token, client_id):
        self.access_token = access_token
        self.client_id = client_id
        self.connected = False
        self.disconnected = False
        self.broadcaster_calls = []
        self._events = queue.Queue()
        FakeClient.instances.append(self)

    def connect(self):
        self.connected = True

    def set_broadcasters(self, ids):
        self.broadcaster_calls.append(list(ids))

    def push_event(self, event):
        self._events.put(event)

    def read_events(self):
        while True:
            yield self._events.get()

    def disconnect(self):
        self.disconnected = True


def test_disabled_by_default_never_constructs_a_client(monkeypatch):
    FakeClient.instances.clear()
    monkeypatch.setattr(live_notify_service.auth, "load_token", lambda addon: {"access_token": "t", "user_id": "1"})
    monkeypatch.setattr(live_notify_service.api, "get_followed_channels", lambda *a, **kw: [])
    addon = FakeAddon({"live_notify_enabled": "false"})
    monitor = FakeMonitor(ticks=2)
    live_notify_service.run(addon=addon, monitor_cls=lambda: monitor, client_cls=FakeClient, settings_cls=FakeSettings)
    assert FakeClient.instances == []


def test_enabled_with_token_connects_and_sets_initial_broadcasters(monkeypatch):
    FakeClient.instances.clear()
    monkeypatch.setattr(live_notify_service.auth, "load_token", lambda addon: {"access_token": "t", "user_id": "1", "client_id": "cid"})
    monkeypatch.setattr(
        live_notify_service.api, "get_followed_channels",
        lambda *a, **kw: [{"broadcaster_id": "111"}, {"broadcaster_id": "222"}],
    )
    addon = FakeAddon({"live_notify_enabled": "true"})
    monitor = FakeMonitor(ticks=2)
    live_notify_service.run(addon=addon, monitor_cls=lambda: monitor, client_cls=FakeClient, settings_cls=FakeSettings)
    assert len(FakeClient.instances) == 1
    client = FakeClient.instances[0]
    assert client.connected is True
    assert client.broadcaster_calls[0] == ["111", "222"]


def test_disabled_after_running_disconnects_client(monkeypatch):
    FakeClient.instances.clear()
    monkeypatch.setattr(live_notify_service.auth, "load_token", lambda addon: {"access_token": "t", "user_id": "1", "client_id": "cid"})
    monkeypatch.setattr(live_notify_service.api, "get_followed_channels", lambda *a, **kw: [])

    calls = {"n": 0}
    addon = FakeAddon({"live_notify_enabled": "true"})

    class TogglingAddon(FakeAddon):
        def getSettingBool(self, id):
            calls["n"] += 1
            return calls["n"] == 1  # enabled on first tick, disabled from then on

    monitor = FakeMonitor(ticks=3)
    live_notify_service.run(
        addon=TogglingAddon(), monitor_cls=lambda: monitor, client_cls=FakeClient, settings_cls=FakeSettings
    )
    assert len(FakeClient.instances) == 1
    assert FakeClient.instances[0].disconnected is True


def test_no_token_skips_connecting_but_does_not_crash(monkeypatch):
    FakeClient.instances.clear()
    monkeypatch.setattr(live_notify_service.auth, "load_token", lambda addon: None)
    addon = FakeAddon({"live_notify_enabled": "true"})
    monitor = FakeMonitor(ticks=2)
    live_notify_service.run(addon=addon, monitor_cls=lambda: monitor, client_cls=FakeClient, settings_cls=FakeSettings)
    assert FakeClient.instances == []


def test_stream_online_event_shows_notification(monkeypatch):
    FakeClient.instances.clear()
    monkeypatch.setattr(live_notify_service.auth, "load_token", lambda addon: {"access_token": "t", "user_id": "1", "client_id": "cid"})
    monkeypatch.setattr(live_notify_service.api, "get_followed_channels", lambda *a, **kw: [{"broadcaster_id": "111"}])

    notifications = []

    class FakeDialog:
        def notification(self, heading, message):
            notifications.append((heading, message))

    monkeypatch.setattr(live_notify_service.xbmcgui, "Dialog", lambda: FakeDialog())

    class EmittingClient(FakeClient):
        def connect(self):
            super().connect()
            self.push_event({
                "type": "stream_online",
                "broadcaster_user_id": "111",
                "broadcaster_user_login": "someuser",
                "broadcaster_user_name": "SomeUser",
            })

    addon = FakeAddon({"live_notify_enabled": "true"})
    monitor = FakeMonitor(ticks=3)
    live_notify_service.run(
        addon=addon, monitor_cls=lambda: monitor, client_cls=EmittingClient, settings_cls=FakeSettings
    )
    assert ("Twitch Center", "SomeUser is live") in notifications
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_live_notify_service.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'lib.live_notify_service'`

- [ ] **Step 3: Write minimal implementation**

Create `lib/live_notify_service.py`:

```python
"""Background service entry point, referenced by addon.xml's xbmc.service extension. Runs for
Kodi's whole lifetime; polls the live_notify_enabled setting and, when on, keeps a
LiveNotifyClient subscribed to stream.online for the user's followed Twitch channels."""
import os
import queue
import sys
import threading

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import xbmc
import xbmcaddon
import xbmcgui

from lib.settings import Settings
from lib.twitch import api, auth
from lib.twitch.eventsub import LiveNotifyClient

_SETTING_POLL_INTERVAL_SECONDS = 60
_FOLLOW_REFRESH_INTERVAL_SECONDS = 600


class _RunningClient:
    """Bundles a LiveNotifyClient with the dedicated thread that drains its blocking
    read_events() generator into a plain Queue the main service loop can poll non-blockingly."""

    def __init__(self, client):
        self.client = client
        self.events = queue.Queue()
        self._thread = threading.Thread(target=self._pump, daemon=True)
        self._thread.start()

    def _pump(self):
        for event in self.client.read_events():
            self.events.put(event)

    def drain(self):
        events = []
        while True:
            try:
                events.append(self.events.get_nowait())
            except queue.Empty:
                break
        return events

    def disconnect(self):
        self.client.disconnect()


def _followed_broadcaster_ids(token, client_id):
    channels = api.get_followed_channels(token["access_token"], client_id, token["user_id"])
    return [c["broadcaster_id"] for c in channels]


def run(addon=None, monitor_cls=None, client_cls=None, settings_cls=None):
    addon = addon or xbmcaddon.Addon()
    monitor_cls = monitor_cls or xbmc.Monitor
    client_cls = client_cls or LiveNotifyClient
    settings_cls = settings_cls or Settings

    monitor = monitor_cls()
    running = None  # _RunningClient or None
    ticks_since_follow_refresh = 0
    _TICKS_PER_FOLLOW_REFRESH = _FOLLOW_REFRESH_INTERVAL_SECONDS // _SETTING_POLL_INTERVAL_SECONDS

    while True:
        settings = settings_cls(addon)

        if not settings.live_notify_enabled and running is not None:
            running.disconnect()
            running = None

        elif settings.live_notify_enabled and running is None:
            token = auth.load_token(addon)
            if token is not None:
                client_id = token.get("client_id") or addon.getSetting("client_id")
                client = client_cls(token["access_token"], client_id)
                client.connect()
                client.set_broadcasters(_followed_broadcaster_ids(token, client_id))
                running = _RunningClient(client)
                ticks_since_follow_refresh = 0

        elif settings.live_notify_enabled and running is not None:
            for event in running.drain():
                if event.get("type") == "stream_online":
                    xbmcgui.Dialog().notification(
                        "Twitch Center", "%s is live" % event["broadcaster_user_name"]
                    )
            ticks_since_follow_refresh += 1
            if ticks_since_follow_refresh >= _TICKS_PER_FOLLOW_REFRESH:
                ticks_since_follow_refresh = 0
                token = auth.load_token(addon)
                if token is not None:
                    client_id = token.get("client_id") or addon.getSetting("client_id")
                    running.client.set_broadcasters(_followed_broadcaster_ids(token, client_id))

        if monitor.waitForAbort(_SETTING_POLL_INTERVAL_SECONDS):
            if running is not None:
                running.disconnect()
            break


if __name__ == "__main__":
    run()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_live_notify_service.py -v`
Expected: PASS (all 5 tests)

- [ ] **Step 5: Run the full suite**

Run: `pytest -v`
Expected: PASS, no regressions in any other test file (in particular `tests/test_architecture.py`, `tests/test_addon_manifest.py`, `tests/twitch/`, `tests/test_settings.py`)

- [ ] **Step 6: Commit**

```bash
git add lib/live_notify_service.py tests/test_live_notify_service.py
git commit -m "Add live-go notification background service"
```

---

### Task 5: Changelog and version bump

**Files:**
- Modify: `addon.xml` (bump `version` attribute on the `addon` root element, add a `<news>` entry)
- Modify: `CHANGELOG.md`

**Interfaces:** None — documentation/metadata only.

- [ ] **Step 1: Check the current version**

Run: `grep 'addon id="script.twitch.center"' addon.xml`

Note the current version (e.g. `0.25.5`) and bump the minor version per this repo's convention (new feature → minor bump), e.g. `0.26.0`.

- [ ] **Step 2: Update `addon.xml`**

Update the `version` attribute on the root `<addon>` element to the new version. Add a new `<news>` entry at the top of the `<news>` block (before the existing `v0.21.0:` entry), e.g.:

```
      v0.26.0: Added an opt-in background notification for followed Twitch channels going live -
      enable "Notify when followed streamers go live" in Settings. Runs as a new Kodi background
      service (separate from the existing on-demand addon window), using one EventSub WebSocket
      subscribed to your followed channels' stream.online events. Off by default. Twitch only for
      now.
```

- [ ] **Step 3: Update `CHANGELOG.md`**

Read `CHANGELOG.md`'s existing entry format first (check the top few entries for the exact heading/bullet style used), then add a new top entry for this version following that same format, describing: new opt-in setting, new background service, EventSub-based (instant, not polling), Twitch-only.

- [ ] **Step 4: Verify the manifest still parses and the version bump test (if any) passes**

Run: `pytest tests/test_addon_manifest.py tests/test_build_zip.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add addon.xml CHANGELOG.md
git commit -m "Bump version to 0.26.0 for live-go notification feature"
```

---

## Manual verification (not automated — do after Task 5)

Per this repo's live-testing conventions: do a clean Kodi restart before testing (not a re-run of the addon), enable the new setting, confirm via Kodi's log that the service starts, follow a channel that's about to go live (or use a test broadcaster), and confirm the notification appears without the Twitch Center window being open. This step is out of scope for the automated task list above — flag it to the user rather than attempting it as part of plan execution, since it requires real Kodi hardware and a live Twitch stream.
