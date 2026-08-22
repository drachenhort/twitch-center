import threading
from unittest.mock import MagicMock, patch

import xbmcgui

from lib.views.kick_login_view import KickLoginView


class FakeWindow:
    def __init__(self):
        self._controls = {}

    def getControl(self, control_id):
        from xbmcgui import FakeListControl

        if control_id not in self._controls:
            self._controls[control_id] = FakeListControl()
        return self._controls[control_id]


def test_on_code_sets_url_label():
    win = KickLoginView(FakeWindow(), closed_event=threading.Event())
    win._cancel_event = threading.Event()
    win._on_code(win._cancel_event, "https://id.kick.com/oauth/authorize?client_id=x")
    assert win.window.getControl(KickLoginView.URL_LABEL_ID).getLabel() == (
        "https://id.kick.com/oauth/authorize?client_id=x"
    )


def test_on_status_sets_status_label_text():
    win = KickLoginView(FakeWindow(), closed_event=threading.Event())
    win._cancel_event = threading.Event()
    win._on_status(win._cancel_event, "pending")
    assert win.window.getControl(KickLoginView.STATUS_LABEL_ID).getLabel() == "Waiting for authorization..."


def test_on_status_denied_sets_status_label_text():
    win = KickLoginView(FakeWindow(), closed_event=threading.Event())
    win._cancel_event = threading.Event()
    win._on_status(win._cancel_event, "denied")
    assert win.window.getControl(KickLoginView.STATUS_LABEL_ID).getLabel() == (
        "Access denied. Reopen this screen to try again."
    )


def test_on_status_success_sets_login_succeeded_flag():
    win = KickLoginView(FakeWindow(), closed_event=threading.Event())
    win._cancel_event = threading.Event()
    win._on_status(win._cancel_event, "success")
    assert win.login_succeeded is True


def test_on_code_does_nothing_when_cancelled():
    win = KickLoginView(FakeWindow(), closed_event=threading.Event())
    win._cancel_event = threading.Event()
    win._cancel_event.set()
    win._on_code(win._cancel_event, "https://id.kick.com/oauth/authorize?client_id=x")
    assert win.window.getControl(KickLoginView.URL_LABEL_ID).getLabel() == ""


def test_on_status_does_nothing_when_cancelled():
    win = KickLoginView(FakeWindow(), closed_event=threading.Event())
    win._cancel_event = threading.Event()
    win._cancel_event.set()
    win._on_status(win._cancel_event, "success")
    assert win.login_succeeded is False
    assert win.window.getControl(KickLoginView.STATUS_LABEL_ID).getLabel() == ""


def test_activate_starts_background_thread_with_run_pkce_login():
    import xbmcaddon

    from lib.kick import auth

    addon = xbmcaddon.Addon()
    addon.setSetting("kick_client_id", "cid")
    addon.setSetting("kick_client_secret", "csecret")
    addon.setSetting("kick_redirect_port", "8919")

    with patch("lib.views.kick_login_view.xbmcaddon.Addon", return_value=addon), patch(
        "lib.views.kick_login_view.threading.Thread"
    ) as mock_thread_cls:
        win = KickLoginView(FakeWindow(), closed_event=threading.Event())
        win.activate()

    mock_thread_cls.assert_called_once()
    call_kwargs = mock_thread_cls.call_args.kwargs
    assert call_kwargs["target"] is auth.run_pkce_login
    assert call_kwargs["kwargs"]["client_id"] == "cid"
    assert call_kwargs["kwargs"]["client_secret"] == "csecret"
    assert call_kwargs["kwargs"]["redirect_port"] == 8919
    assert call_kwargs["kwargs"]["scopes"] == auth.SCOPES
    mock_thread_cls.return_value.start.assert_called_once()


def test_activate_is_idempotent_when_thread_already_running():
    with patch("lib.views.kick_login_view.threading.Thread") as mock_thread_cls:
        mock_thread_cls.return_value.is_alive.return_value = True
        win = KickLoginView(FakeWindow(), closed_event=threading.Event())
        win.activate()
        win.activate()
    mock_thread_cls.assert_called_once()


def test_activate_starts_a_fresh_login_flow_on_a_second_visit():
    with patch("lib.views.kick_login_view.threading.Thread") as mock_thread_cls:
        first_thread = MagicMock()
        first_thread.is_alive.return_value = True
        second_thread = MagicMock()
        mock_thread_cls.side_effect = [first_thread, second_thread]

        win = KickLoginView(FakeWindow(), closed_event=threading.Event())
        win.activate()
        win._on_status(win._cancel_event, "success")
        assert win.login_succeeded is True

        win.stop()
        win.activate()

    assert mock_thread_cls.call_count == 2
    second_thread.start.assert_called_once()
    assert win.login_succeeded is False
    assert not win._cancel_event.is_set()


def test_activate_does_not_restart_after_success_even_if_reactivated():
    win = KickLoginView(FakeWindow(), closed_event=threading.Event())
    win._cancel_event = threading.Event()
    win._on_status(win._cancel_event, "success")

    with patch("lib.views.kick_login_view.threading.Thread") as mock_thread_cls:
        win.activate()
    mock_thread_cls.assert_not_called()


def test_on_action_and_click_are_no_ops():
    win = KickLoginView(FakeWindow(), closed_event=threading.Event())
    win._cancel_event = threading.Event()
    win.handle_action(xbmcgui.Action(xbmcgui.ACTION_NAV_BACK))
    win.handle_click(KickLoginView.CANCEL_BUTTON_ID)
    # Neither raises, and stop() (which would set the cancel event) is never
    # implicitly called by either - Back/Cancel are handled by the skin's
    # <onclick>PreviousMenu</onclick> and MainWindow's central Back handling,
    # same as LoginView's CANCEL_BUTTON_ID.
    assert not win._cancel_event.is_set()
