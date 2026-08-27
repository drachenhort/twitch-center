from unittest.mock import patch

import xbmcaddon
import xbmcgui

from lib.twitch import api
from lib.twitch.auth import load_token, save_token
from lib.views.vod_clips_channels_view import VodClipsChannelsView

FakeAddon = xbmcaddon.Addon


class FakeWindow:
    def __init__(self):
        self._controls = {}
        self._focus_id = None
        self.switched_to = []

    def getControl(self, control_id):
        from xbmcgui import FakeListControl

        if control_id not in self._controls:
            self._controls[control_id] = FakeListControl()
        return self._controls[control_id]

    def setFocusId(self, control_id):
        self._focus_id = control_id

    def getFocusId(self):
        return self._focus_id

    def _switch_view(self, name, context=None):
        self.switched_to.append((name, context))


def _addon_with_token(token):
    addon = FakeAddon()
    if token is not None:
        save_token(token, addon)
    return addon


FOLLOWED = [
    {"broadcaster_id": "1", "broadcaster_login": "alice", "broadcaster_name": "Alice"},
    {"broadcaster_id": "2", "broadcaster_login": "bob", "broadcaster_name": "Bob"},
]


def test_activate_populates_channel_list_from_all_followed_channels():
    addon = _addon_with_token({"access_token": "tok", "refresh_token": "ref", "user_id": "u1"})
    with patch("xbmcaddon.Addon", return_value=addon), patch.object(
        api, "get_followed_channels", return_value=FOLLOWED
    ):
        window = FakeWindow()
        view = VodClipsChannelsView(window)
        view.activate()
    channel_list = window.getControl(VodClipsChannelsView.CHANNEL_LIST_ID)
    assert channel_list.size() == 2
    assert window.getFocusId() == VodClipsChannelsView.CHANNEL_LIST_ID


def test_activate_sets_title():
    addon = _addon_with_token({"access_token": "tok", "refresh_token": "ref", "user_id": "u1"})
    with patch("xbmcaddon.Addon", return_value=addon), patch.object(
        api, "get_followed_channels", return_value=[]
    ):
        window = FakeWindow()
        view = VodClipsChannelsView(window)
        view.activate()
    assert window.getControl(VodClipsChannelsView.TITLE_LABEL_ID).getLabel() == "VODs & Clips"


def test_activate_shows_empty_message_when_no_followed_channels():
    addon = _addon_with_token({"access_token": "tok", "refresh_token": "ref", "user_id": "u1"})
    with patch("xbmcaddon.Addon", return_value=addon), patch.object(
        api, "get_followed_channels", return_value=[]
    ):
        window = FakeWindow()
        view = VodClipsChannelsView(window)
        view.activate()
    empty_label = window.getControl(VodClipsChannelsView.EMPTY_LABEL_ID)
    assert empty_label.getLabel() != ""
    assert window.getControl(VodClipsChannelsView.RELOGIN_BUTTON_ID).isVisible() is True


def test_selecting_a_channel_switches_to_vod_clips_with_context():
    addon = _addon_with_token({"access_token": "tok", "refresh_token": "ref", "user_id": "u1"})
    followed = [{"broadcaster_id": "1", "broadcaster_login": "alice", "broadcaster_name": "Alice"}]
    with patch("xbmcaddon.Addon", return_value=addon), patch.object(
        api, "get_followed_channels", return_value=followed
    ):
        window = FakeWindow()
        view = VodClipsChannelsView(window)
        view.activate()
        channel_list = window.getControl(VodClipsChannelsView.CHANNEL_LIST_ID)
        channel_list.selectItem(0)
        window.setFocusId(VodClipsChannelsView.CHANNEL_LIST_ID)
        view.handle_action(xbmcgui.Action(xbmcgui.ACTION_SELECT_ITEM))
    assert window.switched_to == [(
        "vod_clips",
        {"broadcaster_id": "1", "broadcaster_login": "alice", "broadcaster_name": "Alice"},
    )]


def test_activate_shows_relogin_button_when_no_token():
    with patch("xbmcaddon.Addon", return_value=_addon_with_token(None)):
        window = FakeWindow()
        view = VodClipsChannelsView(window)
        view.activate()
    assert window.getControl(VodClipsChannelsView.ERROR_LABEL_ID).getLabel() != ""
    assert window.getControl(VodClipsChannelsView.RELOGIN_BUTTON_ID).isVisible() is True


def test_activate_shows_relogin_prompt_when_token_refresh_fails_after_expiry():
    old_token = {"access_token": "old", "refresh_token": "ref", "user_id": "u1"}
    addon = _addon_with_token(old_token)
    with patch("xbmcaddon.Addon", return_value=addon), patch.object(
        api, "get_followed_channels", side_effect=api.TokenExpiredError()
    ), patch(
        "lib.views.vod_clips_channels_view.auth.refresh_access_token", return_value=None
    ):
        window = FakeWindow()
        view = VodClipsChannelsView(window)
        view.activate()
    assert load_token(addon) is None
    assert window.getControl(VodClipsChannelsView.ERROR_LABEL_ID).getLabel() != ""
    assert window.getControl(VodClipsChannelsView.RELOGIN_BUTTON_ID).isVisible() is True


def test_selecting_the_relogin_button_switches_to_login():
    window = FakeWindow()
    view = VodClipsChannelsView(window)
    window.setFocusId(VodClipsChannelsView.RELOGIN_BUTTON_ID)
    view.handle_action(xbmcgui.Action(xbmcgui.ACTION_SELECT_ITEM))
    assert window.switched_to == [("login", None)]
