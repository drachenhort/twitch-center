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
        self.received_closed_event = kwargs.get("closed_event")
        # Already-closed, so main.run's wait loop exits immediately without
        # sleeping or blocking real test time.
        self.closed_event = threading.Event()
        self.closed_event.set()

    def show(self):
        self.shown = True

    def close(self):
        pass


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


def test_run_opens_home_window_on_main_thread_when_login_succeeded_flag_is_set():
    """LoginWindow can't open Home itself (its success callback runs on a
    background thread), so it just sets login_succeeded and main.run()'s
    (main-thread) wait loop performs the actual handoff."""
    FakeLoginWindow.instances.clear()
    FakeHomeWindow.instances.clear()

    class FlaggingLoginWindow(FakeLoginWindow):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.closed_event = threading.Event()
            self.login_succeeded = False

    class TickingMonitor:
        def __init__(self):
            self.calls = 0

        def waitForAbort(self, timeout=None):
            self.calls += 1
            if self.calls == 1:
                FakeLoginWindow.instances[-1].login_succeeded = True
            elif self.calls >= 2:
                FakeHomeWindow.instances[-1].closed_event.set()
            return False

    main.run(
        [],
        addon=FakeAddon(token=None),
        login_window_cls=FlaggingLoginWindow,
        home_window_cls=FakeHomeWindow,
        monitor_cls=TickingMonitor,
    )

    assert len(FakeHomeWindow.instances) == 1
    assert FakeHomeWindow.instances[0].shown is True
    assert FakeHomeWindow.instances[0].received_closed_event is FakeLoginWindow.instances[0].closed_event


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


def test_run_prompts_before_quit_and_exits_when_confirmed():
    FakeHomeWindow.instances.clear()

    class QuittingHomeWindow(FakeHomeWindow):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.closed_event = threading.Event()
            self.closed_event.quit_requested = False

    class TickingMonitor:
        def __init__(self):
            self.calls = 0

        def waitForAbort(self, timeout=None):
            self.calls += 1
            if self.calls == 1:
                FakeHomeWindow.instances[-1].closed_event.quit_requested = True
            return False

    prompts = []
    original_prompt = main.show_quit_prompt
    main.show_quit_prompt = lambda: prompts.append(True) or True
    try:
        main.run(
            [],
            addon=FakeAddon(token={"access_token": "tok"}),
            login_window_cls=FakeLoginWindow,
            home_window_cls=QuittingHomeWindow,
            monitor_cls=TickingMonitor,
        )
    finally:
        main.show_quit_prompt = original_prompt

    assert len(prompts) == 1
    assert len(FakeHomeWindow.instances) == 1
    assert FakeHomeWindow.instances[0].closed_event.is_set()


def test_run_does_not_quit_when_user_cancels_prompt():
    FakeHomeWindow.instances.clear()

    class QuittingHomeWindow(FakeHomeWindow):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.closed_event = threading.Event()
            self.closed_event.quit_requested = False

    class TickingMonitor:
        def __init__(self):
            self.calls = 0

        def waitForAbort(self, timeout=None):
            self.calls += 1
            if self.calls == 1:
                FakeHomeWindow.instances[-1].closed_event.quit_requested = True
            elif self.calls >= 3:
                FakeHomeWindow.instances[-1].closed_event.set()
            return False

    prompts = []
    original_prompt = main.show_quit_prompt
    main.show_quit_prompt = lambda: prompts.append(True) or False
    try:
        main.run(
            [],
            addon=FakeAddon(token={"access_token": "tok"}),
            login_window_cls=FakeLoginWindow,
            home_window_cls=QuittingHomeWindow,
            monitor_cls=TickingMonitor,
        )
    finally:
        main.show_quit_prompt = original_prompt

    assert len(prompts) == 1
    assert FakeHomeWindow.instances[0].closed_event.is_set()
    assert not getattr(FakeHomeWindow.instances[0].closed_event, "quit_requested", False)
