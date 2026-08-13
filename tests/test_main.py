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
    def waitForAbort(self, timeout=None):
        raise AssertionError("waitForAbort should not be called when closed_event is already set")


class FakeMainWindow:
    instances = []

    def __init__(self, xml_filename, script_path, *args, initial_view="login", closed_event=None, **kwargs):
        self.xml_filename = xml_filename
        self.script_path = script_path
        self.initial_view = initial_view
        self.shown = False
        self.close_calls = 0
        self.closed_event = closed_event or threading.Event()
        self.closed_event.set()  # already-closed: run()'s loop exits immediately
        self._views = {"login": _FakeView()}
        FakeMainWindow.instances.append(self)

    def show(self):
        self.shown = True

    def close(self):
        self.close_calls += 1


class _FakeView:
    login_succeeded = False


def test_run_shows_login_view_first_when_no_token_saved():
    FakeMainWindow.instances.clear()
    main.run([], addon=FakeAddon(token=None), main_window_cls=FakeMainWindow, monitor_cls=FakeMonitor)
    assert len(FakeMainWindow.instances) == 1
    assert FakeMainWindow.instances[0].initial_view == "login"
    assert FakeMainWindow.instances[0].shown is True


def test_run_shows_menu_view_first_when_token_saved():
    FakeMainWindow.instances.clear()
    main.run(
        [], addon=FakeAddon(token={"access_token": "tok"}), main_window_cls=FakeMainWindow, monitor_cls=FakeMonitor
    )
    assert FakeMainWindow.instances[0].initial_view == "menu"


def test_run_blocks_until_closed_event_is_set():
    class SlowCloseFakeMainWindow(FakeMainWindow):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.closed_event = threading.Event()

    class TickingMonitor:
        def __init__(self):
            self.calls = 0

        def waitForAbort(self, timeout=None):
            self.calls += 1
            if self.calls >= 2:
                FakeMainWindow.instances[-1].closed_event.set()
            return False

    FakeMainWindow.instances.clear()
    main.run(
        [],
        addon=FakeAddon(token=None),
        main_window_cls=SlowCloseFakeMainWindow,
        monitor_cls=TickingMonitor,
    )
    assert FakeMainWindow.instances[-1].closed_event.is_set()


def test_run_switches_to_menu_when_login_succeeded_flag_is_set():
    FakeMainWindow.instances.clear()

    class FlaggingView:
        login_succeeded = True

    class FlaggingMainWindow(FakeMainWindow):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.closed_event = threading.Event()
            self._views = {"login": FlaggingView()}
            self.switched_to = []

        def _switch_view(self, name):
            self.switched_to.append(name)

    class TickingMonitor:
        def __init__(self):
            self.calls = 0

        def waitForAbort(self, timeout=None):
            self.calls += 1
            if self.calls >= 2:
                FakeMainWindow.instances[-1].closed_event.set()
            return False

    main.run(
        [], addon=FakeAddon(token=None), main_window_cls=FlaggingMainWindow, monitor_cls=TickingMonitor
    )
    assert FakeMainWindow.instances[-1].switched_to == ["menu"]


def test_run_switches_to_menu_again_after_a_second_login():
    # LoginView is reused for the whole session, so "Log in again" ->
    # successful login has to hand off to Menu a second time. run() must not
    # latch "already switched once"; it clears the flag instead.
    FakeMainWindow.instances.clear()

    class FlaggingView:
        def __init__(self):
            self.login_succeeded = True

    class FlaggingMainWindow(FakeMainWindow):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.closed_event = threading.Event()
            self._views = {"login": FlaggingView()}
            self.switched_to = []

        def _switch_view(self, name):
            self.switched_to.append(name)

    class TickingMonitor:
        def __init__(self):
            self.calls = 0

        def waitForAbort(self, timeout=None):
            self.calls += 1
            window = FakeMainWindow.instances[-1]
            if self.calls == 2:
                # Second successful login, on the same reused LoginView.
                window._views["login"].login_succeeded = True
            elif self.calls >= 3:
                window.closed_event.set()
            return False

    main.run(
        [], addon=FakeAddon(token=None), main_window_cls=FlaggingMainWindow, monitor_cls=TickingMonitor
    )
    assert FakeMainWindow.instances[-1].switched_to == ["menu", "menu"]


def test_run_prompts_before_quit_and_exits_when_confirmed():
    FakeMainWindow.instances.clear()

    class QuittingMainWindow(FakeMainWindow):
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
                FakeMainWindow.instances[-1].closed_event.quit_requested = True
            return False

    prompts = []
    original_prompt = main.show_quit_prompt
    main.show_quit_prompt = lambda: prompts.append(True) or True
    try:
        main.run(
            [],
            addon=FakeAddon(token={"access_token": "tok"}),
            main_window_cls=QuittingMainWindow,
            monitor_cls=TickingMonitor,
        )
    finally:
        main.show_quit_prompt = original_prompt

    assert len(prompts) == 1
    assert FakeMainWindow.instances[0].closed_event.is_set()
    # Kodi tears the script down after run() returns, but the window was
    # shown non-modally with show() - close it explicitly rather than
    # relying on that teardown to reclaim it.
    assert FakeMainWindow.instances[0].close_calls == 1


def test_run_does_not_quit_when_user_cancels_prompt():
    FakeMainWindow.instances.clear()

    class QuittingMainWindow(FakeMainWindow):
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
                FakeMainWindow.instances[-1].closed_event.quit_requested = True
            elif self.calls >= 3:
                FakeMainWindow.instances[-1].closed_event.set()
            return False

    prompts = []
    original_prompt = main.show_quit_prompt
    main.show_quit_prompt = lambda: prompts.append(True) or False
    try:
        main.run(
            [],
            addon=FakeAddon(token={"access_token": "tok"}),
            main_window_cls=QuittingMainWindow,
            monitor_cls=TickingMonitor,
        )
    finally:
        main.show_quit_prompt = original_prompt

    assert len(prompts) == 1
    assert FakeMainWindow.instances[0].closed_event.is_set()
    assert not getattr(FakeMainWindow.instances[0].closed_event, "quit_requested", False)
