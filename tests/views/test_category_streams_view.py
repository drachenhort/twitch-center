from unittest.mock import patch

import requests
import xbmcaddon
import xbmcgui

from lib import providers
from lib.twitch import api
from lib.twitch.auth import save_token
from lib.views import category_streams_view
from lib.views.category_streams_view import CategoryStreamsView

FakeAddon = xbmcaddon.Addon
TOKEN = {"access_token": "tok", "refresh_token": "ref", "user_id": "u1"}
CONTEXT = {"game_id": "509658", "game_name": "Just Chatting"}

STREAMS = [
    {"user_id": "1", "user_login": "alice", "user_name": "Alice", "game_name": "Just Chatting",
     "viewer_count": 100, "thumbnail_url": "https://x.invalid/a-{width}x{height}.jpg"},
    {"user_id": "2", "user_login": "bob", "user_name": "Bob", "game_name": "Just Chatting",
     "viewer_count": 50, "thumbnail_url": "https://x.invalid/b-{width}x{height}.jpg"},
]


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


def _view(context=CONTEXT):
    view = CategoryStreamsView(FakeWindow())
    view.context = context
    return view


def _select_stream(view, index):
    view.window.getControl(CategoryStreamsView.STREAM_LIST_ID).selectItem(index)
    view.window.setFocusId(CategoryStreamsView.STREAM_LIST_ID)
    view.handle_action(xbmcgui.Action(xbmcgui.ACTION_SELECT_ITEM))


def test_activate_lists_streams_for_context_game():
    addon = _addon_with_token(TOKEN)
    with patch("xbmcaddon.Addon", return_value=addon), patch.object(
        api, "get_live_streams_by_game", return_value=STREAMS
    ) as mock_streams:
        view = _view()
        view.activate()
    mock_streams.assert_called_once_with("tok", addon.getSetting("client_id"), "509658", first=100)
    assert view.window.getControl(CategoryStreamsView.TITLE_LABEL_ID).getLabel() == "Just Chatting"
    control = view.window.getControl(CategoryStreamsView.STREAM_LIST_ID)
    assert control.size() == 2
    assert control.getListItem(0).getProperty("broadcaster_login") == "alice"
    assert view.window.getFocusId() == CategoryStreamsView.STREAM_LIST_ID


def test_missing_context_shows_error_without_relogin():
    with patch.object(api, "get_live_streams_by_game") as mock_streams:
        view = _view(context=None)
        view.activate()
    mock_streams.assert_not_called()
    assert view.window.getControl(CategoryStreamsView.ERROR_LABEL_ID).getLabel() != ""
    assert view.window.switched_to == []


def test_empty_category_shows_message():
    addon = _addon_with_token(TOKEN)
    with patch("xbmcaddon.Addon", return_value=addon), patch.object(
        api, "get_live_streams_by_game", return_value=[]
    ):
        view = _view()
        view.activate()
    assert (
        view.window.getControl(CategoryStreamsView.EMPTY_LABEL_ID).getLabel()
        == "Nobody's live in this category right now."
    )


def test_selecting_stream_plays_it():
    addon = _addon_with_token(TOKEN)
    with patch("xbmcaddon.Addon", return_value=addon), patch.object(
        api, "get_live_streams_by_game", return_value=STREAMS
    ), patch.object(category_streams_view.playback, "play_channel", return_value=True) as mock_play:
        view = _view()
        view.activate()
        _select_stream(view, 0)
    args, kwargs = mock_play.call_args
    assert args == ("twitch", "alice")
    assert kwargs["token"]["access_token"] == "tok"
    assert kwargs["client_id"] == addon.getSetting("client_id")
    assert callable(kwargs["show_error"])


def test_playback_failure_shows_error_and_keeps_streams():
    addon = _addon_with_token(TOKEN)
    with patch("xbmcaddon.Addon", return_value=addon), patch.object(
        api, "get_live_streams_by_game", return_value=STREAMS
    ), patch.object(
        providers, "resolve_stream_url", side_effect=providers.StreamUnavailableError("alice")
    ):
        view = _view()
        view.activate()
        _select_stream(view, 0)
    assert view.window.getControl(CategoryStreamsView.ERROR_LABEL_ID).getLabel() != ""
    assert view.window.getControl(CategoryStreamsView.STREAM_LIST_ID).size() == 2
    assert view.window.switched_to == []


def test_expired_token_refreshes_and_retries_same_category():
    addon = _addon_with_token(TOKEN)
    refreshed = {"access_token": "new", "refresh_token": "ref2"}
    with patch("xbmcaddon.Addon", return_value=addon), patch.object(
        api, "get_live_streams_by_game", side_effect=[api.TokenExpiredError(), STREAMS]
    ) as mock_streams, patch(
        "lib.views.category_streams_view.auth.refresh_access_token", return_value=refreshed
    ):
        view = _view()
        view.activate()
    assert [call.args[2] for call in mock_streams.call_args_list] == ["509658", "509658"]
    assert mock_streams.call_args.args[0] == "new"
    assert view.window.getControl(CategoryStreamsView.STREAM_LIST_ID).size() == 2


def test_network_error_shows_error():
    addon = _addon_with_token(TOKEN)
    with patch("xbmcaddon.Addon", return_value=addon), patch.object(
        api, "get_live_streams_by_game", side_effect=requests.ConnectionError("down")
    ):
        view = _view()
        view.activate()
    assert view.window.getControl(CategoryStreamsView.ERROR_LABEL_ID).getLabel() != ""
    assert view.window.getControl(CategoryStreamsView.STREAM_LIST_ID).size() == 0


def test_switching_category_clears_old_streams_before_loading():
    # The group becomes visible before activate()'s blocking HTTP call; the
    # previous category's streams must not sit there (and be playable) meanwhile.
    addon = _addon_with_token(TOKEN)
    sizes_during_fetch = []
    view = _view()

    def fake_streams(*args, **kwargs):
        sizes_during_fetch.append(view.window.getControl(CategoryStreamsView.STREAM_LIST_ID).size())
        return STREAMS

    with patch("xbmcaddon.Addon", return_value=addon), patch.object(
        api, "get_live_streams_by_game", side_effect=fake_streams
    ):
        view.activate()
        view.context = {"game_id": "21779", "game_name": "League of Legends"}
        view.activate()
    assert sizes_during_fetch == [0, 0]


def test_missing_context_clears_old_streams():
    addon = _addon_with_token(TOKEN)
    with patch("xbmcaddon.Addon", return_value=addon), patch.object(
        api, "get_live_streams_by_game", return_value=STREAMS
    ):
        view = _view()
        view.activate()
        view.context = None
        view.activate()
    assert view.window.getControl(CategoryStreamsView.STREAM_LIST_ID).size() == 0
