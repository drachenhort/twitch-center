import threading
from unittest.mock import MagicMock, patch

from lib.windows.login import LoginWindow


def test_on_code_sets_code_and_url_labels():
    win = LoginWindow("script-twitch-center-login.xml", "/tmp")
    win._cancel_event = threading.Event()
    win._on_code("ABCD-1234", "https://www.twitch.tv/activate")
    assert win.getControl(LoginWindow.CODE_LABEL_ID).getLabel() == "ABCD-1234"
    assert win.getControl(LoginWindow.URL_LABEL_ID).getLabel() == "https://www.twitch.tv/activate"


def test_on_status_sets_status_label_text():
    win = LoginWindow("script-twitch-center-login.xml", "/tmp")
    win._cancel_event = threading.Event()
    win._on_status("pending")
    assert win.getControl(LoginWindow.STATUS_LABEL_ID).getLabel() == "Waiting for authorization..."


def test_on_status_success_closes_window():
    win = LoginWindow("script-twitch-center-login.xml", "/tmp")
    win._cancel_event = threading.Event()
    with patch.object(win, "close") as mock_close:
        win._on_status("success")
    mock_close.assert_called_once()
    assert win.closed_event.is_set()


def test_on_code_does_nothing_when_cancelled():
    win = LoginWindow("script-twitch-center-login.xml", "/tmp")
    win._cancel_event = threading.Event()
    win._cancel_event.set()
    win._on_code("ABCD-1234", "https://www.twitch.tv/activate")
    # No control was touched - getControl would lazily create a blank one,
    # so its label staying empty demonstrates _on_code short-circuited.
    assert win.getControl(LoginWindow.CODE_LABEL_ID).getLabel() == ""


def test_on_status_does_nothing_when_cancelled():
    win = LoginWindow("script-twitch-center-login.xml", "/tmp")
    win._cancel_event = threading.Event()
    win._cancel_event.set()
    with patch.object(win, "close") as mock_close:
        win._on_status("success")
    mock_close.assert_not_called()
    assert win.getControl(LoginWindow.STATUS_LABEL_ID).getLabel() == ""


def test_on_action_back_sets_cancel_event_and_closes():
    import xbmcgui

    win = LoginWindow("script-twitch-center-login.xml", "/tmp")
    win._cancel_event = threading.Event()
    with patch.object(win, "close") as mock_close:
        win.onAction(xbmcgui.Action(xbmcgui.ACTION_NAV_BACK))
    assert win._cancel_event.is_set()
    mock_close.assert_called_once()
    assert win.closed_event.is_set()


def test_on_action_unrelated_key_does_nothing():
    import xbmcgui

    win = LoginWindow("script-twitch-center-login.xml", "/tmp")
    win._cancel_event = threading.Event()
    with patch.object(win, "close") as mock_close:
        win.onAction(xbmcgui.Action(999))
    assert not win._cancel_event.is_set()
    mock_close.assert_not_called()


def test_oninit_starts_background_thread_with_run_device_code_login():
    from lib.twitch import auth

    with patch("lib.windows.login.threading.Thread") as mock_thread_cls:
        win = LoginWindow("script-twitch-center-login.xml", "/tmp")
        win.onInit()
    mock_thread_cls.assert_called_once()
    call_kwargs = mock_thread_cls.call_args.kwargs
    assert call_kwargs["target"] is auth.run_device_code_login
    assert call_kwargs["kwargs"]["client_id"] == ""
    assert call_kwargs["kwargs"]["scopes"] == auth.SCOPES
    mock_thread_cls.return_value.start.assert_called_once()


def test_oninit_is_idempotent_when_thread_already_running():
    with patch("lib.windows.login.threading.Thread") as mock_thread_cls:
        mock_thread_cls.return_value.is_alive.return_value = True
        win = LoginWindow("script-twitch-center-login.xml", "/tmp")
        win.onInit()
        win.onInit()
    mock_thread_cls.assert_called_once()


def test_oninit_starts_new_thread_if_previous_thread_finished():
    with patch("lib.windows.login.threading.Thread") as mock_thread_cls:
        first_thread = MagicMock()
        first_thread.is_alive.return_value = False
        second_thread = MagicMock()
        mock_thread_cls.side_effect = [first_thread, second_thread]

        win = LoginWindow("script-twitch-center-login.xml", "/tmp")
        win.onInit()
        win.onInit()
    assert mock_thread_cls.call_count == 2
    second_thread.start.assert_called_once()
