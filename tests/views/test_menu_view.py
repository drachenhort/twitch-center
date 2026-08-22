from unittest.mock import patch

import xbmcaddon
import xbmcgui

from lib.views.menu_view import MenuView


class FakeMainWindow:
    def __init__(self):
        self.switched_to = []

    def _switch_view(self, name):
        self.switched_to.append(name)

    def getFocusId(self):
        return self._focus_id

    def setFocusId(self, control_id):
        self._focus_id = control_id


def _select(window, control_id):
    window.setFocusId(control_id)
    view = MenuView(window)
    view.handle_action(xbmcgui.Action(xbmcgui.ACTION_SELECT_ITEM))
    return view


def test_selecting_live_streams_switches_to_live_streams_view():
    window = FakeMainWindow()
    _select(window, MenuView.LIVE_STREAMS_BUTTON_ID)
    assert window.switched_to == ["live_streams"]


def test_selecting_discover_switches_to_discover_view():
    window = FakeMainWindow()
    _select(window, MenuView.DISCOVER_BUTTON_ID)
    assert window.switched_to == ["discover"]


def test_selecting_search_switches_to_search_view():
    window = FakeMainWindow()
    _select(window, MenuView.SEARCH_BUTTON_ID)
    assert window.switched_to == ["search"]


def test_selecting_relogin_switches_to_login_view():
    window = FakeMainWindow()
    _select(window, MenuView.RELOGIN_BUTTON_ID)
    assert window.switched_to == ["login"]


def test_selecting_settings_opens_addon_settings_without_switching_view():
    window = FakeMainWindow()
    addon = xbmcaddon.Addon()
    with patch("xbmcaddon.Addon", return_value=addon), patch.object(
        addon, "openSettings"
    ) as mock_open_settings:
        _select(window, MenuView.SETTINGS_BUTTON_ID)
    mock_open_settings.assert_called_once()
    assert window.switched_to == []


def test_non_select_action_is_a_no_op():
    window = FakeMainWindow()
    window.setFocusId(MenuView.DISCOVER_BUTTON_ID)
    view = MenuView(window)
    view.handle_action(xbmcgui.Action(999))
    assert window.switched_to == []


def test_selecting_kick_login_switches_to_kick_login_view_when_credentials_set():
    window = FakeMainWindow()
    addon = xbmcaddon.Addon()
    addon.setSetting("kick_client_id", "cid")
    addon.setSetting("kick_client_secret", "csecret")
    with patch("lib.views.menu_view.xbmcaddon.Addon", return_value=addon):
        _select(window, MenuView.KICK_LOGIN_BUTTON_ID)
    assert window.switched_to == ["kick_login"]


def test_selecting_kick_login_shows_a_dialog_when_client_id_missing():
    window = FakeMainWindow()
    addon = xbmcaddon.Addon()
    addon.setSetting("kick_client_secret", "csecret")  # client id left empty
    with patch("lib.views.menu_view.xbmcaddon.Addon", return_value=addon), patch(
        "lib.views.menu_view.xbmcgui.Dialog"
    ) as mock_dialog_cls:
        _select(window, MenuView.KICK_LOGIN_BUTTON_ID)
    mock_dialog_cls.return_value.ok.assert_called_once()
    assert window.switched_to == []


def test_selecting_kick_login_shows_a_dialog_when_client_secret_missing():
    window = FakeMainWindow()
    addon = xbmcaddon.Addon()
    addon.setSetting("kick_client_id", "cid")  # secret left empty
    with patch("lib.views.menu_view.xbmcaddon.Addon", return_value=addon), patch(
        "lib.views.menu_view.xbmcgui.Dialog"
    ) as mock_dialog_cls:
        _select(window, MenuView.KICK_LOGIN_BUTTON_ID)
    mock_dialog_cls.return_value.ok.assert_called_once()
    assert window.switched_to == []
