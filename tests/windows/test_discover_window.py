import threading
from unittest.mock import patch

import xbmcaddon
import xbmcgui

from lib.twitch import api
from lib.twitch.auth import save_token
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
        "user_name": "Alice",
        "game_name": "Just Chatting",
        "viewer_count": 500,
        "thumbnail_url": "https://example.invalid/{width}x{height}.jpg",
    }
]

SEARCH_RESULTS = [
    {
        "id": "2",
        "display_name": "Bob",
        "game_name": "League of Legends",
        "is_live": True,
        "thumbnail_url": "https://example.invalid/bob.jpg",
    },
    {
        "id": "3",
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
