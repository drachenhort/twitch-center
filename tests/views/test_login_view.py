import threading
from unittest.mock import MagicMock, patch

import xbmcgui

from lib.views.login_view import LoginView


class FakeWindow:
    def __init__(self):
        self._controls = {}

    def getControl(self, control_id):
        from xbmcgui import FakeListControl

        if control_id not in self._controls:
            self._controls[control_id] = FakeListControl()
        return self._controls[control_id]


def test_on_code_sets_code_and_url_labels():
    win = LoginView(FakeWindow(), closed_event=threading.Event())
    win._cancel_event = threading.Event()
    win._on_code(win._cancel_event, "ABCD-1234", "https://www.twitch.tv/activate")
    assert win.window.getControl(LoginView.CODE_LABEL_ID).getLabel() == "ABCD-1234"
    assert win.window.getControl(LoginView.URL_LABEL_ID).getLabel() == "https://www.twitch.tv/activate"


def test_on_status_sets_status_label_text():
    win = LoginView(FakeWindow(), closed_event=threading.Event())
    win._cancel_event = threading.Event()
    win._on_status(win._cancel_event, "pending")
    assert win.window.getControl(LoginView.STATUS_LABEL_ID).getLabel() == "Waiting for authorization..."


def test_on_status_success_sets_login_succeeded_flag():
    # LoginView doesn't open Home itself - _on_status runs on the
    # background polling thread, so it just flags success and lib.main.run()
    # (on the main thread) does the actual handoff. See test_main.py.
    win = LoginView(FakeWindow(), closed_event=threading.Event())
    win._cancel_event = threading.Event()
    win._on_status(win._cancel_event, "success")
    assert win.login_succeeded is True
    assert not win.closed_event.is_set()


def test_on_code_does_nothing_when_cancelled():
    win = LoginView(FakeWindow(), closed_event=threading.Event())
    win._cancel_event = threading.Event()
    win._cancel_event.set()
    win._on_code(win._cancel_event, "ABCD-1234", "https://www.twitch.tv/activate")
    # No control was touched - getControl would lazily create a blank one,
    # so its label staying empty demonstrates _on_code short-circuited.
    assert win.window.getControl(LoginView.CODE_LABEL_ID).getLabel() == ""


def test_on_status_does_nothing_when_cancelled():
    win = LoginView(FakeWindow(), closed_event=threading.Event())
    win._cancel_event = threading.Event()
    win._cancel_event.set()
    win._on_status(win._cancel_event, "success")
    assert win.login_succeeded is False
    assert win.window.getControl(LoginView.STATUS_LABEL_ID).getLabel() == ""


def test_on_action_back_is_a_no_op_pass_through():
    # Back is handled centrally by MainWindow now - LoginView.handle_action
    # has nothing left to do for it.
    win = LoginView(FakeWindow(), closed_event=threading.Event())
    win._cancel_event = threading.Event()
    win.handle_action(xbmcgui.Action(xbmcgui.ACTION_NAV_BACK))
    assert not win._cancel_event.is_set()


def test_on_action_unrelated_key_does_nothing():
    win = LoginView(FakeWindow(), closed_event=threading.Event())
    win._cancel_event = threading.Event()
    with patch.object(win, "stop") as mock_stop:
        win.handle_action(xbmcgui.Action(999))
    assert not win._cancel_event.is_set()
    mock_stop.assert_not_called()


def test_activate_starts_background_thread_with_run_device_code_login():
    from lib.twitch import auth

    with patch("lib.views.login_view.threading.Thread") as mock_thread_cls:
        win = LoginView(FakeWindow(), closed_event=threading.Event())
        win.activate()
    mock_thread_cls.assert_called_once()
    call_kwargs = mock_thread_cls.call_args.kwargs
    assert call_kwargs["target"] is auth.run_device_code_login
    assert call_kwargs["kwargs"]["client_id"] == ""
    assert call_kwargs["kwargs"]["scopes"] == auth.SCOPES
    mock_thread_cls.return_value.start.assert_called_once()


def test_activate_is_idempotent_when_thread_already_running():
    with patch("lib.views.login_view.threading.Thread") as mock_thread_cls:
        mock_thread_cls.return_value.is_alive.return_value = True
        win = LoginView(FakeWindow(), closed_event=threading.Event())
        win.activate()
        win.activate()
    mock_thread_cls.assert_called_once()


def test_activate_starts_new_thread_if_previous_thread_finished():
    with patch("lib.views.login_view.threading.Thread") as mock_thread_cls:
        first_thread = MagicMock()
        first_thread.is_alive.return_value = False
        second_thread = MagicMock()
        mock_thread_cls.side_effect = [first_thread, second_thread]

        win = LoginView(FakeWindow(), closed_event=threading.Event())
        win.activate()
        win.activate()
    assert mock_thread_cls.call_count == 2
    second_thread.start.assert_called_once()


def test_activate_starts_a_fresh_login_flow_on_a_second_visit():
    # LoginView is constructed once and reused for the whole session, so
    # "Log in again" after an earlier successful login has to start a
    # genuinely fresh device-code flow. MainWindow calls stop() when it
    # navigates away, which is what marks the previous visit as finished.
    with patch("lib.views.login_view.threading.Thread") as mock_thread_cls:
        first_thread = MagicMock()
        first_thread.is_alive.return_value = True  # still polling when we leave
        second_thread = MagicMock()
        mock_thread_cls.side_effect = [first_thread, second_thread]

        win = LoginView(FakeWindow(), closed_event=threading.Event())
        win.activate()
        win._on_status(win._cancel_event, "success")
        assert win.login_succeeded is True

        # User leaves Login (MainWindow._switch_view) and comes back later.
        win.stop()
        win.activate()

    assert mock_thread_cls.call_count == 2
    second_thread.start.assert_called_once()
    # A fresh flow means the stale success flag is cleared, and the new
    # thread gets a fresh (un-cancelled) cancel event so its callbacks land.
    assert win.login_succeeded is False
    assert not win._cancel_event.is_set()
    assert mock_thread_cls.call_args.kwargs["kwargs"]["cancel_event"] is win._cancel_event


def test_activate_does_not_restart_after_success_even_if_reactivated():
    # Kodi can re-fire onInit/activation on the still-current Login view
    # even after _on_status("success") has flagged the handoff and the
    # polling thread has finished (is_alive() would be False by then) - the
    # thread-liveness check alone isn't enough to stop a second device-code
    # request from starting on an already-completed login. This guard is
    # scoped to the CURRENT visit only; see
    # test_activate_starts_a_fresh_login_flow_on_a_second_visit.
    win = LoginView(FakeWindow(), closed_event=threading.Event())
    win._cancel_event = threading.Event()
    win._on_status(win._cancel_event, "success")

    with patch("lib.views.login_view.threading.Thread") as mock_thread_cls:
        win.activate()
    mock_thread_cls.assert_not_called()


def test_stale_thread_callbacks_are_ignored_after_a_second_activate():
    # Regression test: a first flow's background thread can still be
    # winding down (its on_code/on_status callbacks about to fire) when the
    # user backs out and re-enters Login, triggering a second activate().
    # activate() rebinds self._cancel_event to a brand-new Event for the
    # second flow - if the first flow's callbacks checked self._cancel_event
    # (the mutable instance attribute) instead of the event THEY were
    # started with, they'd see the new, un-cancelled event and write stale
    # data (an old code, or a stale status) over the fresh login screen.
    with patch("lib.views.login_view.threading.Thread") as mock_thread_cls:
        first_thread = MagicMock()
        first_thread.is_alive.return_value = True  # still winding down
        second_thread = MagicMock()
        mock_thread_cls.side_effect = [first_thread, second_thread]

        win = LoginView(FakeWindow(), closed_event=threading.Event())

        # First flow starts.
        win.activate()
        first_kwargs = mock_thread_cls.call_args.kwargs["kwargs"]
        first_on_code = first_kwargs["on_code"]
        first_on_status = first_kwargs["on_status"]

        # User leaves Login (MainWindow._switch_view calls stop(), setting
        # the first flow's cancel event) and comes back, starting a second,
        # independent flow. The first thread hasn't actually died yet
        # (is_alive() still True), mirroring a real still-winding-down
        # thread.
        win.stop()
        win.activate()
        second_kwargs = mock_thread_cls.call_args.kwargs["kwargs"]
        second_on_code = second_kwargs["on_code"]
        second_on_status = second_kwargs["on_status"]

    # The first flow's own callbacks fire late, after the second flow is
    # already under way. They must recognize THEIR OWN cancellation and do
    # nothing - not read the (now different) self._cancel_event.
    first_on_code("STALE-CODE", "https://stale.example/activate")
    first_on_status("error")
    assert win.window.getControl(LoginView.CODE_LABEL_ID).getLabel() == ""
    assert win.window.getControl(LoginView.URL_LABEL_ID).getLabel() == ""
    assert win.window.getControl(LoginView.STATUS_LABEL_ID).getLabel() == ""

    # The second (current) flow's callbacks must still work normally.
    second_on_code("FRESH-CODE", "https://fresh.example/activate")
    second_on_status("pending")
    assert win.window.getControl(LoginView.CODE_LABEL_ID).getLabel() == "FRESH-CODE"
    assert win.window.getControl(LoginView.URL_LABEL_ID).getLabel() == "https://fresh.example/activate"
    assert win.window.getControl(LoginView.STATUS_LABEL_ID).getLabel() == "Waiting for authorization..."
