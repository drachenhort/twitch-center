import threading
from unittest.mock import patch

from lib.twitch import stream

import xbmcaddon
import xbmcgui

from lib.twitch import api
from lib.twitch.auth import clear_token, save_token
from lib.windows.discover import (
    DiscoverWindow,
    _build_channel_item,
    _build_stream_item,
)
from lib.windows.login import LoginWindow

FakeAddon = xbmcaddon.Addon

TOP_GAMES = [
    {"id": "509658", "name": "Just Chatting"},
    {"id": "21779", "name": "League of Legends"},
]

STREAMS = [
    {
        "user_id": "1",
        "user_login": "alice",
        "user_name": "Alice",
        "game_name": "Just Chatting",
        "viewer_count": 500,
        "thumbnail_url": "https://example.invalid/{width}x{height}.jpg",
    }
]

SEARCH_RESULTS = [
    {
        "id": "2",
        "broadcaster_login": "bob",
        "display_name": "Bob",
        "game_name": "League of Legends",
        "is_live": True,
        "thumbnail_url": "https://example.invalid/bob.jpg",
    },
    {
        "id": "3",
        "broadcaster_login": "carol",
        "display_name": "Carol",
        "game_name": "",
        "is_live": False,
        "thumbnail_url": "https://example.invalid/carol.jpg",
    },
]


def _addon_with_token(token):
    addon = FakeAddon()
    if token is not None:
        save_token(token, addon)
    return addon


def test_build_stream_item_sets_label2_and_thumbnail():
    item = _build_stream_item(STREAMS[0])
    assert item.getLabel() == "Alice"
    assert "Just Chatting" in item.getLabel2()
    assert "500" in item.getLabel2()
    assert item.getArt("thumb") == "https://example.invalid/320x180.jpg"
    assert item.getProperty("broadcaster_id") == "1"


def test_build_channel_item_live_shows_game_and_live_status():
    item = _build_channel_item(SEARCH_RESULTS[0])
    assert item.getLabel() == "Bob"
    assert "Live" in item.getLabel2()
    assert "League of Legends" in item.getLabel2()
    assert item.getArt("thumb") == "https://example.invalid/bob.jpg"
    assert item.getProperty("broadcaster_id") == "2"


def test_build_channel_item_offline_shows_offline():
    item = _build_channel_item(SEARCH_RESULTS[1])
    assert item.getLabel() == "Carol"
    assert item.getLabel2() == "Offline"


def test_oninit_populates_top_games():
    addon = _addon_with_token({"access_token": "tok", "refresh_token": "ref", "user_id": "u1"})
    with patch("xbmcaddon.Addon", return_value=addon), patch.object(
        api, "get_top_games", return_value=TOP_GAMES
    ):
        win = DiscoverWindow("script-twitch-center-discover.xml", "/tmp")
        win.onInit()
    games_control = win.getControl(DiscoverWindow.GAMES_LIST_ID)
    assert games_control.size() == 2
    labels = [games_control._items[i].getLabel() for i in range(2)]
    assert labels == ["Just Chatting", "League of Legends"]


def test_oninit_shows_relogin_when_no_token():
    addon = FakeAddon()
    with patch("xbmcaddon.Addon", return_value=addon):
        win = DiscoverWindow("script-twitch-center-discover.xml", "/tmp")
        win.onInit()
    assert win.getControl(DiscoverWindow.ERROR_LABEL_ID).getLabel() != ""


def test_oninit_shows_error_on_network_failure():
    import requests

    addon = _addon_with_token({"access_token": "tok", "refresh_token": "ref", "user_id": "u1"})
    with patch("xbmcaddon.Addon", return_value=addon), patch.object(
        api, "get_top_games", side_effect=requests.ConnectionError("boom")
    ):
        win = DiscoverWindow("script-twitch-center-discover.xml", "/tmp")
        win.onInit()
    assert win.getControl(DiscoverWindow.ERROR_LABEL_ID).getLabel() != ""


def test_selecting_a_game_populates_results_with_stream_items():
    addon = _addon_with_token({"access_token": "tok", "refresh_token": "ref", "user_id": "u1"})
    with patch("xbmcaddon.Addon", return_value=addon), patch.object(
        api, "get_top_games", return_value=TOP_GAMES
    ), patch.object(api, "get_live_streams_by_game", return_value=STREAMS):
        win = DiscoverWindow("script-twitch-center-discover.xml", "/tmp")
        win.onInit()
        games_control = win.getControl(DiscoverWindow.GAMES_LIST_ID)
        games_control.selectItem(0)
        win.setFocusId(DiscoverWindow.GAMES_LIST_ID)
        win.onAction(xbmcgui.Action(xbmcgui.ACTION_SELECT_ITEM))

    results_control = win.getControl(DiscoverWindow.RESULTS_LIST_ID)
    assert results_control.size() == 1
    assert results_control._items[0].getLabel() == "Alice"


def test_pressing_search_populates_results_with_channel_items():
    addon = _addon_with_token({"access_token": "tok", "refresh_token": "ref", "user_id": "u1"})
    with patch("xbmcaddon.Addon", return_value=addon), patch.object(
        api, "get_top_games", return_value=TOP_GAMES
    ), patch.object(api, "search_channels", return_value=SEARCH_RESULTS):
        win = DiscoverWindow("script-twitch-center-discover.xml", "/tmp")
        win.onInit()
        win.getControl(DiscoverWindow.SEARCH_EDIT_ID).setText("bob")
        win.setFocusId(DiscoverWindow.SEARCH_BUTTON_ID)
        win.onAction(xbmcgui.Action(xbmcgui.ACTION_SELECT_ITEM))

    results_control = win.getControl(DiscoverWindow.RESULTS_LIST_ID)
    assert results_control.size() == 2
    assert results_control._items[0].getLabel() == "Bob"


def test_pressing_search_with_empty_query_does_nothing():
    addon = _addon_with_token({"access_token": "tok", "refresh_token": "ref", "user_id": "u1"})
    with patch("xbmcaddon.Addon", return_value=addon), patch.object(
        api, "get_top_games", return_value=TOP_GAMES
    ), patch.object(api, "search_channels") as mock_search:
        win = DiscoverWindow("script-twitch-center-discover.xml", "/tmp")
        win.onInit()
        win.setFocusId(DiscoverWindow.SEARCH_BUTTON_ID)
        win.onAction(xbmcgui.Action(xbmcgui.ACTION_SELECT_ITEM))

    mock_search.assert_not_called()


def test_empty_search_results_show_nothing_found_message():
    addon = _addon_with_token({"access_token": "tok", "refresh_token": "ref", "user_id": "u1"})
    with patch("xbmcaddon.Addon", return_value=addon), patch.object(
        api, "get_top_games", return_value=TOP_GAMES
    ), patch.object(api, "search_channels", return_value=[]):
        win = DiscoverWindow("script-twitch-center-discover.xml", "/tmp")
        win.onInit()
        win.getControl(DiscoverWindow.SEARCH_EDIT_ID).setText("nobody")
        win.setFocusId(DiscoverWindow.SEARCH_BUTTON_ID)
        win.onAction(xbmcgui.Action(xbmcgui.ACTION_SELECT_ITEM))

    assert win.getControl(DiscoverWindow.EMPTY_LABEL_ID).getLabel() != ""
    assert win.getControl(DiscoverWindow.RESULTS_LIST_ID).size() == 0


def test_selecting_relogin_button_opens_login_window_and_closes_discover():
    addon = _addon_with_token({"access_token": "old", "refresh_token": "ref", "user_id": "u1"})

    with patch("xbmcaddon.Addon", return_value=addon), patch.object(
        api, "get_top_games", side_effect=api.TokenExpiredError()
    ), patch("lib.windows.discover.auth.refresh_access_token", return_value=None), patch(
        "lib.windows.discover.LoginWindow"
    ) as mock_login_window_cls:
        win = DiscoverWindow("script-twitch-center-discover.xml", "/tmp")
        win.onInit()
        win.setFocusId(DiscoverWindow.RELOGIN_BUTTON_ID)
        win.onAction(xbmcgui.Action(xbmcgui.ACTION_SELECT_ITEM))

    mock_login_window_cls.assert_called_once()
    assert mock_login_window_cls.call_args.kwargs["closed_event"] is win.closed_event
    mock_login_window_cls.return_value.show.assert_called_once()
    # Handing off to the login window must NOT set the shared event, or
    # main.run's wait loop would exit and tear the script down immediately.
    assert not win.closed_event.is_set()


def test_relogin_chain_sets_the_shared_event_only_when_login_window_closes():
    addon = _addon_with_token({"access_token": "old", "refresh_token": "ref", "user_id": "u1"})

    with patch("xbmcaddon.Addon", return_value=addon), patch.object(
        api, "get_top_games", side_effect=api.TokenExpiredError()
    ), patch("lib.windows.discover.auth.refresh_access_token", return_value=None):
        win = DiscoverWindow("script-twitch-center-discover.xml", "/tmp")
        shared_event = win.closed_event
        win.onInit()
        win.setFocusId(DiscoverWindow.RELOGIN_BUTTON_ID)
        win.onAction(xbmcgui.Action(xbmcgui.ACTION_SELECT_ITEM))

        assert not shared_event.is_set()

        login_window = LoginWindow(
            "script-twitch-center-login.xml", "/tmp", closed_event=shared_event
        )
        login_window.onAction(xbmcgui.Action(xbmcgui.ACTION_NAV_BACK))

    assert shared_event.is_set()


def test_back_from_discover_sets_the_shared_event():
    shared = threading.Event()
    win = DiscoverWindow("script-twitch-center-discover.xml", "/tmp", closed_event=shared)
    assert win.closed_event is shared
    win.onAction(xbmcgui.Action(xbmcgui.ACTION_NAV_BACK))
    assert shared.is_set()


def test_empty_top_games_shows_a_message_instead_of_a_blank_row():
    addon = _addon_with_token({"access_token": "tok", "refresh_token": "ref", "user_id": "u1"})
    with patch("xbmcaddon.Addon", return_value=addon), patch.object(
        api, "get_top_games", return_value=[]
    ):
        win = DiscoverWindow("script-twitch-center-discover.xml", "/tmp")
        win.onInit()

    assert win.getControl(DiscoverWindow.EMPTY_LABEL_ID).getLabel() != ""
    assert win.getControl(DiscoverWindow.GAMES_LIST_ID).size() == 0
    assert win.getControl(DiscoverWindow.ERROR_LABEL_ID).getLabel() == ""


def test_search_failure_keeps_the_top_games_row_intact():
    import requests

    addon = _addon_with_token({"access_token": "tok", "refresh_token": "ref", "user_id": "u1"})
    with patch("xbmcaddon.Addon", return_value=addon), patch.object(
        api, "get_top_games", return_value=TOP_GAMES
    ), patch.object(api, "search_channels", side_effect=requests.ConnectionError("boom")):
        win = DiscoverWindow("script-twitch-center-discover.xml", "/tmp")
        win.onInit()
        assert win.getControl(DiscoverWindow.GAMES_LIST_ID).size() == 2
        win.getControl(DiscoverWindow.SEARCH_EDIT_ID).setText("bob")
        win.setFocusId(DiscoverWindow.SEARCH_BUTTON_ID)
        win.onAction(xbmcgui.Action(xbmcgui.ACTION_SELECT_ITEM))

    assert win.getControl(DiscoverWindow.ERROR_LABEL_ID).getLabel() != ""
    # A transient blip must not force an addon restart.
    assert win.getControl(DiscoverWindow.GAMES_LIST_ID).size() == 2
    assert win.getControl(DiscoverWindow.RELOGIN_BUTTON_ID).isVisible() is False


def test_game_select_failure_keeps_the_top_games_row_intact():
    import requests

    addon = _addon_with_token({"access_token": "tok", "refresh_token": "ref", "user_id": "u1"})
    with patch("xbmcaddon.Addon", return_value=addon), patch.object(
        api, "get_top_games", return_value=TOP_GAMES
    ), patch.object(
        api, "get_live_streams_by_game", side_effect=requests.ConnectionError("boom")
    ):
        win = DiscoverWindow("script-twitch-center-discover.xml", "/tmp")
        win.onInit()
        win.getControl(DiscoverWindow.GAMES_LIST_ID).selectItem(0)
        win.setFocusId(DiscoverWindow.GAMES_LIST_ID)
        win.onAction(xbmcgui.Action(xbmcgui.ACTION_SELECT_ITEM))

    assert win.getControl(DiscoverWindow.ERROR_LABEL_ID).getLabel() != ""
    assert win.getControl(DiscoverWindow.GAMES_LIST_ID).size() == 2


def test_expired_token_during_game_select_retries_that_game_after_refresh():
    addon = _addon_with_token({"access_token": "old", "refresh_token": "ref", "user_id": "u1"})
    calls = []

    def fake_streams(access_token, client_id, game_id, **kwargs):
        calls.append((access_token, game_id))
        if access_token == "old":
            raise api.TokenExpiredError()
        return STREAMS

    with patch("xbmcaddon.Addon", return_value=addon), patch.object(
        api, "get_top_games", return_value=TOP_GAMES
    ), patch.object(api, "get_live_streams_by_game", side_effect=fake_streams), patch(
        "lib.windows.discover.auth.refresh_access_token",
        return_value={"access_token": "new", "refresh_token": "ref2"},
    ):
        win = DiscoverWindow("script-twitch-center-discover.xml", "/tmp")
        win.onInit()
        win.getControl(DiscoverWindow.GAMES_LIST_ID).selectItem(0)
        win.setFocusId(DiscoverWindow.GAMES_LIST_ID)
        win.onAction(xbmcgui.Action(xbmcgui.ACTION_SELECT_ITEM))

    # The user's original game was retried with the refreshed token, not
    # silently dropped in favour of reloading the games row.
    assert calls == [("old", "509658"), ("new", "509658")]
    results_control = win.getControl(DiscoverWindow.RESULTS_LIST_ID)
    assert results_control.size() == 1
    assert results_control._items[0].getLabel() == "Alice"


def test_expired_token_during_search_retries_that_search_after_refresh():
    addon = _addon_with_token({"access_token": "old", "refresh_token": "ref", "user_id": "u1"})
    calls = []

    def fake_search(access_token, client_id, query, **kwargs):
        calls.append((access_token, query))
        if access_token == "old":
            raise api.TokenExpiredError()
        return SEARCH_RESULTS

    with patch("xbmcaddon.Addon", return_value=addon), patch.object(
        api, "get_top_games", return_value=TOP_GAMES
    ), patch.object(api, "search_channels", side_effect=fake_search), patch(
        "lib.windows.discover.auth.refresh_access_token",
        return_value={"access_token": "new", "refresh_token": "ref2"},
    ):
        win = DiscoverWindow("script-twitch-center-discover.xml", "/tmp")
        win.onInit()
        win.getControl(DiscoverWindow.SEARCH_EDIT_ID).setText("bob")
        win.setFocusId(DiscoverWindow.SEARCH_BUTTON_ID)
        win.onAction(xbmcgui.Action(xbmcgui.ACTION_SELECT_ITEM))

    assert calls == [("old", "bob"), ("new", "bob")]
    results_control = win.getControl(DiscoverWindow.RESULTS_LIST_ID)
    assert results_control.size() == 2
    assert results_control._items[0].getLabel() == "Bob"


def test_missing_token_at_click_time_shows_an_error_instead_of_no_op():
    addon = _addon_with_token({"access_token": "tok", "refresh_token": "ref", "user_id": "u1"})
    with patch("xbmcaddon.Addon", return_value=addon), patch.object(
        api, "get_top_games", return_value=TOP_GAMES
    ):
        win = DiscoverWindow("script-twitch-center-discover.xml", "/tmp")
        win.onInit()
        # Another window cleared the token between onInit and the click.
        clear_token(addon)
        win.getControl(DiscoverWindow.SEARCH_EDIT_ID).setText("bob")
        win.setFocusId(DiscoverWindow.SEARCH_BUTTON_ID)
        win.onAction(xbmcgui.Action(xbmcgui.ACTION_SELECT_ITEM))

    assert win.getControl(DiscoverWindow.ERROR_LABEL_ID).getLabel() != ""
    assert win.getControl(DiscoverWindow.GAMES_LIST_ID).size() == 2


def test_build_stream_item_sets_broadcaster_login_and_is_live_true():
    item = _build_stream_item(STREAMS[0])
    assert item.getProperty("broadcaster_login") == STREAMS[0]["user_login"]
    assert item.getProperty("is_live") == "true"


def test_build_channel_item_sets_broadcaster_login_and_is_live_from_data():
    live_item = _build_channel_item(SEARCH_RESULTS[0])
    assert live_item.getProperty("broadcaster_login") == SEARCH_RESULTS[0]["broadcaster_login"]
    assert live_item.getProperty("is_live") == "true"
    offline_item = _build_channel_item(SEARCH_RESULTS[1])
    assert offline_item.getProperty("is_live") == "false"


def test_selecting_a_live_result_plays_it():
    addon = _addon_with_token({"access_token": "tok", "refresh_token": "ref", "user_id": "u1"})
    with patch("xbmcaddon.Addon", return_value=addon), patch.object(
        api, "get_top_games", return_value=TOP_GAMES
    ), patch.object(api, "get_live_streams_by_game", return_value=STREAMS), patch(
        "lib.windows.discover.stream.resolve_stream_url",
        return_value="https://example.invalid/stream.m3u8",
    ) as mock_resolve, patch(
        "lib.windows.discover.player.play_stream", return_value=True
    ) as mock_play:
        win = DiscoverWindow("script-twitch-center-discover.xml", "/tmp")
        win.onInit()
        games_control = win.getControl(DiscoverWindow.GAMES_LIST_ID)
        games_control.selectItem(0)
        win.setFocusId(DiscoverWindow.GAMES_LIST_ID)
        win.onAction(xbmcgui.Action(xbmcgui.ACTION_SELECT_ITEM))
        results_control = win.getControl(DiscoverWindow.RESULTS_LIST_ID)
        results_control.selectItem(0)
        win.setFocusId(DiscoverWindow.RESULTS_LIST_ID)
        win.onAction(xbmcgui.Action(xbmcgui.ACTION_SELECT_ITEM))

    mock_resolve.assert_called_once_with("tok", STREAMS[0]["user_login"])
    mock_play.assert_called_once_with("https://example.invalid/stream.m3u8")


def test_selecting_an_offline_search_result_does_nothing():
    addon = _addon_with_token({"access_token": "tok", "refresh_token": "ref", "user_id": "u1"})
    with patch("xbmcaddon.Addon", return_value=addon), patch.object(
        api, "get_top_games", return_value=TOP_GAMES
    ), patch.object(api, "search_channels", return_value=SEARCH_RESULTS):
        win = DiscoverWindow("script-twitch-center-discover.xml", "/tmp")
        win.onInit()
        win.getControl(DiscoverWindow.SEARCH_EDIT_ID).setText("bob")
        win.setFocusId(DiscoverWindow.SEARCH_BUTTON_ID)
        win.onAction(xbmcgui.Action(xbmcgui.ACTION_SELECT_ITEM))
        results_control = win.getControl(DiscoverWindow.RESULTS_LIST_ID)
        results_control.selectItem(1)  # Carol, offline per SEARCH_RESULTS[1]
        win.setFocusId(DiscoverWindow.RESULTS_LIST_ID)
        with patch("lib.windows.discover.stream.resolve_stream_url") as mock_resolve:
            win.onAction(xbmcgui.Action(xbmcgui.ACTION_SELECT_ITEM))

    mock_resolve.assert_not_called()


def test_selecting_a_live_result_shows_results_error_when_resolution_fails():
    addon = _addon_with_token({"access_token": "tok", "refresh_token": "ref", "user_id": "u1"})
    with patch("xbmcaddon.Addon", return_value=addon), patch.object(
        api, "get_top_games", return_value=TOP_GAMES
    ), patch.object(api, "get_live_streams_by_game", return_value=STREAMS), patch(
        "lib.windows.discover.stream.resolve_stream_url",
        side_effect=stream.StreamUnavailableError("alice"),
    ):
        win = DiscoverWindow("script-twitch-center-discover.xml", "/tmp")
        win.onInit()
        games_control = win.getControl(DiscoverWindow.GAMES_LIST_ID)
        games_control.selectItem(0)
        win.setFocusId(DiscoverWindow.GAMES_LIST_ID)
        win.onAction(xbmcgui.Action(xbmcgui.ACTION_SELECT_ITEM))
        results_control = win.getControl(DiscoverWindow.RESULTS_LIST_ID)
        results_control.selectItem(0)
        win.setFocusId(DiscoverWindow.RESULTS_LIST_ID)
        win.onAction(xbmcgui.Action(xbmcgui.ACTION_SELECT_ITEM))

    assert win.getControl(DiscoverWindow.ERROR_LABEL_ID).getLabel() != ""
    # Games row must survive a transient playback failure, same as a transient
    # search/browse failure already does.
    assert games_control.size() == 2


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
        api, "get_top_games", return_value=TOP_GAMES
    ), patch.object(api, "get_live_streams_by_game", return_value=STREAMS), patch(
        "lib.windows.discover.stream.resolve_stream_url", side_effect=fake_resolve
    ), patch(
        "lib.windows.discover.player.play_stream", return_value=True
    ) as mock_play, patch(
        "lib.windows.discover.auth.refresh_access_token", return_value=new_token
    ):
        win = DiscoverWindow("script-twitch-center-discover.xml", "/tmp")
        win.onInit()
        games_control = win.getControl(DiscoverWindow.GAMES_LIST_ID)
        games_control.selectItem(0)
        win.setFocusId(DiscoverWindow.GAMES_LIST_ID)
        win.onAction(xbmcgui.Action(xbmcgui.ACTION_SELECT_ITEM))
        results_control = win.getControl(DiscoverWindow.RESULTS_LIST_ID)
        results_control.selectItem(0)
        win.setFocusId(DiscoverWindow.RESULTS_LIST_ID)
        win.onAction(xbmcgui.Action(xbmcgui.ACTION_SELECT_ITEM))

    assert resolve_calls == [
        ("old", STREAMS[0]["user_login"]),
        ("new", STREAMS[0]["user_login"]),
    ]
    mock_play.assert_called_once_with("https://example.invalid/stream.m3u8")
