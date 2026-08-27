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
        self.live_notify_verbose_logging = addon.getSettingBool("live_notify_verbose_logging")


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


def test_initial_connect_load_token_error_is_caught_and_retried(monkeypatch):
    """A transient error from auth.load_token during the initial-connect tick must not
    propagate out of run() — the loop should survive and connect successfully on a later
    tick once load_token stops raising."""
    FakeClient.instances.clear()
    calls = {"n": 0}

    def load_token(addon):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("network blip")
        return {"access_token": "t", "user_id": "1", "client_id": "cid"}

    monkeypatch.setattr(live_notify_service.auth, "load_token", load_token)
    monkeypatch.setattr(
        live_notify_service.api, "get_followed_channels", lambda *a, **kw: [{"broadcaster_id": "111"}]
    )
    addon = FakeAddon({"live_notify_enabled": "true"})
    monitor = FakeMonitor(ticks=3)
    live_notify_service.run(
        addon=addon, monitor_cls=lambda: monitor, client_cls=FakeClient, settings_cls=FakeSettings
    )
    assert len(FakeClient.instances) == 1
    assert FakeClient.instances[0].connected is True


def test_initial_connect_get_followed_channels_error_is_caught_and_retried(monkeypatch):
    """A transient error from api.get_followed_channels during the initial-connect tick
    must not propagate out of run() either, and a later tick should still succeed."""
    FakeClient.instances.clear()
    monkeypatch.setattr(
        live_notify_service.auth,
        "load_token",
        lambda addon: {"access_token": "t", "user_id": "1", "client_id": "cid"},
    )
    calls = {"n": 0}

    def get_followed_channels(*a, **kw):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("transient Helix failure")
        return [{"broadcaster_id": "111"}]

    monkeypatch.setattr(live_notify_service.api, "get_followed_channels", get_followed_channels)
    addon = FakeAddon({"live_notify_enabled": "true"})
    monitor = FakeMonitor(ticks=3)
    live_notify_service.run(
        addon=addon, monitor_cls=lambda: monitor, client_cls=FakeClient, settings_cls=FakeSettings
    )
    # The first attempt constructs a client, connects it, then fails while fetching the
    # followed list; the loop must survive that and try again fresh on the next tick,
    # succeeding with a second client instance. The first (now-orphaned) client must have
    # been disconnected rather than leaked with a live background thread/socket - Critical 2.
    assert len(FakeClient.instances) == 2
    assert FakeClient.instances[0].disconnected is True
    assert FakeClient.instances[-1].connected is True
    assert FakeClient.instances[-1].broadcaster_calls == [["111"]]


def test_follow_refresh_error_does_not_disconnect_running_client(monkeypatch):
    """A transient error during the periodic follow-refresh (auth.load_token or
    api.get_followed_channels raising) must not tear down the already-connected client —
    the spec says don't drop an established WS session over a transient Helix failure."""
    FakeClient.instances.clear()
    # Force a follow-refresh check on every tick instead of every 10.
    monkeypatch.setattr(live_notify_service, "_FOLLOW_REFRESH_INTERVAL_SECONDS", 60)

    calls = {"n": 0}

    def load_token(addon):
        calls["n"] += 1
        if calls["n"] == 1:
            return {"access_token": "t", "user_id": "1", "client_id": "cid"}
        raise RuntimeError("network blip")

    monkeypatch.setattr(live_notify_service.auth, "load_token", load_token)
    monkeypatch.setattr(
        live_notify_service.api, "get_followed_channels", lambda *a, **kw: [{"broadcaster_id": "111"}]
    )
    addon = FakeAddon({"live_notify_enabled": "true"})
    monitor = FakeMonitor(ticks=3)
    live_notify_service.run(
        addon=addon, monitor_cls=lambda: monitor, client_cls=FakeClient, settings_cls=FakeSettings
    )
    # No reconnect/replacement client was created despite the follow-refresh errors, and
    # only the initial connect's set_broadcasters call went through.
    assert len(FakeClient.instances) == 1
    assert FakeClient.instances[0].broadcaster_calls == [["111"]]


def test_initial_connect_token_expired_refreshes_and_retries_next_tick(monkeypatch):
    """Important 3: api.TokenExpiredError during the initial-connect tick must trigger a
    refresh+save (mirroring lib/views/discover_view.py's pattern), leaving the leaked client
    disconnected (Critical 2) and running=None so the next tick picks up the freshly-saved
    token and succeeds."""
    FakeClient.instances.clear()
    calls = {"n": 0}
    saved = {}

    def load_token(addon):
        calls["n"] += 1
        if calls["n"] == 1:
            return {
                "access_token": "old", "refresh_token": "r", "user_id": "1",
                "login": "u", "display_name": "U",
            }
        return dict(saved)

    def get_followed_channels(access_token, client_id, user_id):
        if access_token == "old":
            raise live_notify_service.api.TokenExpiredError()
        return [{"broadcaster_id": "111"}]

    def refresh_access_token(client_id, refresh_token, on_error=None):
        return {"access_token": "new", "refresh_token": "r2"}

    def save_token(token, addon):
        saved.clear()
        saved.update(token)

    monkeypatch.setattr(live_notify_service.auth, "load_token", load_token)
    monkeypatch.setattr(live_notify_service.api, "get_followed_channels", get_followed_channels)
    monkeypatch.setattr(live_notify_service.auth, "refresh_access_token", refresh_access_token)
    monkeypatch.setattr(live_notify_service.auth, "save_token", save_token)

    addon = FakeAddon({"live_notify_enabled": "true"})
    monitor = FakeMonitor(ticks=3)
    live_notify_service.run(
        addon=addon, monitor_cls=lambda: monitor, client_cls=FakeClient, settings_cls=FakeSettings
    )

    assert saved.get("access_token") == "new"
    assert saved.get("user_id") == "1"  # preserved from the expired token, per discover_view's pattern
    assert len(FakeClient.instances) == 2
    assert FakeClient.instances[0].disconnected is True  # the leaked pre-refresh client
    assert FakeClient.instances[-1].connected is True
    assert FakeClient.instances[-1].broadcaster_calls == [["111"]]


def test_follow_refresh_token_expired_tears_down_for_reconnect_next_tick(monkeypatch):
    """Important 3: TokenExpiredError during the periodic follow-refresh path must refresh+save
    the token, then tear down the running client (LiveNotifyClient has no access-token setter)
    so the next tick reconnects fresh with the already-saved refreshed token."""
    FakeClient.instances.clear()
    monkeypatch.setattr(live_notify_service, "_FOLLOW_REFRESH_INTERVAL_SECONDS", 60)

    saved = {}
    calls = {"n": 0}

    def load_token(addon):
        if saved:
            return dict(saved)
        return {
            "access_token": "old", "refresh_token": "r", "user_id": "1",
            "login": "u", "display_name": "U",
        }

    def get_followed_channels(access_token, client_id, user_id):
        calls["n"] += 1
        # Succeeds the first time (initial connect, tick1), then the token "expires" for the
        # follow-refresh check (tick2) - simulating a token going stale mid-session.
        if calls["n"] == 1:
            return [{"broadcaster_id": "111"}]
        if access_token == "old":
            raise live_notify_service.api.TokenExpiredError()
        return [{"broadcaster_id": "111"}]

    def refresh_access_token(client_id, refresh_token, on_error=None):
        return {"access_token": "new", "refresh_token": "r2"}

    def save_token(token, addon):
        saved.update(token)

    monkeypatch.setattr(live_notify_service.auth, "load_token", load_token)
    monkeypatch.setattr(live_notify_service.api, "get_followed_channels", get_followed_channels)
    monkeypatch.setattr(live_notify_service.auth, "refresh_access_token", refresh_access_token)
    monkeypatch.setattr(live_notify_service.auth, "save_token", save_token)

    addon = FakeAddon({"live_notify_enabled": "true"})
    monitor = FakeMonitor(ticks=3)
    live_notify_service.run(
        addon=addon, monitor_cls=lambda: monitor, client_cls=FakeClient, settings_cls=FakeSettings
    )

    # tick1: initial connect succeeds. tick2: follow-refresh hits TokenExpiredError, refreshes
    # + saves, then tears the running client down. tick3: reconnects with a fresh client.
    assert saved.get("access_token") == "new"
    assert len(FakeClient.instances) == 2
    assert FakeClient.instances[0].disconnected is True
    assert FakeClient.instances[-1].connected is True


def test_initial_connect_missing_user_id_skips_without_connecting(monkeypatch):
    """Important 4: a legacy token saved before user_id was added to the login flow must not
    reach client.connect() - it lacks what _followed_broadcaster_ids needs and would otherwise
    KeyError, get swallowed by the generic except, and retry forever."""
    FakeClient.instances.clear()
    monkeypatch.setattr(live_notify_service.auth, "load_token", lambda addon: {"access_token": "t"})
    addon = FakeAddon({"live_notify_enabled": "true"})
    monitor = FakeMonitor(ticks=2)
    live_notify_service.run(
        addon=addon, monitor_cls=lambda: monitor, client_cls=FakeClient, settings_cls=FakeSettings
    )
    assert FakeClient.instances == []


def test_follow_refresh_missing_user_id_skips_without_crashing(monkeypatch):
    """Important 4, follow-refresh path: same legacy-token guard applies there too."""
    FakeClient.instances.clear()
    monkeypatch.setattr(live_notify_service, "_FOLLOW_REFRESH_INTERVAL_SECONDS", 60)
    calls = {"n": 0}

    def load_token(addon):
        calls["n"] += 1
        if calls["n"] == 1:
            return {"access_token": "t", "user_id": "1"}
        return {"access_token": "t"}  # legacy token missing user_id from here on

    monkeypatch.setattr(live_notify_service.auth, "load_token", load_token)
    monkeypatch.setattr(
        live_notify_service.api, "get_followed_channels", lambda *a, **kw: [{"broadcaster_id": "111"}]
    )
    addon = FakeAddon({"live_notify_enabled": "true"})
    monitor = FakeMonitor(ticks=3)
    live_notify_service.run(
        addon=addon, monitor_cls=lambda: monitor, client_cls=FakeClient, settings_cls=FakeSettings
    )
    # No second/replacement client was constructed - the missing-user_id token was skipped
    # rather than crashing or triggering a reconnect. (The single instance is disconnected only
    # as part of normal service shutdown when the monitor aborts, not by the refresh logic.)
    assert len(FakeClient.instances) == 1


def test_status_and_subscription_error_events_are_logged(monkeypatch):
    """Important 5: status/disconnected and subscription_error events drained from the running
    client must be logged (the only diagnostics this feature produces), not dropped."""
    FakeClient.instances.clear()
    monkeypatch.setattr(live_notify_service.auth, "load_token", lambda addon: {"access_token": "t", "user_id": "1"})
    monkeypatch.setattr(
        live_notify_service.api, "get_followed_channels", lambda *a, **kw: [{"broadcaster_id": "111"}]
    )

    logs = []
    monkeypatch.setattr(live_notify_service.xbmc, "log", lambda msg, level=None: logs.append(msg))

    class EmittingClient(FakeClient):
        def connect(self):
            super().connect()
            self.push_event({"type": "status", "state": "disconnected", "error": "boom"})
            self.push_event({"type": "subscription_error", "broadcaster_user_id": "111", "error": "boom"})

    addon = FakeAddon({"live_notify_enabled": "true", "live_notify_verbose_logging": "true"})
    monitor = FakeMonitor(ticks=3)
    live_notify_service.run(
        addon=addon, monitor_cls=lambda: monitor, client_cls=EmittingClient, settings_cls=FakeSettings
    )

    assert any("disconnected" in m for m in logs)
    assert any("subscription_error" in m for m in logs)


def test_status_events_not_logged_when_verbose_logging_disabled(monkeypatch):
    """The new live_notify_verbose_logging setting defaults off - status/subscription_error
    events must not be logged unless it's explicitly enabled."""
    FakeClient.instances.clear()
    monkeypatch.setattr(live_notify_service.auth, "load_token", lambda addon: {"access_token": "t", "user_id": "1"})
    monkeypatch.setattr(
        live_notify_service.api, "get_followed_channels", lambda *a, **kw: [{"broadcaster_id": "111"}]
    )

    logs = []
    monkeypatch.setattr(live_notify_service.xbmc, "log", lambda msg, level=None: logs.append(msg))

    class EmittingClient(FakeClient):
        def connect(self):
            super().connect()
            self.push_event({"type": "status", "state": "disconnected", "error": "boom"})

    addon = FakeAddon({"live_notify_enabled": "true"})  # verbose logging left at its false default
    monitor = FakeMonitor(ticks=3)
    live_notify_service.run(
        addon=addon, monitor_cls=lambda: monitor, client_cls=EmittingClient, settings_cls=FakeSettings
    )

    assert not any("disconnected" in m for m in logs)


def test_subscribed_channels_logged_only_when_verbose_logging_enabled(monkeypatch):
    FakeClient.instances.clear()
    monkeypatch.setattr(live_notify_service.auth, "load_token", lambda addon: {"access_token": "t", "user_id": "1"})
    monkeypatch.setattr(
        live_notify_service.api, "get_followed_channels",
        lambda *a, **kw: [{"broadcaster_id": "111", "broadcaster_login": "aerospacenews"}],
    )

    logs = []
    monkeypatch.setattr(live_notify_service.xbmc, "log", lambda msg, level=None: logs.append(msg))

    addon = FakeAddon({"live_notify_enabled": "true", "live_notify_verbose_logging": "true"})
    monitor = FakeMonitor(ticks=2)
    live_notify_service.run(
        addon=addon, monitor_cls=lambda: monitor, client_cls=FakeClient, settings_cls=FakeSettings
    )

    assert any("aerospacenews" in m for m in logs)
