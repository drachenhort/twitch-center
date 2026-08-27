from unittest.mock import patch

import xbmcaddon
import xbmcgui

from lib import providers
from lib.twitch import api
from lib.twitch.auth import load_token, save_token
from lib.views.vod_clips_view import VodClipsView

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


CONTEXT = {"broadcaster_id": "1", "broadcaster_login": "alice", "broadcaster_name": "Alice"}

VIDEOS = [{
    "id": "v1", "title": "VOD 1", "created_at": "2026-08-20T00:00:00Z",
    "duration": "1h", "thumbnail_url": "https://example.invalid/t-%{width}x%{height}.jpg",
    "view_count": 5,
}]

CLIPS = [{
    "id": "c1", "title": "Clip 1", "created_at": "2026-08-20T00:00:00Z",
    "duration": 20.0, "thumbnail_url": "https://clips-media-assets2.twitch.tv/X-preview-480x272.jpg",
    "view_count": 3,
}]


def test_activate_with_no_context_shows_error_without_crashing():
    window = FakeWindow()
    view = VodClipsView(window)
    view.context = None
    # The skin declares the relogin button <visible>false</visible> by
    # default; mirror that starting state here since FakeListControl itself
    # defaults to visible.
    window.getControl(VodClipsView.RELOGIN_BUTTON_ID).setVisible(False)
    view.activate()
    error_label = window.getControl(VodClipsView.ERROR_LABEL_ID)
    assert error_label.getLabel() != ""
    # No context is not an auth failure - the relogin button must not be
    # shown (misleading: it invites destroying a valid login session).
    assert window.getControl(VodClipsView.RELOGIN_BUTTON_ID).isVisible() is False


def test_activate_with_no_vods_and_no_clips_shows_neutral_message_not_relogin():
    addon = _addon_with_token({"access_token": "tok", "refresh_token": "ref", "user_id": "u1"})
    with patch("xbmcaddon.Addon", return_value=addon), patch.object(
        api, "get_videos", return_value=[]
    ), patch.object(api, "get_clips", return_value=[]):
        window = FakeWindow()
        view = VodClipsView(window)
        view.context = CONTEXT
        view.activate()
    error_label = window.getControl(VodClipsView.ERROR_LABEL_ID)
    assert error_label.getLabel() == "No VODs or Clips for this channel."
    assert window.getControl(VodClipsView.RELOGIN_BUTTON_ID).isVisible() is False


def test_activate_populates_both_vods_and_clips_lists():
    addon = _addon_with_token({"access_token": "tok", "refresh_token": "ref", "user_id": "u1"})
    with patch("xbmcaddon.Addon", return_value=addon), patch.object(
        api, "get_videos", return_value=VIDEOS
    ), patch.object(api, "get_clips", return_value=CLIPS):
        window = FakeWindow()
        view = VodClipsView(window)
        view.context = CONTEXT
        view.activate()
    assert window.getControl(VodClipsView.VODS_LIST_ID).size() == 1
    assert window.getControl(VodClipsView.CLIPS_LIST_ID).size() == 1
    assert window.getControl(VodClipsView.TITLE_LABEL_ID).getLabel() == "Alice"
    assert window.getFocusId() == VodClipsView.VODS_LIST_ID


def test_selecting_a_vod_resolves_and_plays_it():
    addon = _addon_with_token({"access_token": "tok", "refresh_token": "ref", "user_id": "u1"})
    with patch("xbmcaddon.Addon", return_value=addon), patch.object(
        api, "get_videos", return_value=VIDEOS
    ), patch.object(api, "get_clips", return_value=[]), patch.object(
        providers, "resolve_vod_url", return_value="https://usher.example/vod.m3u8"
    ) as mock_resolve, patch(
        "lib.views.vod_clips_view.player.play_stream", return_value=True
    ) as mock_play:
        window = FakeWindow()
        view = VodClipsView(window)
        view.context = CONTEXT
        view.activate()
        vods_control = window.getControl(VodClipsView.VODS_LIST_ID)
        vods_control.selectItem(0)
        window.setFocusId(VodClipsView.VODS_LIST_ID)
        view.handle_action(xbmcgui.Action(xbmcgui.ACTION_SELECT_ITEM))

    mock_resolve.assert_called_once()
    assert mock_resolve.call_args.args[1] == "v1"
    mock_play.assert_called_once_with(
        "https://usher.example/vod.m3u8", "VOD 1", platform="twitch_vod"
    )


def test_selecting_a_clip_resolves_and_plays_it():
    addon = _addon_with_token({"access_token": "tok", "refresh_token": "ref", "user_id": "u1"})
    with patch("xbmcaddon.Addon", return_value=addon), patch.object(
        api, "get_videos", return_value=[]
    ), patch.object(api, "get_clips", return_value=CLIPS), patch.object(
        providers, "resolve_clip_url", return_value="https://clips.example/x.mp4"
    ) as mock_resolve, patch(
        "lib.views.vod_clips_view.player.play_stream", return_value=True
    ) as mock_play:
        window = FakeWindow()
        view = VodClipsView(window)
        view.context = CONTEXT
        view.activate()
        clips_control = window.getControl(VodClipsView.CLIPS_LIST_ID)
        clips_control.selectItem(0)
        window.setFocusId(VodClipsView.CLIPS_LIST_ID)
        view.handle_action(xbmcgui.Action(xbmcgui.ACTION_SELECT_ITEM))

    mock_resolve.assert_called_once()
    assert mock_resolve.call_args.args[1] == CLIPS[0]["thumbnail_url"]
    mock_play.assert_called_once_with(
        "https://clips.example/x.mp4", "Clip 1", platform="twitch_clip"
    )


def test_vod_playback_resolution_failure_shows_error_without_crashing():
    addon = _addon_with_token({"access_token": "tok", "refresh_token": "ref", "user_id": "u1"})
    with patch("xbmcaddon.Addon", return_value=addon), patch.object(
        api, "get_videos", return_value=VIDEOS
    ), patch.object(api, "get_clips", return_value=[]), patch.object(
        providers, "resolve_vod_url", side_effect=providers.StreamUnavailableError("x")
    ):
        window = FakeWindow()
        view = VodClipsView(window)
        view.context = CONTEXT
        view.activate()
        vods_control = window.getControl(VodClipsView.VODS_LIST_ID)
        vods_control.selectItem(0)
        window.setFocusId(VodClipsView.VODS_LIST_ID)
        view.handle_action(xbmcgui.Action(xbmcgui.ACTION_SELECT_ITEM))
    error_label = window.getControl(VodClipsView.ERROR_LABEL_ID)
    assert error_label.getLabel() != ""
    # A transient playback failure must not wipe the lists the user is browsing.
    assert window.getControl(VodClipsView.VODS_LIST_ID).size() == 1


def test_activate_shows_relogin_prompt_when_token_refresh_fails_after_expiry():
    old_token = {"access_token": "old", "refresh_token": "ref", "user_id": "u1"}
    addon = _addon_with_token(old_token)
    with patch("xbmcaddon.Addon", return_value=addon), patch.object(
        api, "get_videos", side_effect=api.TokenExpiredError()
    ), patch(
        "lib.views.vod_clips_view.auth.refresh_access_token", return_value=None
    ):
        window = FakeWindow()
        view = VodClipsView(window)
        view.context = CONTEXT
        view.activate()
    assert load_token(addon) is None
    assert window.getControl(VodClipsView.ERROR_LABEL_ID).getLabel() != ""
    assert window.getControl(VodClipsView.RELOGIN_BUTTON_ID).isVisible() is True


def test_back_target_is_the_channel_picker():
    assert VodClipsView.BACK_TARGET == "vod_clips_channels"
