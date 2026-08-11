import threading
from unittest.mock import patch

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


def test_on_action_back_sets_cancel_event_and_closes():
    import xbmcgui

    win = LoginWindow("script-twitch-center-login.xml", "/tmp")
    win._cancel_event = threading.Event()
    with patch.object(win, "close") as mock_close:
        win.onAction(xbmcgui.Action(xbmcgui.ACTION_NAV_BACK))
    assert win._cancel_event.is_set()
    mock_close.assert_called_once()


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
