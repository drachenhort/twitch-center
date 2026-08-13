import threading
from unittest.mock import MagicMock, patch

import xbmcgui

from lib.views.login_view import LoginView


class FakeWindow:
    def __init__(self):
        self._controls = {}

    def getControl(self, control_id):
        from xbmcgui import ControlLabel

        if control_id not in self._controls:
            self._controls[control_id] = ControlLabel()
        return self._controls[control_id]


def test_on_code_sets_code_and_url_labels():
    win = LoginView(FakeWindow(), closed_event=threading.Event())
    win._cancel_event = threading.Event()
    win._on_code("ABCD-1234", "https://www.twitch.tv/activate")
    assert win.window.getControl(LoginView.CODE_LABEL_ID).getLabel() == "ABCD-1234"
    assert win.window.getControl(LoginView.URL_LABEL_ID).getLabel() == "https://www.twitch.tv/activate"


def test_on_status_sets_status_label_text():
    win = LoginView(FakeWindow(), closed_event=threading.Event())
    win._cancel_event = threading.Event()
    win._on_status("pending")
    assert win.window.getControl(LoginView.STATUS_LABEL_ID).getLabel() == "Waiting for authorization..."


def test_on_status_success_sets_login_succeeded_flag():
    # LoginView doesn't open Home itself - _on_status runs on the
    # background polling thread, so it just flags success and lib.main.run()
    # (on the main thread) does the actual handoff. See test_main.py.
    win = LoginView(FakeWindow(), closed_event=threading.Event())
    win._cancel_event = threading.Event()
    win._on_status("success")
    assert win.login_succeeded is True
    assert not win.closed_event.is_set()


def test_on_code_does_nothing_when_cancelled():
    win = LoginView(FakeWindow(), closed_event=threading.Event())
    win._cancel_event = threading.Event()
    win._cancel_event.set()
    win._on_code("ABCD-1234", "https://www.twitch.tv/activate")
    # No control was touched - getControl would lazily create a blank one,
    # so its label staying empty demonstrates _on_code short-circuited.
    assert win.window.getControl(LoginView.CODE_LABEL_ID).getLabel() == ""


def test_on_status_does_nothing_when_cancelled():
    win = LoginView(FakeWindow(), closed_event=threading.Event())
    win._cancel_event = threading.Event()
    win._cancel_event.set()
    win._on_status("success")
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


def test_activate_does_not_restart_after_success_even_if_reactivated():
    # Kodi can re-show this view's group (e.g. re-activation) even after
    # _on_status("success") has already handed off to Home and the polling
    # thread has finished (is_alive() would be False by then) - the
    # thread-liveness check alone isn't enough to stop a second device-code
    # request from starting on an already-completed login.
    win = LoginView(FakeWindow(), closed_event=threading.Event())
    win._cancel_event = threading.Event()
    win._on_status("success")

    with patch("lib.views.login_view.threading.Thread") as mock_thread_cls:
        win.activate()
    mock_thread_cls.assert_not_called()
