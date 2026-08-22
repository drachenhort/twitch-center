from unittest.mock import patch

import xbmcaddon
import xbmcgui

from lib.twitch import api, gql
from lib.twitch.auth import save_token
from lib.views.live_streams_view import LiveStreamsView, _NO_LIVE_MESSAGE, _build_list_item, _merge_channels

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

    def _switch_view(self, name):
        self.switched_to.append(name)


FOLLOWED = [
    {"broadcaster_id": "1", "broadcaster_login": "alice", "broadcaster_name": "Alice"},
    {"broadcaster_id": "2", "broadcaster_login": "bob", "broadcaster_name": "Bob"},
    {"broadcaster_id": "3", "broadcaster_login": "carol", "broadcaster_name": "Carol"},
]

LIVE = [
    {
        "user_id": "2",
        "game_name": "Just Chatting",
        "title": "hello",
        "viewer_count": 50,
        "thumbnail_url": "https://example.invalid/{width}x{height}.jpg",
    },
    {
        "user_id": "3",
        "game_name": "Programming",
        "title": "code",
        "viewer_count": 200,
        "thumbnail_url": "https://example.invalid/{width}x{height}.jpg",
    },
]


def test_merge_channels_sorts_live_by_viewers_desc_then_offline_alpha():
    live, offline = _merge_channels(FOLLOWED, LIVE)
    assert [c["broadcaster_name"] for c, _ in live] == ["Carol", "Bob"]
    assert [c["broadcaster_name"] for c in offline] == ["Alice"]


def test_merge_channels_all_offline():
    live, offline = _merge_channels(FOLLOWED, [])
    assert live == []
    assert [c["broadcaster_name"] for c in offline] == ["Alice", "Bob", "Carol"]


def test_build_list_item_live_sets_label2_and_thumbnail():
    channel = FOLLOWED[1]
    stream = LIVE[0]
    item = _build_list_item(channel, stream)
    assert item.getLabel() == "Bob"
    assert "Just Chatting" in item.getLabel2()
    assert "50" in item.getLabel2()
    assert item.getArt("thumb") == "https://example.invalid/320x180.jpg"
    assert item.getProperty("broadcaster_id") == "2"


def _addon_with_token(token):
    addon = FakeAddon()
    if token is not None:
        save_token(token, addon)
    return addon


def test_oninit_populates_list_on_success():
    addon = _addon_with_token({"access_token": "tok", "refresh_token": "ref", "user_id": "u1"})
    with patch("xbmcaddon.Addon", return_value=addon), patch.object(
        api, "get_followed_channels", return_value=FOLLOWED
    ), patch.object(api, "get_live_status", return_value=LIVE), patch.object(
        gql, "get_followed_live_games", return_value=[]
    ):
        win = LiveStreamsView(FakeWindow())
        win.activate()
    control = win.window.getControl(LiveStreamsView.CHANNEL_LIST_ID)
    assert control.size() == 2
    assert win.window.getFocusId() == LiveStreamsView.CHANNEL_LIST_ID
    assert all(item.getProperty("is_live") == "true" for item in control._items)


def test_oninit_still_hides_offline_channels_when_setting_is_off():
    addon = _addon_with_token({"access_token": "tok", "refresh_token": "ref", "user_id": "u1"})
    with patch("xbmcaddon.Addon", return_value=addon), patch.object(
        api, "get_followed_channels", return_value=FOLLOWED
    ), patch.object(api, "get_live_status", return_value=LIVE), patch.object(
        gql, "get_followed_live_games", return_value=[]
    ):
        win = LiveStreamsView(FakeWindow())
        win.activate()
    control = win.window.getControl(LiveStreamsView.CHANNEL_LIST_ID)
    assert control.size() == 2


def test_oninit_shows_offline_channels_after_live_ones_when_setting_is_on():
    addon = _addon_with_token({"access_token": "tok", "refresh_token": "ref", "user_id": "u1"})
    addon.setSetting("show_offline_channels", True)
    with patch("xbmcaddon.Addon", return_value=addon), patch.object(
        api, "get_followed_channels", return_value=FOLLOWED
    ), patch.object(api, "get_live_status", return_value=LIVE), patch.object(
        gql, "get_followed_live_games", return_value=[]
    ):
        win = LiveStreamsView(FakeWindow())
        win.activate()
    control = win.window.getControl(LiveStreamsView.CHANNEL_LIST_ID)
    # LIVE-first per _merge_channels: Carol (200 viewers) then Bob (50), then
    # offline Alice appended alphabetically.
    assert [item.getLabel() for item in control._items] == ["Carol", "Bob", "Alice"]
    assert control._items[-1].getProperty("is_live") == "false"
    assert control._items[-1].getLabel2() == "Offline"


def test_oninit_excludes_offline_channels_when_game_filter_is_set_even_with_setting_on():
    addon = _addon_with_token({"access_token": "tok", "refresh_token": "ref", "user_id": "u1"})
    addon.setSetting("show_offline_channels", True)
    with patch("xbmcaddon.Addon", return_value=addon), patch.object(
        api, "get_followed_channels", return_value=FOLLOWED
    ), patch.object(api, "get_live_status", return_value=LIVE), patch.object(
        gql, "get_followed_live_games", return_value=GAMES
    ):
        win = LiveStreamsView(FakeWindow())
        win.activate()
        games_control = win.window.getControl(LiveStreamsView.GAMES_LIST_ID)
        games_control.selectItem(1)  # "Just Chatting" - Bob is live playing it
        win.window.setFocusId(LiveStreamsView.GAMES_LIST_ID)
        win.handle_action(xbmcgui.Action(xbmcgui.ACTION_SELECT_ITEM))

    control = win.window.getControl(LiveStreamsView.CHANNEL_LIST_ID)
    assert [item.getLabel() for item in control._items] == ["Bob"]


def test_oninit_shows_no_live_message_when_all_followed_channels_are_offline():
    addon = _addon_with_token({"access_token": "tok", "refresh_token": "ref", "user_id": "u1"})
    with patch("xbmcaddon.Addon", return_value=addon), patch.object(
        api, "get_followed_channels", return_value=FOLLOWED
    ), patch.object(api, "get_live_status", return_value=[]), patch.object(
        gql, "get_followed_live_games", return_value=[]
    ):
        win = LiveStreamsView(FakeWindow())
        win.activate()
    assert win.window.getControl(LiveStreamsView.CHANNEL_LIST_ID).size() == 0
    assert win.window.getControl(LiveStreamsView.EMPTY_LABEL_ID).getLabel() == _NO_LIVE_MESSAGE


def test_oninit_passes_website_token_setting_to_followed_live_games():
    addon = _addon_with_token({"access_token": "tok", "refresh_token": "ref", "user_id": "u1"})
    addon.setSetting("website_token", "my-website-token")
    with patch("xbmcaddon.Addon", return_value=addon), patch.object(
        api, "get_followed_channels", return_value=FOLLOWED
    ), patch.object(api, "get_live_status", return_value=LIVE), patch.object(
        gql, "get_followed_live_games", return_value=[]
    ) as mock_games:
        win = LiveStreamsView(FakeWindow())
        win.activate()
    mock_games.assert_called_once_with("my-website-token")


def test_oninit_sets_title_to_live_streams():
    addon = _addon_with_token({"access_token": "tok", "refresh_token": "ref", "user_id": "u1"})
    with patch("xbmcaddon.Addon", return_value=addon), patch.object(
        api, "get_followed_channels", return_value=[]
    ), patch.object(api, "get_live_status", return_value=[]), patch.object(
        gql, "get_followed_live_games", return_value=[]
    ):
        win = LiveStreamsView(FakeWindow())
        win.activate()
    title = win.window.getControl(LiveStreamsView.TITLE_LABEL_ID).getLabel()
    assert title == "Live Streams"


def test_activate_offers_relogin_in_place_when_no_followed_channels():
    # Switching to Menu here would hide the group before the user could read
    # the message that was just set - stay put and offer a way forward.
    addon = _addon_with_token({"access_token": "tok", "refresh_token": "ref", "user_id": "u1"})
    with patch("xbmcaddon.Addon", return_value=addon), patch.object(
        api, "get_followed_channels", return_value=[]
    ), patch.object(api, "get_live_status", return_value=[]), patch.object(
        gql, "get_followed_live_games", return_value=[]
    ):
        window = FakeWindow()
        win = LiveStreamsView(window)
        win.activate()
    assert win.window.getControl(LiveStreamsView.EMPTY_LABEL_ID).getLabel() != ""
    assert win.window.getControl(LiveStreamsView.CHANNEL_LIST_ID).size() == 0
    assert window.switched_to == []
    assert win.window.getControl(LiveStreamsView.RELOGIN_BUTTON_ID).isVisible() is True
    assert window.getFocusId() == LiveStreamsView.RELOGIN_BUTTON_ID


def test_oninit_refreshes_token_and_retries_on_expiry():
    old_token = {"access_token": "old", "refresh_token": "ref", "user_id": "u1", "login": "x", "display_name": "X"}
    new_token = {"access_token": "new", "refresh_token": "ref2"}
    addon = _addon_with_token(old_token)

    call_count = {"n": 0}

    def fake_get_followed(access_token, client_id, user_id):
        call_count["n"] += 1
        if access_token == "old":
            raise api.TokenExpiredError()
        return FOLLOWED

    with patch("xbmcaddon.Addon", return_value=addon), patch.object(
        api, "get_followed_channels", side_effect=fake_get_followed
    ), patch.object(api, "get_live_status", return_value=[]), patch.object(
        gql, "get_followed_live_games", return_value=[]
    ), patch(
        "lib.views.live_streams_view.auth.refresh_access_token", return_value=new_token
    ):
        win = LiveStreamsView(FakeWindow())
        win.activate()

    assert call_count["n"] == 2
    assert win.window.getControl(LiveStreamsView.CHANNEL_LIST_ID).size() == 0
    from lib.twitch.auth import load_token

    saved = load_token(addon)
    assert saved["access_token"] == "new"
    assert saved["user_id"] == "u1"  # preserved from the old token


def test_oninit_shows_relogin_prompt_when_refresh_fails():
    old_token = {"access_token": "old", "refresh_token": "ref", "user_id": "u1"}
    addon = _addon_with_token(old_token)

    with patch("xbmcaddon.Addon", return_value=addon), patch.object(
        api, "get_followed_channels", side_effect=api.TokenExpiredError()
    ), patch(
        "lib.views.live_streams_view.auth.refresh_access_token", return_value=None
    ) as mock_refresh, patch("lib.views.live_streams_view.xbmc.log") as mock_log:
        win = LiveStreamsView(FakeWindow())
        win.activate()
        # refresh_access_token's on_error callback is live_streams_view.py's
        # only way to surface *why* the refresh failed, since auth.py stays
        # free of xbmc imports - confirm the wiring is actually connected.
        assert mock_refresh.call_args.kwargs["on_error"] is not None
        mock_refresh.call_args.kwargs["on_error"]("HTTP 401: invalid_grant")
        assert any(
            "invalid_grant" in call.args[0] for call in mock_log.call_args_list
        )

    from lib.twitch.auth import load_token

    assert load_token(addon) is None
    assert win.window.getControl(LiveStreamsView.ERROR_LABEL_ID).getLabel() != ""


def test_oninit_shows_error_state_on_network_failure():
    import requests

    addon = _addon_with_token({"access_token": "tok", "refresh_token": "ref", "user_id": "u1"})
    with patch("xbmcaddon.Addon", return_value=addon), patch.object(
        api, "get_followed_channels", side_effect=requests.ConnectionError("boom")
    ):
        window = FakeWindow()
        win = LiveStreamsView(window)
        win.activate()
    assert win.window.getControl(LiveStreamsView.ERROR_LABEL_ID).getLabel() != ""
    # The error message is only useful if the group stays visible - so the
    # error state stays on Live Streams and offers the re-login button
    # instead of bouncing to Menu.
    assert window.switched_to == []
    assert win.window.getControl(LiveStreamsView.RELOGIN_BUTTON_ID).isVisible() is True
    assert window.getFocusId() == LiveStreamsView.RELOGIN_BUTTON_ID


def test_selecting_the_relogin_button_switches_to_the_login_view():
    window = FakeWindow()
    win = LiveStreamsView(window)
    window.setFocusId(LiveStreamsView.RELOGIN_BUTTON_ID)
    win.handle_action(xbmcgui.Action(xbmcgui.ACTION_SELECT_ITEM))
    assert window.switched_to == ["login"]


def test_successful_load_hides_a_stale_relogin_button():
    addon = _addon_with_token({"access_token": "tok", "refresh_token": "ref", "user_id": "u1"})
    window = FakeWindow()
    win = LiveStreamsView(window)
    win._show_error("boom")
    assert window.getControl(LiveStreamsView.RELOGIN_BUTTON_ID).isVisible() is True

    with patch("xbmcaddon.Addon", return_value=addon), patch.object(
        api, "get_followed_channels", return_value=FOLLOWED
    ), patch.object(api, "get_live_status", return_value=LIVE), patch.object(
        gql, "get_followed_live_games", return_value=[]
    ):
        win.activate()

    assert window.getControl(LiveStreamsView.RELOGIN_BUTTON_ID).isVisible() is False
    assert window.getFocusId() == LiveStreamsView.CHANNEL_LIST_ID


def test_oninit_shows_relogin_when_token_has_no_user_id():
    # Tokens saved by the already-shipped device-code-login feature, before
    # this plan added user_id/login/display_name caching, have no user_id
    # key. activate() must treat that as needing re-login rather than
    # crashing with a swallowed KeyError that reports a misleading network
    # error.
    addon = _addon_with_token({"access_token": "tok", "refresh_token": "ref"})
    with patch("xbmcaddon.Addon", return_value=addon):
        win = LiveStreamsView(FakeWindow())
        win.activate()

    from lib.twitch.auth import load_token

    assert load_token(addon) is None
    assert win.window.getControl(LiveStreamsView.ERROR_LABEL_ID).getLabel() != ""


def test_oninit_saves_refreshed_token_even_if_retry_hits_network_error():
    # Refresh tokens are single-use: once refresh_access_token succeeds, the
    # old refresh_token is dead. The new token must be persisted even if the
    # subsequent retry call fails with a transient (non-401) network error,
    # otherwise the next launch's refresh attempt would fail outright.
    import requests

    old_token = {"access_token": "old", "refresh_token": "ref", "user_id": "u1", "login": "x", "display_name": "X"}
    new_token = {"access_token": "new", "refresh_token": "ref2"}
    addon = _addon_with_token(old_token)

    def fake_get_followed(access_token, client_id, user_id):
        if access_token == "old":
            raise api.TokenExpiredError()
        raise requests.ConnectionError("boom")

    with patch("xbmcaddon.Addon", return_value=addon), patch.object(
        api, "get_followed_channels", side_effect=fake_get_followed
    ), patch("lib.views.live_streams_view.auth.refresh_access_token", return_value=new_token):
        win = LiveStreamsView(FakeWindow())
        win.activate()

    from lib.twitch.auth import load_token

    saved = load_token(addon)
    assert saved is not None
    assert saved["access_token"] == "new"
    assert saved["refresh_token"] == "ref2"


GAMES = [
    {"id": "10", "name": "just-chatting", "displayName": "Just Chatting"},
    {"id": "20", "name": "programming", "displayName": "Programming"},
]


def test_oninit_populates_games_row_with_all_plus_followed_games():
    addon = _addon_with_token({"access_token": "tok", "refresh_token": "ref", "user_id": "u1"})
    with patch("xbmcaddon.Addon", return_value=addon), patch.object(
        api, "get_followed_channels", return_value=FOLLOWED
    ), patch.object(api, "get_live_status", return_value=LIVE), patch.object(
        gql, "get_followed_live_games", return_value=GAMES
    ):
        win = LiveStreamsView(FakeWindow())
        win.activate()
    games_control = win.window.getControl(LiveStreamsView.GAMES_LIST_ID)
    assert games_control.size() == 3
    labels = [games_control._items[i].getLabel() for i in range(games_control.size())]
    assert labels == ["All", "Just Chatting", "Programming"]


def test_oninit_games_row_empty_when_gql_fails():
    addon = _addon_with_token({"access_token": "tok", "refresh_token": "ref", "user_id": "u1"})
    with patch("xbmcaddon.Addon", return_value=addon), patch.object(
        api, "get_followed_channels", return_value=FOLLOWED
    ), patch.object(api, "get_live_status", return_value=LIVE), patch.object(
        gql, "get_followed_live_games", return_value=[]
    ):
        win = LiveStreamsView(FakeWindow())
        win.activate()
    games_control = win.window.getControl(LiveStreamsView.GAMES_LIST_ID)
    assert games_control.size() == 1
    assert games_control._items[0].getLabel() == "All"
    channel_control = win.window.getControl(LiveStreamsView.CHANNEL_LIST_ID)
    assert channel_control.size() == 2


def test_selecting_a_game_filters_channel_list_to_matching_live_channels():
    addon = _addon_with_token({"access_token": "tok", "refresh_token": "ref", "user_id": "u1"})
    with patch("xbmcaddon.Addon", return_value=addon), patch.object(
        api, "get_followed_channels", return_value=FOLLOWED
    ), patch.object(api, "get_live_status", return_value=LIVE), patch.object(
        gql, "get_followed_live_games", return_value=GAMES
    ):
        win = LiveStreamsView(FakeWindow())
        win.activate()
        games_control = win.window.getControl(LiveStreamsView.GAMES_LIST_ID)
        games_control.selectItem(1)  # "Just Chatting" (Bob, per LIVE fixture)
        win.window.setFocusId(LiveStreamsView.GAMES_LIST_ID)
        win.handle_action(xbmcgui.Action(xbmcgui.ACTION_SELECT_ITEM))

    channel_control = win.window.getControl(LiveStreamsView.CHANNEL_LIST_ID)
    assert channel_control.size() == 1
    assert channel_control._items[0].getLabel() == "Bob"


def test_selecting_all_clears_the_filter():
    # Select a game with zero live matches first, so the "no matches"
    # message is showing, then select "All" - both the channel list and the
    # stale empty-label message must be cleared/reset.
    addon = _addon_with_token({"access_token": "tok", "refresh_token": "ref", "user_id": "u1"})
    games_with_unmatched = GAMES + [{"id": "30", "name": "some-other-game", "displayName": "Some Other Game"}]
    with patch("xbmcaddon.Addon", return_value=addon), patch.object(
        api, "get_followed_channels", return_value=FOLLOWED
    ), patch.object(api, "get_live_status", return_value=LIVE), patch.object(
        gql, "get_followed_live_games", return_value=games_with_unmatched
    ):
        win = LiveStreamsView(FakeWindow())
        win.activate()
        games_control = win.window.getControl(LiveStreamsView.GAMES_LIST_ID)
        games_control.selectItem(3)  # "Some Other Game" - no live matches
        win.window.setFocusId(LiveStreamsView.GAMES_LIST_ID)
        win.handle_action(xbmcgui.Action(xbmcgui.ACTION_SELECT_ITEM))
        assert win.window.getControl(LiveStreamsView.EMPTY_LABEL_ID).getLabel() != ""
        games_control.selectItem(0)  # "All"
        win.handle_action(xbmcgui.Action(xbmcgui.ACTION_SELECT_ITEM))

    channel_control = win.window.getControl(LiveStreamsView.CHANNEL_LIST_ID)
    assert channel_control.size() == 2
    assert win.window.getControl(LiveStreamsView.EMPTY_LABEL_ID).getLabel() == ""


def test_show_error_resets_stale_channel_list_and_empty_label():
    # activate() can re-fire (Kodi re-initializes windows). If a prior
    # activate() successfully populated the channel list and a later one
    # hits an error path, the error screen must not show a stale populated
    # channel list underneath the error message.
    addon = _addon_with_token({"access_token": "tok", "refresh_token": "ref", "user_id": "u1"})
    with patch("xbmcaddon.Addon", return_value=addon), patch.object(
        api, "get_followed_channels", return_value=FOLLOWED
    ), patch.object(api, "get_live_status", return_value=LIVE), patch.object(
        gql, "get_followed_live_games", return_value=[]
    ):
        win = LiveStreamsView(FakeWindow())
        win.activate()

    assert win.window.getControl(LiveStreamsView.CHANNEL_LIST_ID).size() == 2

    with patch("xbmcaddon.Addon", return_value=addon), patch.object(
        api, "get_followed_channels", side_effect=api.TokenExpiredError()
    ), patch("lib.views.live_streams_view.auth.refresh_access_token", return_value=None):
        win.activate()

    assert win.window.getControl(LiveStreamsView.CHANNEL_LIST_ID).size() == 0
    assert win.window.getControl(LiveStreamsView.EMPTY_LABEL_ID).getLabel() == ""
    assert win.window.getControl(LiveStreamsView.ERROR_LABEL_ID).getLabel() != ""


def test_selecting_a_game_with_no_live_matches_shows_no_matches_message():
    addon = _addon_with_token({"access_token": "tok", "refresh_token": "ref", "user_id": "u1"})
    games_with_unmatched = GAMES + [{"id": "30", "name": "some-other-game", "displayName": "Some Other Game"}]
    with patch("xbmcaddon.Addon", return_value=addon), patch.object(
        api, "get_followed_channels", return_value=FOLLOWED
    ), patch.object(api, "get_live_status", return_value=LIVE), patch.object(
        gql, "get_followed_live_games", return_value=games_with_unmatched
    ):
        win = LiveStreamsView(FakeWindow())
        win.activate()
        games_control = win.window.getControl(LiveStreamsView.GAMES_LIST_ID)
        games_control.selectItem(3)  # "Some Other Game" - no live followed channel plays it
        win.window.setFocusId(LiveStreamsView.GAMES_LIST_ID)
        win.handle_action(xbmcgui.Action(xbmcgui.ACTION_SELECT_ITEM))

    channel_control = win.window.getControl(LiveStreamsView.CHANNEL_LIST_ID)
    assert channel_control.size() == 0
    assert win.window.getControl(LiveStreamsView.EMPTY_LABEL_ID).getLabel() != ""


def test_build_list_item_live_sets_broadcaster_login_and_is_live_true():
    channel = FOLLOWED[1]  # Bob, broadcaster_login "bob"
    stream_data = LIVE[0]
    item = _build_list_item(channel, stream_data)
    assert item.getProperty("broadcaster_login") == "bob"
    assert item.getProperty("is_live") == "true"


def test_selecting_a_live_channel_plays_it():
    addon = _addon_with_token({"access_token": "tok", "refresh_token": "ref", "user_id": "u1"})
    with patch("xbmcaddon.Addon", return_value=addon), patch.object(
        api, "get_followed_channels", return_value=FOLLOWED
    ), patch.object(api, "get_live_status", return_value=LIVE), patch.object(
        gql, "get_followed_live_games", return_value=[]
    ), patch.object(
        providers, "resolve_stream_url", return_value="https://example.invalid/stream.m3u8"
    ) as mock_resolve, patch(
        "lib.views.live_streams_view.player.play_stream", return_value=True
    ) as mock_play:
        win = LiveStreamsView(FakeWindow())
        win.activate()
        channel_control = win.window.getControl(LiveStreamsView.CHANNEL_LIST_ID)
        # LIVE-first order per _merge_channels: Carol (200 viewers) then Bob (50).
        channel_control.selectItem(0)  # Carol, live
        win.window.setFocusId(LiveStreamsView.CHANNEL_LIST_ID)
        win.handle_action(xbmcgui.Action(xbmcgui.ACTION_SELECT_ITEM))

    mock_resolve.assert_called_once()
    call_args = mock_resolve.call_args
    assert call_args.args[1] == "twitch"
    assert call_args.args[2] == "carol"
    mock_play.assert_called_once_with(
        "https://example.invalid/stream.m3u8",
        "carol",
        platform="twitch",
        access_token="tok",
        client_id="",
        user_id="u1",
    )


def test_selecting_a_live_channel_shows_error_when_resolution_fails():
    addon = _addon_with_token({"access_token": "tok", "refresh_token": "ref", "user_id": "u1"})
    with patch("xbmcaddon.Addon", return_value=addon), patch.object(
        api, "get_followed_channels", return_value=FOLLOWED
    ), patch.object(api, "get_live_status", return_value=LIVE), patch.object(
        gql, "get_followed_live_games", return_value=[]
    ), patch.object(
        providers, "resolve_stream_url", side_effect=providers.StreamUnavailableError("carol"),
    ):
        win = LiveStreamsView(FakeWindow())
        win.activate()
        channel_control = win.window.getControl(LiveStreamsView.CHANNEL_LIST_ID)
        channel_control.selectItem(0)
        win.window.setFocusId(LiveStreamsView.CHANNEL_LIST_ID)
        win.handle_action(xbmcgui.Action(xbmcgui.ACTION_SELECT_ITEM))

    assert win.window.getControl(LiveStreamsView.ERROR_LABEL_ID).getLabel() != ""
    assert win.window.getControl(LiveStreamsView.CHANNEL_LIST_ID).size() == 2


def test_selecting_a_live_channel_shows_error_when_playback_declined():
    addon = _addon_with_token({"access_token": "tok", "refresh_token": "ref", "user_id": "u1"})
    with patch("xbmcaddon.Addon", return_value=addon), patch.object(
        api, "get_followed_channels", return_value=FOLLOWED
    ), patch.object(api, "get_live_status", return_value=LIVE), patch.object(
        gql, "get_followed_live_games", return_value=[]
    ), patch.object(
        providers, "resolve_stream_url", return_value="https://example.invalid/stream.m3u8"
    ), patch("lib.views.live_streams_view.player.play_stream", return_value=False):
        win = LiveStreamsView(FakeWindow())
        win.activate()
        channel_control = win.window.getControl(LiveStreamsView.CHANNEL_LIST_ID)
        channel_control.selectItem(0)
        win.window.setFocusId(LiveStreamsView.CHANNEL_LIST_ID)
        win.handle_action(xbmcgui.Action(xbmcgui.ACTION_SELECT_ITEM))

    assert win.window.getControl(LiveStreamsView.ERROR_LABEL_ID).getLabel() != ""


def test_populate_clears_stale_playback_error_on_next_populate():
    # A playback failure sets the error label; the next time the channel list
    # is rebuilt (e.g. re-selecting "All" in the games filter), the stale
    # error must be cleared rather than sticking around for the rest of the
    # session.
    addon = _addon_with_token({"access_token": "tok", "refresh_token": "ref", "user_id": "u1"})
    with patch("xbmcaddon.Addon", return_value=addon), patch.object(
        api, "get_followed_channels", return_value=FOLLOWED
    ), patch.object(api, "get_live_status", return_value=LIVE), patch.object(
        gql, "get_followed_live_games", return_value=GAMES
    ), patch.object(
        providers, "resolve_stream_url", side_effect=providers.StreamUnavailableError("carol"),
    ):
        win = LiveStreamsView(FakeWindow())
        win.activate()
        channel_control = win.window.getControl(LiveStreamsView.CHANNEL_LIST_ID)
        channel_control.selectItem(0)
        win.window.setFocusId(LiveStreamsView.CHANNEL_LIST_ID)
        win.handle_action(xbmcgui.Action(xbmcgui.ACTION_SELECT_ITEM))

    assert win.window.getControl(LiveStreamsView.ERROR_LABEL_ID).getLabel() != ""

    games_control = win.window.getControl(LiveStreamsView.GAMES_LIST_ID)
    games_control.selectItem(0)  # "All"
    win.window.setFocusId(LiveStreamsView.GAMES_LIST_ID)
    win.handle_action(xbmcgui.Action(xbmcgui.ACTION_SELECT_ITEM))

    assert win.window.getControl(LiveStreamsView.ERROR_LABEL_ID).getLabel() == ""


def test_selecting_a_live_channel_clears_stale_error_on_successful_retry():
    addon = _addon_with_token({"access_token": "tok", "refresh_token": "ref", "user_id": "u1"})
    with patch("xbmcaddon.Addon", return_value=addon), patch.object(
        api, "get_followed_channels", return_value=FOLLOWED
    ), patch.object(api, "get_live_status", return_value=LIVE), patch.object(
        gql, "get_followed_live_games", return_value=[]
    ), patch.object(
        providers, "resolve_stream_url", side_effect=providers.StreamUnavailableError("carol"),
    ):
        win = LiveStreamsView(FakeWindow())
        win.activate()
        channel_control = win.window.getControl(LiveStreamsView.CHANNEL_LIST_ID)
        channel_control.selectItem(0)
        win.window.setFocusId(LiveStreamsView.CHANNEL_LIST_ID)
        win.handle_action(xbmcgui.Action(xbmcgui.ACTION_SELECT_ITEM))

    assert win.window.getControl(LiveStreamsView.ERROR_LABEL_ID).getLabel() != ""

    with patch("xbmcaddon.Addon", return_value=addon), patch.object(
        providers, "resolve_stream_url", return_value="https://example.invalid/stream.m3u8"
    ), patch("lib.views.live_streams_view.player.play_stream", return_value=True):
        win.handle_action(xbmcgui.Action(xbmcgui.ACTION_SELECT_ITEM))

    assert win.window.getControl(LiveStreamsView.ERROR_LABEL_ID).getLabel() == ""


def test_selecting_a_live_channel_shows_error_on_unexpected_exception():
    addon = _addon_with_token({"access_token": "tok", "refresh_token": "ref", "user_id": "u1"})
    with patch("xbmcaddon.Addon", return_value=addon), patch.object(
        api, "get_followed_channels", return_value=FOLLOWED
    ), patch.object(api, "get_live_status", return_value=LIVE), patch.object(
        gql, "get_followed_live_games", return_value=[]
    ), patch.object(providers, "resolve_stream_url", side_effect=RuntimeError("boom")):
        win = LiveStreamsView(FakeWindow())
        win.activate()
        channel_control = win.window.getControl(LiveStreamsView.CHANNEL_LIST_ID)
        channel_control.selectItem(0)
        win.window.setFocusId(LiveStreamsView.CHANNEL_LIST_ID)
        win.handle_action(xbmcgui.Action(xbmcgui.ACTION_SELECT_ITEM))

    assert win.window.getControl(LiveStreamsView.ERROR_LABEL_ID).getLabel() != ""
    assert win.window.getControl(LiveStreamsView.CHANNEL_LIST_ID).size() == 2


def test_missing_token_at_click_time_shows_an_error_instead_of_no_op():
    from lib.twitch.auth import clear_token

    addon = _addon_with_token({"access_token": "tok", "refresh_token": "ref", "user_id": "u1"})
    with patch("xbmcaddon.Addon", return_value=addon), patch.object(
        api, "get_followed_channels", return_value=FOLLOWED
    ), patch.object(api, "get_live_status", return_value=LIVE), patch.object(
        gql, "get_followed_live_games", return_value=[]
    ):
        win = LiveStreamsView(FakeWindow())
        win.activate()
        # Another window cleared the token between activate() and the click.
        clear_token(addon)
        channel_control = win.window.getControl(LiveStreamsView.CHANNEL_LIST_ID)
        channel_control.selectItem(0)
        win.window.setFocusId(LiveStreamsView.CHANNEL_LIST_ID)
        win.handle_action(xbmcgui.Action(xbmcgui.ACTION_SELECT_ITEM))

    assert win.window.getControl(LiveStreamsView.ERROR_LABEL_ID).getLabel() != ""
    assert win.window.getControl(LiveStreamsView.CHANNEL_LIST_ID).size() == 2


from lib import providers


KICK_LIVE_FAVORITE = {
    "platform": "kick",
    "id": "42",
    "login": "kickchannel",
    "display_name": "kickchannel",
    "is_live": True,
    "viewer_count": 120,
    "game_name": "Slots",
    "thumbnail_url": "https://example.invalid/kickthumb.jpg",
}


def test_oninit_merges_kick_favorites_into_the_channel_list():
    # Twitch live: Carol (200), Bob (50). Kick live favorite: 120 viewers.
    # Interleaved by viewer count: Carol (200), kickchannel (120), Bob (50).
    addon = _addon_with_token({"access_token": "tok", "refresh_token": "ref", "user_id": "u1"})
    with patch("xbmcaddon.Addon", return_value=addon), patch.object(
        api, "get_followed_channels", return_value=FOLLOWED
    ), patch.object(api, "get_live_status", return_value=LIVE), patch.object(
        gql, "get_followed_live_games", return_value=[]
    ), patch.object(
        providers, "get_kick_live_favorites", return_value=[KICK_LIVE_FAVORITE]
    ):
        win = LiveStreamsView(FakeWindow())
        win.activate()

    channel_control = win.window.getControl(LiveStreamsView.CHANNEL_LIST_ID)
    logins = [
        channel_control.getListItem(i).getProperty("broadcaster_login")
        for i in range(channel_control.size())
    ]
    platforms = [
        channel_control.getListItem(i).getProperty("platform")
        for i in range(channel_control.size())
    ]
    assert logins[:3] == ["carol", "kickchannel", "bob"]
    assert platforms[:3] == ["twitch", "kick", "twitch"]


def test_oninit_shows_kick_favorites_alone_when_no_twitch_channels_are_live():
    addon = _addon_with_token({"access_token": "tok", "refresh_token": "ref", "user_id": "u1"})
    with patch("xbmcaddon.Addon", return_value=addon), patch.object(
        api, "get_followed_channels", return_value=[]
    ), patch.object(api, "get_live_status", return_value=[]), patch.object(
        gql, "get_followed_live_games", return_value=[]
    ), patch.object(
        providers, "get_kick_live_favorites", return_value=[KICK_LIVE_FAVORITE]
    ):
        win = LiveStreamsView(FakeWindow())
        win.activate()

    channel_control = win.window.getControl(LiveStreamsView.CHANNEL_LIST_ID)
    assert channel_control.size() == 1
    assert channel_control.getListItem(0).getProperty("broadcaster_login") == "kickchannel"
    assert win.window.getControl(LiveStreamsView.EMPTY_LABEL_ID).getLabel() == ""


def test_oninit_shows_empty_message_when_no_twitch_followed_and_no_kick_favorites():
    addon = _addon_with_token({"access_token": "tok", "refresh_token": "ref", "user_id": "u1"})
    with patch("xbmcaddon.Addon", return_value=addon), patch.object(
        api, "get_followed_channels", return_value=[]
    ), patch.object(api, "get_live_status", return_value=[]), patch.object(
        gql, "get_followed_live_games", return_value=[]
    ), patch.object(providers, "get_kick_live_favorites", return_value=[]):
        win = LiveStreamsView(FakeWindow())
        win.activate()

    assert win.window.getControl(LiveStreamsView.EMPTY_LABEL_ID).getLabel() != ""


def test_selecting_a_game_filter_hides_kick_favorites():
    # The games filter is Twitch-only - Kick has no equivalent taxonomy, so
    # selecting a specific game hides Kick results rather than showing them
    # unfiltered alongside a filtered Twitch list (documented spec decision).
    addon = _addon_with_token({"access_token": "tok", "refresh_token": "ref", "user_id": "u1"})
    with patch("xbmcaddon.Addon", return_value=addon), patch.object(
        api, "get_followed_channels", return_value=FOLLOWED
    ), patch.object(api, "get_live_status", return_value=LIVE), patch.object(
        gql, "get_followed_live_games", return_value=GAMES
    ), patch.object(
        providers, "get_kick_live_favorites", return_value=[KICK_LIVE_FAVORITE]
    ):
        win = LiveStreamsView(FakeWindow())
        win.activate()
        games_control = win.window.getControl(LiveStreamsView.GAMES_LIST_ID)
        # GAMES[0]["displayName"] must be "Programming" (Carol's game) for
        # this assertion to isolate her alone - see GAMES' definition.
        for i in range(games_control.size()):
            if games_control.getListItem(i).getProperty("game_name") == "Programming":
                games_control.selectItem(i)
                break
        win.window.setFocusId(LiveStreamsView.GAMES_LIST_ID)
        win.handle_action(xbmcgui.Action(xbmcgui.ACTION_SELECT_ITEM))

    channel_control = win.window.getControl(LiveStreamsView.CHANNEL_LIST_ID)
    logins = [
        channel_control.getListItem(i).getProperty("broadcaster_login")
        for i in range(channel_control.size())
    ]
    assert "kickchannel" not in logins


def test_selecting_a_live_kick_channel_plays_it():
    addon = _addon_with_token({"access_token": "tok", "refresh_token": "ref", "user_id": "u1"})
    with patch("xbmcaddon.Addon", return_value=addon), patch.object(
        api, "get_followed_channels", return_value=[]
    ), patch.object(api, "get_live_status", return_value=[]), patch.object(
        gql, "get_followed_live_games", return_value=[]
    ), patch.object(
        providers, "get_kick_live_favorites", return_value=[KICK_LIVE_FAVORITE]
    ), patch.object(
        providers, "resolve_stream_url", return_value="https://kick.example/x.m3u8"
    ) as mock_resolve, patch(
        "lib.views.live_streams_view.player.play_stream", return_value=True
    ) as mock_play:
        win = LiveStreamsView(FakeWindow())
        win.activate()
        channel_control = win.window.getControl(LiveStreamsView.CHANNEL_LIST_ID)
        channel_control.selectItem(0)
        win.window.setFocusId(LiveStreamsView.CHANNEL_LIST_ID)
        win.handle_action(xbmcgui.Action(xbmcgui.ACTION_SELECT_ITEM))

    mock_resolve.assert_called_once()
    call_args = mock_resolve.call_args
    assert call_args.args[1] == "kick"
    assert call_args.args[2] == "kickchannel"
    mock_play.assert_called_once_with(
        "https://kick.example/x.m3u8", "kickchannel", platform="kick"
    )


def test_selecting_a_live_kick_channel_shows_error_when_resolution_fails():
    addon = _addon_with_token({"access_token": "tok", "refresh_token": "ref", "user_id": "u1"})
    with patch("xbmcaddon.Addon", return_value=addon), patch.object(
        api, "get_followed_channels", return_value=[]
    ), patch.object(api, "get_live_status", return_value=[]), patch.object(
        gql, "get_followed_live_games", return_value=[]
    ), patch.object(
        providers, "get_kick_live_favorites", return_value=[KICK_LIVE_FAVORITE]
    ), patch.object(
        providers, "resolve_stream_url", side_effect=providers.StreamUnavailableError("x")
    ):
        win = LiveStreamsView(FakeWindow())
        win.activate()
        channel_control = win.window.getControl(LiveStreamsView.CHANNEL_LIST_ID)
        channel_control.selectItem(0)
        win.window.setFocusId(LiveStreamsView.CHANNEL_LIST_ID)
        win.handle_action(xbmcgui.Action(xbmcgui.ACTION_SELECT_ITEM))

    assert win.window.getControl(LiveStreamsView.ERROR_LABEL_ID).getLabel() != ""


def test_context_menu_on_kick_result_removes_favorite_and_refreshes_list():
    addon = _addon_with_token({"access_token": "tok", "refresh_token": "ref", "user_id": "u1"})
    providers.add_kick_favorite(addon, "kickchannel")
    xbmcgui.Dialog.next_contextmenu_choice = 0
    xbmcgui.Dialog.notifications = []
    with patch("xbmcaddon.Addon", return_value=addon), patch.object(
        api, "get_followed_channels", return_value=FOLLOWED
    ), patch.object(api, "get_live_status", return_value=LIVE), patch.object(
        gql, "get_followed_live_games", return_value=[]
    ), patch.object(
        providers, "get_kick_live_favorites", side_effect=lambda a: (
            [KICK_LIVE_FAVORITE] if "kickchannel" in providers.get_kick_favorites(a) else []
        )
    ):
        win = LiveStreamsView(FakeWindow())
        win.activate()
        channel_control = win.window.getControl(LiveStreamsView.CHANNEL_LIST_ID)
        channel_control.selectItem(1)  # kickchannel, per the interleave-order test above
        win.window.setFocusId(LiveStreamsView.CHANNEL_LIST_ID)
        win.handle_action(xbmcgui.Action(xbmcgui.ACTION_CONTEXT_MENU))

    assert providers.get_kick_favorites(addon) == []
    logins = [
        channel_control.getListItem(i).getProperty("broadcaster_login")
        for i in range(channel_control.size())
    ]
    assert "kickchannel" not in logins


def test_context_menu_on_twitch_result_does_nothing():
    addon = _addon_with_token({"access_token": "tok", "refresh_token": "ref", "user_id": "u1"})
    xbmcgui.Dialog.next_contextmenu_choice = 0
    xbmcgui.Dialog.notifications = []
    with patch("xbmcaddon.Addon", return_value=addon), patch.object(
        api, "get_followed_channels", return_value=FOLLOWED
    ), patch.object(api, "get_live_status", return_value=LIVE), patch.object(
        gql, "get_followed_live_games", return_value=[]
    ), patch.object(providers, "get_kick_live_favorites", return_value=[]):
        win = LiveStreamsView(FakeWindow())
        win.activate()
        channel_control = win.window.getControl(LiveStreamsView.CHANNEL_LIST_ID)
        channel_control.selectItem(0)  # carol, twitch
        win.window.setFocusId(LiveStreamsView.CHANNEL_LIST_ID)
        win.handle_action(xbmcgui.Action(xbmcgui.ACTION_CONTEXT_MENU))

    assert providers.get_kick_favorites(addon) == []
    assert xbmcgui.Dialog.notifications == []
