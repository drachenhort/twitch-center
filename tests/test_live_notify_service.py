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
    # succeeding with a second client instance.
    assert len(FakeClient.instances) == 2
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
