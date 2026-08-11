from unittest.mock import patch

import xbmcaddon
import xbmcgui

from lib.twitch import api, gql
from lib.twitch.auth import save_token
from lib.windows.discover import DiscoverWindow
from lib.windows.home import HomeWindow, _build_list_item, _merge_channels
from lib.windows.login import LoginWindow
from lib.twitch import stream

FakeAddon = xbmcaddon.Addon


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


def test_build_list_item_offline_has_no_thumbnail():
    channel = FOLLOWED[0]
    item = _build_list_item(channel, None)
    assert item.getLabel() == "Alice"
    assert item.getLabel2() == "Offline"
    assert item.getArt("thumb") == ""


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
        win = HomeWindow("script-twitch-center-home.xml", "/tmp")
        win.onInit()
    control = win.getControl(HomeWindow.CHANNEL_LIST_ID)
    assert control.size() == 3


def test_oninit_sets_title_with_addon_version():
    addon = _addon_with_token({"access_token": "tok", "refresh_token": "ref", "user_id": "u1"})
    with patch("xbmcaddon.Addon", return_value=addon), patch.object(
        api, "get_followed_channels", return_value=[]
    ), patch.object(api, "get_live_status", return_value=[]), patch.object(
        gql, "get_followed_live_games", return_value=[]
    ):
        win = HomeWindow("script-twitch-center-home.xml", "/tmp")
        win.onInit()
    title = win.getControl(HomeWindow.TITLE_LABEL_ID).getLabel()
    assert title.startswith("Twitch Center v")
    assert addon.getAddonInfo("version") in title


def test_oninit_shows_empty_state_when_no_followed_channels():
    addon = _addon_with_token({"access_token": "tok", "refresh_token": "ref", "user_id": "u1"})
    with patch("xbmcaddon.Addon", return_value=addon), patch.object(
        api, "get_followed_channels", return_value=[]
    ), patch.object(api, "get_live_status", return_value=[]), patch.object(
        gql, "get_followed_live_games", return_value=[]
    ):
        win = HomeWindow("script-twitch-center-home.xml", "/tmp")
        win.onInit()
    assert win.getControl(HomeWindow.EMPTY_LABEL_ID).getLabel() != ""
    assert win.getControl(HomeWindow.CHANNEL_LIST_ID).size() == 0


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
        "lib.windows.home.auth.refresh_access_token", return_value=new_token
    ):
        win = HomeWindow("script-twitch-center-home.xml", "/tmp")
        win.onInit()

    assert call_count["n"] == 2
    assert win.getControl(HomeWindow.CHANNEL_LIST_ID).size() == 3
    from lib.twitch.auth import load_token

    saved = load_token(addon)
    assert saved["access_token"] == "new"
    assert saved["user_id"] == "u1"  # preserved from the old token


def test_oninit_shows_relogin_prompt_when_refresh_fails():
    old_token = {"access_token": "old", "refresh_token": "ref", "user_id": "u1"}
    addon = _addon_with_token(old_token)

    with patch("xbmcaddon.Addon", return_value=addon), patch.object(
        api, "get_followed_channels", side_effect=api.TokenExpiredError()
    ), patch("lib.windows.home.auth.refresh_access_token", return_value=None):
        win = HomeWindow("script-twitch-center-home.xml", "/tmp")
        win.onInit()

    from lib.twitch.auth import load_token

    assert load_token(addon) is None
    assert win.getControl(HomeWindow.ERROR_LABEL_ID).getLabel() != ""


def test_oninit_shows_error_state_on_network_failure():
    import requests

    addon = _addon_with_token({"access_token": "tok", "refresh_token": "ref", "user_id": "u1"})
    with patch("xbmcaddon.Addon", return_value=addon), patch.object(
        api, "get_followed_channels", side_effect=requests.ConnectionError("boom")
    ):
        win = HomeWindow("script-twitch-center-home.xml", "/tmp")
        win.onInit()
    assert win.getControl(HomeWindow.ERROR_LABEL_ID).getLabel() != ""


def test_oninit_shows_relogin_when_token_has_no_user_id():
    # Tokens saved by the already-shipped device-code-login feature, before
    # this plan added user_id/login/display_name caching, have no user_id
    # key. onInit must treat that as needing re-login rather than crashing
    # with a swallowed KeyError that reports a misleading network error.
    addon = _addon_with_token({"access_token": "tok", "refresh_token": "ref"})
    with patch("xbmcaddon.Addon", return_value=addon):
        win = HomeWindow("script-twitch-center-home.xml", "/tmp")
        win.onInit()

    from lib.twitch.auth import load_token

    assert load_token(addon) is None
    assert win.getControl(HomeWindow.ERROR_LABEL_ID).getLabel() != ""
    assert win.getControl(HomeWindow.RELOGIN_BUTTON_ID).isVisible() is True


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
    ), patch("lib.windows.home.auth.refresh_access_token", return_value=new_token):
        win = HomeWindow("script-twitch-center-home.xml", "/tmp")
        win.onInit()

    from lib.twitch.auth import load_token

    saved = load_token(addon)
    assert saved is not None
    assert saved["access_token"] == "new"
    assert saved["refresh_token"] == "ref2"


def test_populate_hides_relogin_button_on_success():
    addon = _addon_with_token({"access_token": "tok", "refresh_token": "ref", "user_id": "u1"})
    with patch("xbmcaddon.Addon", return_value=addon), patch.object(
        api, "get_followed_channels", return_value=FOLLOWED
    ), patch.object(api, "get_live_status", return_value=LIVE), patch.object(
        gql, "get_followed_live_games", return_value=[]
    ):
        win = HomeWindow("script-twitch-center-home.xml", "/tmp")
        win.onInit()
    assert win.getControl(HomeWindow.RELOGIN_BUTTON_ID).isVisible() is False


def test_relogin_button_visible_when_relogin_prompt_shown():
    old_token = {"access_token": "old", "refresh_token": "ref", "user_id": "u1"}
    addon = _addon_with_token(old_token)

    with patch("xbmcaddon.Addon", return_value=addon), patch.object(
        api, "get_followed_channels", side_effect=api.TokenExpiredError()
    ), patch("lib.windows.home.auth.refresh_access_token", return_value=None):
        win = HomeWindow("script-twitch-center-home.xml", "/tmp")
        win.onInit()

    assert win.getControl(HomeWindow.RELOGIN_BUTTON_ID).isVisible() is True


def test_selecting_relogin_button_opens_login_window_and_closes_home():
    addon = _addon_with_token({"access_token": "old", "refresh_token": "ref", "user_id": "u1"})

    with patch("xbmcaddon.Addon", return_value=addon), patch.object(
        api, "get_followed_channels", side_effect=api.TokenExpiredError()
    ), patch("lib.windows.home.auth.refresh_access_token", return_value=None), patch(
        "lib.windows.home.LoginWindow"
    ) as mock_login_window_cls:
        win = HomeWindow("script-twitch-center-home.xml", "/tmp")
        win.onInit()
        win.setFocusId(HomeWindow.RELOGIN_BUTTON_ID)
        win.onAction(xbmcgui.Action(xbmcgui.ACTION_SELECT_ITEM))

    mock_login_window_cls.assert_called_once()
    assert mock_login_window_cls.call_args.kwargs["closed_event"] is win.closed_event
    mock_login_window_cls.return_value.show.assert_called_once()
    # Handing off to the login window must NOT set the shared event: main.run
    # blocks on it, so setting it here would tear the script (and the just-
    # shown login window) down immediately.
    assert not win.closed_event.is_set()


def test_relogin_chain_sets_the_shared_event_only_when_login_window_closes():
    """The event main.run() waits on must survive Home -> Login navigation and
    end up set when the login window itself finally closes."""
    addon = _addon_with_token({"access_token": "old", "refresh_token": "ref", "user_id": "u1"})

    with patch("xbmcaddon.Addon", return_value=addon), patch.object(
        api, "get_followed_channels", side_effect=api.TokenExpiredError()
    ), patch("lib.windows.home.auth.refresh_access_token", return_value=None):
        win = HomeWindow("script-twitch-center-home.xml", "/tmp")
        shared_event = win.closed_event
        win.onInit()
        win.setFocusId(HomeWindow.RELOGIN_BUTTON_ID)
        win.onAction(xbmcgui.Action(xbmcgui.ACTION_SELECT_ITEM))

        assert not shared_event.is_set()

        login_window = LoginWindow(
            "script-twitch-center-login.xml", "/tmp", closed_event=shared_event
        )
        assert login_window.closed_event is shared_event
        login_window.onAction(xbmcgui.Action(xbmcgui.ACTION_NAV_BACK))

    assert shared_event.is_set()


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
        win = HomeWindow("script-twitch-center-home.xml", "/tmp")
        win.onInit()
    games_control = win.getControl(HomeWindow.GAMES_LIST_ID)
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
        win = HomeWindow("script-twitch-center-home.xml", "/tmp")
        win.onInit()
    games_control = win.getControl(HomeWindow.GAMES_LIST_ID)
    assert games_control.size() == 1
    assert games_control._items[0].getLabel() == "All"
    channel_control = win.getControl(HomeWindow.CHANNEL_LIST_ID)
    assert channel_control.size() == 3


def test_selecting_a_game_filters_channel_list_to_matching_live_channels():
    addon = _addon_with_token({"access_token": "tok", "refresh_token": "ref", "user_id": "u1"})
    with patch("xbmcaddon.Addon", return_value=addon), patch.object(
        api, "get_followed_channels", return_value=FOLLOWED
    ), patch.object(api, "get_live_status", return_value=LIVE), patch.object(
        gql, "get_followed_live_games", return_value=GAMES
    ):
        win = HomeWindow("script-twitch-center-home.xml", "/tmp")
        win.onInit()
        games_control = win.getControl(HomeWindow.GAMES_LIST_ID)
        games_control.selectItem(1)  # "Just Chatting" (Bob, per LIVE fixture)
        win.setFocusId(HomeWindow.GAMES_LIST_ID)
        win.onAction(xbmcgui.Action(xbmcgui.ACTION_SELECT_ITEM))

    channel_control = win.getControl(HomeWindow.CHANNEL_LIST_ID)
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
        win = HomeWindow("script-twitch-center-home.xml", "/tmp")
        win.onInit()
        games_control = win.getControl(HomeWindow.GAMES_LIST_ID)
        games_control.selectItem(3)  # "Some Other Game" - no live matches
        win.setFocusId(HomeWindow.GAMES_LIST_ID)
        win.onAction(xbmcgui.Action(xbmcgui.ACTION_SELECT_ITEM))
        assert win.getControl(HomeWindow.EMPTY_LABEL_ID).getLabel() != ""
        games_control.selectItem(0)  # "All"
        win.onAction(xbmcgui.Action(xbmcgui.ACTION_SELECT_ITEM))

    channel_control = win.getControl(HomeWindow.CHANNEL_LIST_ID)
    assert channel_control.size() == 3
    assert win.getControl(HomeWindow.EMPTY_LABEL_ID).getLabel() == ""


def test_show_error_resets_stale_channel_list_and_empty_label():
    # onInit can re-fire (Kodi re-initializes windows). If a prior onInit
    # successfully populated the channel list and a later one hits an error
    # path, the error screen must not show a stale populated channel list
    # underneath the error message.
    addon = _addon_with_token({"access_token": "tok", "refresh_token": "ref", "user_id": "u1"})
    with patch("xbmcaddon.Addon", return_value=addon), patch.object(
        api, "get_followed_channels", return_value=FOLLOWED
    ), patch.object(api, "get_live_status", return_value=LIVE), patch.object(
        gql, "get_followed_live_games", return_value=[]
    ):
        win = HomeWindow("script-twitch-center-home.xml", "/tmp")
        win.onInit()

    assert win.getControl(HomeWindow.CHANNEL_LIST_ID).size() == 3

    with patch("xbmcaddon.Addon", return_value=addon), patch.object(
        api, "get_followed_channels", side_effect=api.TokenExpiredError()
    ), patch("lib.windows.home.auth.refresh_access_token", return_value=None):
        win.onInit()

    assert win.getControl(HomeWindow.CHANNEL_LIST_ID).size() == 0
    assert win.getControl(HomeWindow.EMPTY_LABEL_ID).getLabel() == ""
    assert win.getControl(HomeWindow.ERROR_LABEL_ID).getLabel() != ""


def test_selecting_a_game_with_no_live_matches_shows_no_matches_message():
    addon = _addon_with_token({"access_token": "tok", "refresh_token": "ref", "user_id": "u1"})
    games_with_unmatched = GAMES + [{"id": "30", "name": "some-other-game", "displayName": "Some Other Game"}]
    with patch("xbmcaddon.Addon", return_value=addon), patch.object(
        api, "get_followed_channels", return_value=FOLLOWED
    ), patch.object(api, "get_live_status", return_value=LIVE), patch.object(
        gql, "get_followed_live_games", return_value=games_with_unmatched
    ):
        win = HomeWindow("script-twitch-center-home.xml", "/tmp")
        win.onInit()
        games_control = win.getControl(HomeWindow.GAMES_LIST_ID)
        games_control.selectItem(3)  # "Some Other Game" - no live followed channel plays it
        win.setFocusId(HomeWindow.GAMES_LIST_ID)
        win.onAction(xbmcgui.Action(xbmcgui.ACTION_SELECT_ITEM))

    channel_control = win.getControl(HomeWindow.CHANNEL_LIST_ID)
    assert channel_control.size() == 0
    assert win.getControl(HomeWindow.EMPTY_LABEL_ID).getLabel() != ""


def test_selecting_discover_button_opens_discover_window_and_closes_home():
    addon = _addon_with_token({"access_token": "tok", "refresh_token": "ref", "user_id": "u1"})

    with patch("xbmcaddon.Addon", return_value=addon), patch.object(
        api, "get_followed_channels", return_value=FOLLOWED
    ), patch.object(api, "get_live_status", return_value=LIVE), patch.object(
        gql, "get_followed_live_games", return_value=[]
    ), patch(
        "lib.windows.home.DiscoverWindow"
    ) as mock_discover_window_cls:
        win = HomeWindow("script-twitch-center-home.xml", "/tmp")
        win.onInit()
        win.setFocusId(HomeWindow.DISCOVER_BUTTON_ID)
        win.onAction(xbmcgui.Action(xbmcgui.ACTION_SELECT_ITEM))

    mock_discover_window_cls.assert_called_once()
    assert mock_discover_window_cls.call_args.kwargs["closed_event"] is win.closed_event
    mock_discover_window_cls.return_value.show.assert_called_once()
    # Handing off, not ending the chain - see the relogin test above.
    assert not win.closed_event.is_set()


def test_discover_chain_sets_the_shared_event_only_when_discover_closes():
    addon = _addon_with_token({"access_token": "tok", "refresh_token": "ref", "user_id": "u1"})

    with patch("xbmcaddon.Addon", return_value=addon), patch.object(
        api, "get_followed_channels", return_value=FOLLOWED
    ), patch.object(api, "get_live_status", return_value=LIVE), patch.object(
        gql, "get_followed_live_games", return_value=[]
    ), patch.object(api, "get_top_games", return_value=[]):
        win = HomeWindow("script-twitch-center-home.xml", "/tmp")
        shared_event = win.closed_event
        win.onInit()
        win.setFocusId(HomeWindow.DISCOVER_BUTTON_ID)
        win.onAction(xbmcgui.Action(xbmcgui.ACTION_SELECT_ITEM))

        assert not shared_event.is_set()

        discover_window = DiscoverWindow(
            "script-twitch-center-discover.xml", "/tmp", closed_event=shared_event
        )
        assert discover_window.closed_event is shared_event
        discover_window.onAction(xbmcgui.Action(xbmcgui.ACTION_NAV_BACK))

    assert shared_event.is_set()


def test_build_list_item_live_sets_broadcaster_login_and_is_live_true():
    channel = FOLLOWED[1]  # Bob, broadcaster_login "bob"
    stream_data = LIVE[0]
    item = _build_list_item(channel, stream_data)
    assert item.getProperty("broadcaster_login") == "bob"
    assert item.getProperty("is_live") == "true"


def test_build_list_item_offline_sets_is_live_false():
    channel = FOLLOWED[0]  # Alice
    item = _build_list_item(channel, None)
    assert item.getProperty("broadcaster_login") == "alice"
    assert item.getProperty("is_live") == "false"


def test_selecting_a_live_channel_plays_it():
    addon = _addon_with_token({"access_token": "tok", "refresh_token": "ref", "user_id": "u1"})
    with patch("xbmcaddon.Addon", return_value=addon), patch.object(
        api, "get_followed_channels", return_value=FOLLOWED
    ), patch.object(api, "get_live_status", return_value=LIVE), patch.object(
        gql, "get_followed_live_games", return_value=[]
    ), patch(
        "lib.windows.home.stream.resolve_stream_url",
        return_value="https://example.invalid/stream.m3u8",
    ) as mock_resolve, patch(
        "lib.windows.home.player.play_stream", return_value=True
    ) as mock_play:
        win = HomeWindow("script-twitch-center-home.xml", "/tmp")
        win.onInit()
        channel_control = win.getControl(HomeWindow.CHANNEL_LIST_ID)
        # LIVE-first order per _merge_channels: Carol (200 viewers) then Bob (50), then offline Alice.
        channel_control.selectItem(0)  # Carol, live
        win.setFocusId(HomeWindow.CHANNEL_LIST_ID)
        win.onAction(xbmcgui.Action(xbmcgui.ACTION_SELECT_ITEM))

    mock_resolve.assert_called_once_with("tok", "carol")
    mock_play.assert_called_once_with("https://example.invalid/stream.m3u8")


def test_selecting_an_offline_channel_does_nothing():
    addon = _addon_with_token({"access_token": "tok", "refresh_token": "ref", "user_id": "u1"})
    with patch("xbmcaddon.Addon", return_value=addon), patch.object(
        api, "get_followed_channels", return_value=FOLLOWED
    ), patch.object(api, "get_live_status", return_value=LIVE), patch.object(
        gql, "get_followed_live_games", return_value=[]
    ):
        win = HomeWindow("script-twitch-center-home.xml", "/tmp")
        win.onInit()
        channel_control = win.getControl(HomeWindow.CHANNEL_LIST_ID)
        channel_control.selectItem(2)  # Carol, Bob, then offline Alice at index 2
        win.setFocusId(HomeWindow.CHANNEL_LIST_ID)
        with patch("lib.windows.home.stream.resolve_stream_url") as mock_resolve:
            win.onAction(xbmcgui.Action(xbmcgui.ACTION_SELECT_ITEM))

    mock_resolve.assert_not_called()


def test_selecting_a_live_channel_shows_error_when_resolution_fails():
    addon = _addon_with_token({"access_token": "tok", "refresh_token": "ref", "user_id": "u1"})
    with patch("xbmcaddon.Addon", return_value=addon), patch.object(
        api, "get_followed_channels", return_value=FOLLOWED
    ), patch.object(api, "get_live_status", return_value=LIVE), patch.object(
        gql, "get_followed_live_games", return_value=[]
    ), patch(
        "lib.windows.home.stream.resolve_stream_url",
        side_effect=stream.StreamUnavailableError("carol"),
    ):
        win = HomeWindow("script-twitch-center-home.xml", "/tmp")
        win.onInit()
        channel_control = win.getControl(HomeWindow.CHANNEL_LIST_ID)
        channel_control.selectItem(0)
        win.setFocusId(HomeWindow.CHANNEL_LIST_ID)
        win.onAction(xbmcgui.Action(xbmcgui.ACTION_SELECT_ITEM))

    assert win.getControl(HomeWindow.ERROR_LABEL_ID).getLabel() != ""
    assert win.getControl(HomeWindow.CHANNEL_LIST_ID).size() == 3


def test_selecting_a_live_channel_shows_error_when_playback_declined():
    addon = _addon_with_token({"access_token": "tok", "refresh_token": "ref", "user_id": "u1"})
    with patch("xbmcaddon.Addon", return_value=addon), patch.object(
        api, "get_followed_channels", return_value=FOLLOWED
    ), patch.object(api, "get_live_status", return_value=LIVE), patch.object(
        gql, "get_followed_live_games", return_value=[]
    ), patch(
        "lib.windows.home.stream.resolve_stream_url",
        return_value="https://example.invalid/stream.m3u8",
    ), patch("lib.windows.home.player.play_stream", return_value=False):
        win = HomeWindow("script-twitch-center-home.xml", "/tmp")
        win.onInit()
        channel_control = win.getControl(HomeWindow.CHANNEL_LIST_ID)
        channel_control.selectItem(0)
        win.setFocusId(HomeWindow.CHANNEL_LIST_ID)
        win.onAction(xbmcgui.Action(xbmcgui.ACTION_SELECT_ITEM))

    assert win.getControl(HomeWindow.ERROR_LABEL_ID).getLabel() != ""


def test_expired_token_during_channel_select_retries_playback_after_refresh():
    old_token = {
        "access_token": "old",
        "refresh_token": "ref",
        "user_id": "u1",
        "login": "x",
        "display_name": "X",
    }
    new_token = {"access_token": "new", "refresh_token": "ref2"}
    addon = _addon_with_token(old_token)

    resolve_calls = []

    def fake_resolve(access_token, broadcaster_login):
        resolve_calls.append((access_token, broadcaster_login))
        if access_token == "old":
            raise api.TokenExpiredError()
        return "https://example.invalid/stream.m3u8"

    with patch("xbmcaddon.Addon", return_value=addon), patch.object(
        api, "get_followed_channels", return_value=FOLLOWED
    ), patch.object(api, "get_live_status", return_value=LIVE), patch.object(
        gql, "get_followed_live_games", return_value=[]
    ), patch(
        "lib.windows.home.stream.resolve_stream_url", side_effect=fake_resolve
    ), patch(
        "lib.windows.home.player.play_stream", return_value=True
    ) as mock_play, patch(
        "lib.windows.home.auth.refresh_access_token", return_value=new_token
    ):
        win = HomeWindow("script-twitch-center-home.xml", "/tmp")
        win.onInit()
        channel_control = win.getControl(HomeWindow.CHANNEL_LIST_ID)
        channel_control.selectItem(0)
        win.setFocusId(HomeWindow.CHANNEL_LIST_ID)
        win.onAction(xbmcgui.Action(xbmcgui.ACTION_SELECT_ITEM))

    assert resolve_calls == [("old", "carol"), ("new", "carol")]
    mock_play.assert_called_once_with("https://example.invalid/stream.m3u8")
