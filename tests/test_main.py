import threading

from lib import main


class FakeAddon:
    def __init__(self, token=None):
        self._token = token

    def getSetting(self, id):
        if id == "twitch_token":
            return '{"access_token": "tok"}' if self._token else ""
        return ""

    def getAddonInfo(self, id):
        if id == "path":
            return "/fake/addon/path"
        return ""


class FakeMonitor:
    """Fake xbmc.Monitor whose waitForAbort would never be called in these
    tests, since the fake windows' closed_event is already set - if it ever
    is called, blow up loudly instead of sleeping in real time."""

    def waitForAbort(self, timeout=None):
        raise AssertionError("waitForAbort should not be called when closed_event is already set")


class FakeWindow:
    def __init__(self, xml_filename, script_path, *args, **kwargs):
        self.xml_filename = xml_filename
        self.script_path = script_path
        self.shown = False
        # Already-closed, so main.run's wait loop exits immediately without
        # sleeping or blocking real test time.
        self.closed_event = threading.Event()
        self.closed_event.set()

    def show(self):
        self.shown = True


class FakeLoginWindow(FakeWindow):
    instances = []

    def __init__(self, xml_filename, script_path, *args, **kwargs):
        super().__init__(xml_filename, script_path, *args, **kwargs)
        FakeLoginWindow.instances.append(self)


class FakeHomeWindow(FakeWindow):
    instances = []

    def __init__(self, xml_filename, script_path, *args, **kwargs):
        super().__init__(xml_filename, script_path, *args, **kwargs)
        FakeHomeWindow.instances.append(self)


def test_run_opens_login_window_when_no_token_saved():
    FakeLoginWindow.instances.clear()
    FakeHomeWindow.instances.clear()
    main.run(
        [],
        addon=FakeAddon(token=None),
        login_window_cls=FakeLoginWindow,
        home_window_cls=FakeHomeWindow,
        monitor_cls=FakeMonitor,
    )
    assert len(FakeLoginWindow.instances) == 1
    assert FakeLoginWindow.instances[0].shown is True
    assert len(FakeHomeWindow.instances) == 0


def test_run_blocks_until_window_closed_event_is_set():
    """Simulates the window closing after a couple of monitor ticks, proving
    run() waits on closed_event via the monitor loop rather than returning
    the instant show() is called."""
    windows = []

    class SlowCloseFakeWindow(FakeWindow):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.closed_event = threading.Event()
            windows.append(self)

    class TickingMonitor:
        def __init__(self):
            self.calls = 0

        def waitForAbort(self, timeout=None):
            self.calls += 1
            if self.calls >= 2:
                windows[-1].closed_event.set()
            return False

    monitors = []

    def monitor_cls():
        monitor = TickingMonitor()
        monitors.append(monitor)
        return monitor

    main.run(
        [],
        addon=FakeAddon(token=None),
        login_window_cls=SlowCloseFakeWindow,
        home_window_cls=FakeHomeWindow,
        monitor_cls=monitor_cls,
    )

    assert monitors[-1].calls == 2
    assert windows[-1].closed_event.is_set()


def test_run_opens_home_window_when_token_saved():
    FakeLoginWindow.instances.clear()
    FakeHomeWindow.instances.clear()
    main.run(
        [],
        addon=FakeAddon(token={"access_token": "tok"}),
        login_window_cls=FakeLoginWindow,
        home_window_cls=FakeHomeWindow,
        monitor_cls=FakeMonitor,
    )
    assert len(FakeHomeWindow.instances) == 1
    assert FakeHomeWindow.instances[0].shown is True
    assert len(FakeLoginWindow.instances) == 0


def test_run_keeps_waiting_while_a_child_window_owns_the_shared_event():
    """A window that hands off to another (Home -> Discover) must not end
    run()'s wait loop; only the window that actually closes for real does."""
    windows = []

    class HandOffWindow(FakeWindow):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.closed_event = threading.Event()
            windows.append(self)

    class TickingMonitor:
        def __init__(self):
            self.calls = 0

        def waitForAbort(self, timeout=None):
            self.calls += 1
            if self.calls == 2:
                # Parent "hands off": closes itself but passes its event on to
                # a child window without setting it.
                child = HandOffWindow("child.xml", "/fake/addon/path")
                child.closed_event = windows[0].closed_event
                child.show()
            elif self.calls >= 4:
                # The child finally closes for real.
                windows[-1].closed_event.set()
            return False

    monitors = []

    def monitor_cls():
        monitor = TickingMonitor()
        monitors.append(monitor)
        return monitor

    main.run(
        [],
        addon=FakeAddon(token={"access_token": "tok"}),
        login_window_cls=FakeLoginWindow,
        home_window_cls=HandOffWindow,
        monitor_cls=monitor_cls,
    )

    assert monitors[-1].calls == 4
    assert windows[0].closed_event.is_set()
