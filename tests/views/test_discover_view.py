from unittest.mock import patch

import xbmcaddon
import xbmcgui

from lib import providers
from lib.twitch import api
from lib.twitch.auth import clear_token, save_token
from lib.views.discover_view import (
    DiscoverView,
    _build_channel_item,
    _build_stream_item,
)

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
    assert item.getArt("thumb").startswith("https://example.invalid/320x180.jpg?_tc=")
    assert item.getProperty("broadcaster_id") == "1"
    assert item.getProperty("game_name") == "Just Chatting"
    assert item.getProperty("viewer_count") == "500"


def test_build_channel_item_live_shows_game_and_live_status():
    item = _build_channel_item(SEARCH_RESULTS[0])
    assert item.getLabel() == "Bob"
    assert "Live" in item.getLabel2()
    assert "League of Legends" in item.getLabel2()
    assert item.getArt("thumb").startswith("https://example.invalid/bob.jpg?_tc=")
    assert item.getProperty("broadcaster_id") == "2"
    assert item.getProperty("game_name") == "League of Legends"


def test_build_channel_item_offline_shows_offline():
    item = _build_channel_item(SEARCH_RESULTS[1])
    assert item.getLabel() == "Carol"
    assert item.getLabel2() == "Offline"


def test_oninit_populates_top_games():
    addon = _addon_with_token({"access_token": "tok", "refresh_token": "ref", "user_id": "u1"})
    with patch("xbmcaddon.Addon", return_value=addon), patch.object(
        api, "get_top_games", return_value=TOP_GAMES
    ):
        win = DiscoverView(FakeWindow())
        win.activate()
    games_control = win.window.getControl(DiscoverView.GAMES_LIST_ID)
    assert games_control.size() == 2
    labels = [games_control._items[i].getLabel() for i in range(2)]
    assert labels == ["Just Chatting", "League of Legends"]
    # The skin's <defaultcontrol> targets the search box (always focusable),
    # not the games list, which is empty at skin-parse time and would abort
    # window activation if Kodi tried to focus it directly - activate() must
    # claim focus explicitly once real data is loaded.
    assert win.window.getFocusId() == DiscoverView.GAMES_LIST_ID


def test_oninit_shows_relogin_when_no_token():
    addon = FakeAddon()
    with patch("xbmcaddon.Addon", return_value=addon):
        win = DiscoverView(FakeWindow())
        win.activate()
    assert win.window.getControl(DiscoverView.ERROR_LABEL_ID).getLabel() != ""
    assert win.window.getFocusId() == DiscoverView.RELOGIN_BUTTON_ID


def test_oninit_shows_error_on_network_failure():
    import requests

    addon = _addon_with_token({"access_token": "tok", "refresh_token": "ref", "user_id": "u1"})
    with patch("xbmcaddon.Addon", return_value=addon), patch.object(
        api, "get_top_games", side_effect=requests.ConnectionError("boom")
    ):
        win = DiscoverView(FakeWindow())
        win.activate()
    assert win.window.getControl(DiscoverView.ERROR_LABEL_ID).getLabel() != ""


def test_selecting_a_game_populates_results_with_stream_items():
    addon = _addon_with_token({"access_token": "tok", "refresh_token": "ref", "user_id": "u1"})
    with patch("xbmcaddon.Addon", return_value=addon), patch.object(
        api, "get_top_games", return_value=TOP_GAMES
    ), patch.object(api, "get_live_streams_by_game", return_value=STREAMS):
        win = DiscoverView(FakeWindow())
        win.activate()
        games_control = win.window.getControl(DiscoverView.GAMES_LIST_ID)
        games_control.selectItem(0)
        win.window.setFocusId(DiscoverView.GAMES_LIST_ID)
        win.handle_action(xbmcgui.Action(xbmcgui.ACTION_SELECT_ITEM))

    results_control = win.window.getControl(DiscoverView.RESULTS_LIST_ID)
    assert results_control.size() == 1
    assert results_control._items[0].getLabel() == "Alice"


def test_pressing_search_populates_results_with_channel_items():
    addon = _addon_with_token({"access_token": "tok", "refresh_token": "ref", "user_id": "u1"})
    with patch("xbmcaddon.Addon", return_value=addon), patch.object(
        api, "get_top_games", return_value=TOP_GAMES
    ), patch.object(api, "search_channels", return_value=SEARCH_RESULTS):
        win = DiscoverView(FakeWindow())
        win.activate()
        win.window.getControl(DiscoverView.SEARCH_EDIT_ID).setText("bob")
        win.window.setFocusId(DiscoverView.SEARCH_BUTTON_ID)
        win.handle_action(xbmcgui.Action(xbmcgui.ACTION_SELECT_ITEM))

    results_control = win.window.getControl(DiscoverView.RESULTS_LIST_ID)
    assert results_control.size() == 2
    assert results_control._items[0].getLabel() == "Bob"


def test_pressing_search_with_empty_query_does_nothing():
    addon = _addon_with_token({"access_token": "tok", "refresh_token": "ref", "user_id": "u1"})
    with patch("xbmcaddon.Addon", return_value=addon), patch.object(
        api, "get_top_games", return_value=TOP_GAMES
    ), patch.object(api, "search_channels") as mock_search:
        win = DiscoverView(FakeWindow())
        win.activate()
        win.window.setFocusId(DiscoverView.SEARCH_BUTTON_ID)
        win.handle_action(xbmcgui.Action(xbmcgui.ACTION_SELECT_ITEM))

    mock_search.assert_not_called()


def test_empty_search_results_show_nothing_found_message():
    addon = _addon_with_token({"access_token": "tok", "refresh_token": "ref", "user_id": "u1"})
    with patch("xbmcaddon.Addon", return_value=addon), patch.object(
        api, "get_top_games", return_value=TOP_GAMES
    ), patch.object(api, "search_channels", return_value=[]):
        win = DiscoverView(FakeWindow())
        win.activate()
        win.window.getControl(DiscoverView.SEARCH_EDIT_ID).setText("nobody")
        win.window.setFocusId(DiscoverView.SEARCH_BUTTON_ID)
        win.handle_action(xbmcgui.Action(xbmcgui.ACTION_SELECT_ITEM))

    assert win.window.getControl(DiscoverView.EMPTY_LABEL_ID).getLabel() != ""
    assert win.window.getControl(DiscoverView.RESULTS_LIST_ID).size() == 0


def test_toggling_search_mode_button_flips_mode_and_label():
    addon = _addon_with_token({"access_token": "tok", "refresh_token": "ref", "user_id": "u1"})
    with patch("xbmcaddon.Addon", return_value=addon), patch.object(
        api, "get_top_games", return_value=TOP_GAMES
    ):
        win = DiscoverView(FakeWindow())
        win.activate()
        assert win._search_mode == "channels"

        win.window.setFocusId(DiscoverView.SEARCH_MODE_TOGGLE_ID)
        win.handle_action(xbmcgui.Action(xbmcgui.ACTION_SELECT_ITEM))
        assert win._search_mode == "games"
        assert "Games" in win.window.getControl(DiscoverView.SEARCH_MODE_TOGGLE_ID).getLabel()

        win.handle_action(xbmcgui.Action(xbmcgui.ACTION_SELECT_ITEM))
        assert win._search_mode == "kick"
        assert "Kick" in win.window.getControl(DiscoverView.SEARCH_MODE_TOGGLE_ID).getLabel()

        win.handle_action(xbmcgui.Action(xbmcgui.ACTION_SELECT_ITEM))
        assert win._search_mode == "channels"
        assert "Channels" in win.window.getControl(DiscoverView.SEARCH_MODE_TOGGLE_ID).getLabel()


def test_pressing_search_in_game_mode_searches_categories_then_lists_its_streams():
    addon = _addon_with_token({"access_token": "tok", "refresh_token": "ref", "user_id": "u1"})
    matches = [{"id": "16497", "name": "World of Warships"}]
    with patch("xbmcaddon.Addon", return_value=addon), patch.object(
        api, "get_top_games", return_value=TOP_GAMES
    ), patch.object(
        api, "search_categories", return_value=matches
    ) as mock_search_categories, patch.object(
        api, "get_live_streams_by_game", return_value=STREAMS
    ) as mock_get_streams:
        win = DiscoverView(FakeWindow())
        win.activate()
        win.window.setFocusId(DiscoverView.SEARCH_MODE_TOGGLE_ID)
        win.handle_action(xbmcgui.Action(xbmcgui.ACTION_SELECT_ITEM))
        win.window.getControl(DiscoverView.SEARCH_EDIT_ID).setText("warships")
        win.window.setFocusId(DiscoverView.SEARCH_BUTTON_ID)
        win.handle_action(xbmcgui.Action(xbmcgui.ACTION_SELECT_ITEM))

    mock_search_categories.assert_called_once_with("tok", "", "warships", first=1)
    mock_get_streams.assert_called_once_with("tok", "", "16497")
    results_control = win.window.getControl(DiscoverView.RESULTS_LIST_ID)
    assert results_control.size() == 1
    assert results_control._items[0].getLabel() == "Alice"


def test_pressing_search_in_game_mode_shows_message_when_no_game_matches():
    addon = _addon_with_token({"access_token": "tok", "refresh_token": "ref", "user_id": "u1"})
    with patch("xbmcaddon.Addon", return_value=addon), patch.object(
        api, "get_top_games", return_value=TOP_GAMES
    ), patch.object(api, "search_categories", return_value=[]), patch.object(
        api, "get_live_streams_by_game"
    ) as mock_get_streams:
        win = DiscoverView(FakeWindow())
        win.activate()
        win.window.setFocusId(DiscoverView.SEARCH_MODE_TOGGLE_ID)
        win.handle_action(xbmcgui.Action(xbmcgui.ACTION_SELECT_ITEM))
        win.window.getControl(DiscoverView.SEARCH_EDIT_ID).setText("nonexistentgamexyz")
        win.window.setFocusId(DiscoverView.SEARCH_BUTTON_ID)
        win.handle_action(xbmcgui.Action(xbmcgui.ACTION_SELECT_ITEM))

    mock_get_streams.assert_not_called()
    assert win.window.getControl(DiscoverView.EMPTY_LABEL_ID).getLabel() != ""
    assert win.window.getControl(DiscoverView.RESULTS_LIST_ID).size() == 0


def _switch_to_kick_search_mode(win):
    win.window.setFocusId(DiscoverView.SEARCH_MODE_TOGGLE_ID)
    win.handle_action(xbmcgui.Action(xbmcgui.ACTION_SELECT_ITEM))  # channels -> games
    win.handle_action(xbmcgui.Action(xbmcgui.ACTION_SELECT_ITEM))  # games -> kick


def test_pressing_search_in_kick_mode_searches_categories_then_lists_its_streams():
    addon = _addon_with_token({"access_token": "tok", "refresh_token": "ref", "user_id": "u1"})
    addon.setSetting("kick_client_secret", "csecret")
    matches = [{"id": 3, "name": "EVE Online"}]
    with patch("xbmcaddon.Addon", return_value=addon), patch.object(
        api, "get_top_games", return_value=TOP_GAMES
    ), patch.object(
        providers, "search_kick_categories", return_value=matches
    ) as mock_search, patch.object(
        providers, "get_kick_category_streams", return_value=[KICK_CATEGORY_STREAM]
    ) as mock_get_streams:
        win = DiscoverView(FakeWindow())
        win.activate()
        _switch_to_kick_search_mode(win)
        win.window.getControl(DiscoverView.SEARCH_EDIT_ID).setText("eve")
        win.window.setFocusId(DiscoverView.SEARCH_BUTTON_ID)
        win.handle_action(xbmcgui.Action(xbmcgui.ACTION_SELECT_ITEM))

    mock_search.assert_called_once_with(addon, "eve")
    mock_get_streams.assert_called_once_with(addon, 3)
    results_control = win.window.getControl(DiscoverView.RESULTS_LIST_ID)
    assert results_control.size() == 1
    assert results_control.getListItem(0).getProperty("platform") == "kick"


def test_live_kick_filter_populates_category_row_with_matches():
    addon = _addon_with_token({"access_token": "tok", "refresh_token": "ref", "user_id": "u1"})
    matches = [{"id": 166, "name": "EVE Online"}, {"id": 1067, "name": "EVE Online"}]
    with patch("xbmcaddon.Addon", return_value=addon), patch.object(
        api, "get_top_games", return_value=TOP_GAMES
    ), patch.object(
        providers, "get_kick_top_categories", return_value=KICK_TOP_CATEGORIES
    ), patch.object(
        providers, "search_kick_categories", return_value=matches
    ) as mock_search:
        win = DiscoverView(FakeWindow())
        win.activate()
        win._apply_live_kick_filter("eve online")
        win.stop()

    mock_search.assert_called_once_with(addon, "eve online")
    kick_control = win.window.getControl(DiscoverView.KICK_CATEGORIES_LIST_ID)
    assert kick_control.size() == 2
    assert kick_control.getListItem(0).getLabel() == "EVE Online"
    assert kick_control.getListItem(0).getProperty("category_id") == "166"


def test_live_kick_filter_restores_top_categories_when_query_cleared():
    addon = _addon_with_token({"access_token": "tok", "refresh_token": "ref", "user_id": "u1"})
    with patch("xbmcaddon.Addon", return_value=addon), patch.object(
        api, "get_top_games", return_value=TOP_GAMES
    ), patch.object(
        providers, "get_kick_top_categories", return_value=KICK_TOP_CATEGORIES
    ), patch.object(
        providers, "search_kick_categories", return_value=[{"id": 166, "name": "EVE Online"}]
    ):
        win = DiscoverView(FakeWindow())
        win.activate()
        win._apply_live_kick_filter("eve")
        win._apply_live_kick_filter("")
        win.stop()

    kick_control = win.window.getControl(DiscoverView.KICK_CATEGORIES_LIST_ID)
    assert kick_control.size() == len(KICK_TOP_CATEGORIES)
    assert kick_control.getListItem(0).getLabel() == KICK_TOP_CATEGORIES[0]["name"]


def test_selecting_a_live_filtered_category_loads_its_streams():
    # The live filter reuses the existing top-categories row and its
    # existing selection handler - selecting a filtered-in category should
    # behave exactly like selecting one from the top-categories row.
    addon = _addon_with_token({"access_token": "tok", "refresh_token": "ref", "user_id": "u1"})
    with patch("xbmcaddon.Addon", return_value=addon), patch.object(
        api, "get_top_games", return_value=TOP_GAMES
    ), patch.object(
        providers, "get_kick_top_categories", return_value=KICK_TOP_CATEGORIES
    ), patch.object(
        providers, "search_kick_categories", return_value=[{"id": 1067, "name": "EVE Online"}]
    ), patch.object(
        providers, "get_kick_category_streams", return_value=[KICK_CATEGORY_STREAM]
    ) as mock_get_streams:
        win = DiscoverView(FakeWindow())
        win.activate()
        win._apply_live_kick_filter("eve online")
        kick_control = win.window.getControl(DiscoverView.KICK_CATEGORIES_LIST_ID)
        kick_control.selectItem(0)
        win.window.setFocusId(DiscoverView.KICK_CATEGORIES_LIST_ID)
        win.handle_action(xbmcgui.Action(xbmcgui.ACTION_SELECT_ITEM))
        win.stop()

    mock_get_streams.assert_called_once_with(addon, "1067")
    results_control = win.window.getControl(DiscoverView.RESULTS_LIST_ID)
    assert results_control.size() == 1


def test_stop_cancels_the_live_filter_poll_thread():
    addon = _addon_with_token({"access_token": "tok", "refresh_token": "ref", "user_id": "u1"})
    with patch("xbmcaddon.Addon", return_value=addon), patch.object(
        api, "get_top_games", return_value=TOP_GAMES
    ), patch.object(providers, "get_kick_top_categories", return_value=KICK_TOP_CATEGORIES):
        win = DiscoverView(FakeWindow())
        win.activate()
        assert win._live_filter_cancel is not None
        assert not win._live_filter_cancel.is_set()
        win.stop()
        assert win._live_filter_cancel.is_set()


def test_pressing_search_in_kick_mode_merges_streams_from_duplicate_category_matches():
    # Kick can return multiple distinct category IDs sharing the same name
    # (e.g. two separate "EVE Online" categories) - streams from every
    # match must be merged, not just the first match's.
    addon = _addon_with_token({"access_token": "tok", "refresh_token": "ref", "user_id": "u1"})
    addon.setSetting("kick_client_secret", "csecret")
    matches = [{"id": 166, "name": "EVE Online"}, {"id": 1067, "name": "EVE Online"}]
    other_stream = dict(KICK_CATEGORY_STREAM, id="99", login="contempoenterprises", viewer_count=29)

    def fake_get_streams(addon, category_id):
        return {166: [], 1067: [other_stream]}[category_id]

    with patch("xbmcaddon.Addon", return_value=addon), patch.object(
        api, "get_top_games", return_value=TOP_GAMES
    ), patch.object(
        providers, "search_kick_categories", return_value=matches
    ), patch.object(
        providers, "get_kick_category_streams", side_effect=fake_get_streams
    ):
        win = DiscoverView(FakeWindow())
        win.activate()
        _switch_to_kick_search_mode(win)
        win.window.getControl(DiscoverView.SEARCH_EDIT_ID).setText("eve online")
        win.window.setFocusId(DiscoverView.SEARCH_BUTTON_ID)
        win.handle_action(xbmcgui.Action(xbmcgui.ACTION_SELECT_ITEM))

    results_control = win.window.getControl(DiscoverView.RESULTS_LIST_ID)
    assert results_control.size() == 1
    assert results_control.getListItem(0).getProperty("broadcaster_login") == "contempoenterprises"


def test_pressing_search_in_kick_mode_shows_message_when_no_category_matches():
    addon = _addon_with_token({"access_token": "tok", "refresh_token": "ref", "user_id": "u1"})
    addon.setSetting("kick_client_secret", "csecret")
    with patch("xbmcaddon.Addon", return_value=addon), patch.object(
        api, "get_top_games", return_value=TOP_GAMES
    ), patch.object(
        providers, "search_kick_categories", return_value=[]
    ), patch.object(providers, "get_kick_category_streams") as mock_get_streams:
        win = DiscoverView(FakeWindow())
        win.activate()
        _switch_to_kick_search_mode(win)
        win.window.getControl(DiscoverView.SEARCH_EDIT_ID).setText("nonexistentgamexyz")
        win.window.setFocusId(DiscoverView.SEARCH_BUTTON_ID)
        win.handle_action(xbmcgui.Action(xbmcgui.ACTION_SELECT_ITEM))

    mock_get_streams.assert_not_called()
    assert win.window.getControl(DiscoverView.EMPTY_LABEL_ID).getLabel() != ""
    assert win.window.getControl(DiscoverView.RESULTS_LIST_ID).size() == 0


def test_pressing_search_in_kick_mode_shows_error_when_kick_app_not_configured():
    addon = _addon_with_token({"access_token": "tok", "refresh_token": "ref", "user_id": "u1"})
    # kick_client_secret left unset
    with patch("xbmcaddon.Addon", return_value=addon), patch.object(
        api, "get_top_games", return_value=TOP_GAMES
    ), patch.object(
        providers, "search_kick_categories"
    ) as mock_search:
        win = DiscoverView(FakeWindow())
        win.activate()
        _switch_to_kick_search_mode(win)
        win.window.getControl(DiscoverView.SEARCH_EDIT_ID).setText("eve")
        win.window.setFocusId(DiscoverView.SEARCH_BUTTON_ID)
        win.handle_action(xbmcgui.Action(xbmcgui.ACTION_SELECT_ITEM))

    mock_search.assert_not_called()
    assert win.window.getControl(DiscoverView.ERROR_LABEL_ID).getLabel() != ""


def test_selecting_relogin_button_switches_to_login_view():
    addon = _addon_with_token({"access_token": "old", "refresh_token": "ref", "user_id": "u1"})

    with patch("xbmcaddon.Addon", return_value=addon), patch.object(
        api, "get_top_games", side_effect=api.TokenExpiredError()
    ), patch("lib.views.discover_view.auth.refresh_access_token", return_value=None):
        win = DiscoverView(FakeWindow())
        win.activate()
        win.window.setFocusId(DiscoverView.RELOGIN_BUTTON_ID)
        win.handle_action(xbmcgui.Action(xbmcgui.ACTION_SELECT_ITEM))

    assert win.window.switched_to == ["login"]


def test_empty_top_games_shows_a_message_instead_of_a_blank_row():
    addon = _addon_with_token({"access_token": "tok", "refresh_token": "ref", "user_id": "u1"})
    with patch("xbmcaddon.Addon", return_value=addon), patch.object(
        api, "get_top_games", return_value=[]
    ):
        win = DiscoverView(FakeWindow())
        win.activate()

    assert win.window.getControl(DiscoverView.EMPTY_LABEL_ID).getLabel() != ""
    assert win.window.getControl(DiscoverView.GAMES_LIST_ID).size() == 0
    assert win.window.getControl(DiscoverView.ERROR_LABEL_ID).getLabel() == ""


def test_search_failure_keeps_the_top_games_row_intact():
    import requests

    addon = _addon_with_token({"access_token": "tok", "refresh_token": "ref", "user_id": "u1"})
    with patch("xbmcaddon.Addon", return_value=addon), patch.object(
        api, "get_top_games", return_value=TOP_GAMES
    ), patch.object(api, "search_channels", side_effect=requests.ConnectionError("boom")):
        win = DiscoverView(FakeWindow())
        win.activate()
        assert win.window.getControl(DiscoverView.GAMES_LIST_ID).size() == 2
        win.window.getControl(DiscoverView.SEARCH_EDIT_ID).setText("bob")
        win.window.setFocusId(DiscoverView.SEARCH_BUTTON_ID)
        win.handle_action(xbmcgui.Action(xbmcgui.ACTION_SELECT_ITEM))

    assert win.window.getControl(DiscoverView.ERROR_LABEL_ID).getLabel() != ""
    # A transient blip must not force an addon restart.
    assert win.window.getControl(DiscoverView.GAMES_LIST_ID).size() == 2
    assert win.window.getControl(DiscoverView.RELOGIN_BUTTON_ID).isVisible() is False


def test_game_select_failure_keeps_the_top_games_row_intact():
    import requests

    addon = _addon_with_token({"access_token": "tok", "refresh_token": "ref", "user_id": "u1"})
    with patch("xbmcaddon.Addon", return_value=addon), patch.object(
        api, "get_top_games", return_value=TOP_GAMES
    ), patch.object(
        api, "get_live_streams_by_game", side_effect=requests.ConnectionError("boom")
    ):
        win = DiscoverView(FakeWindow())
        win.activate()
        win.window.getControl(DiscoverView.GAMES_LIST_ID).selectItem(0)
        win.window.setFocusId(DiscoverView.GAMES_LIST_ID)
        win.handle_action(xbmcgui.Action(xbmcgui.ACTION_SELECT_ITEM))

    assert win.window.getControl(DiscoverView.ERROR_LABEL_ID).getLabel() != ""
    assert win.window.getControl(DiscoverView.GAMES_LIST_ID).size() == 2


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
        "lib.views.discover_view.auth.refresh_access_token",
        return_value={"access_token": "new", "refresh_token": "ref2"},
    ):
        win = DiscoverView(FakeWindow())
        win.activate()
        win.window.getControl(DiscoverView.GAMES_LIST_ID).selectItem(0)
        win.window.setFocusId(DiscoverView.GAMES_LIST_ID)
        win.handle_action(xbmcgui.Action(xbmcgui.ACTION_SELECT_ITEM))

    # The user's original game was retried with the refreshed token, not
    # silently dropped in favour of reloading the games row.
    assert calls == [("old", "509658"), ("new", "509658")]
    results_control = win.window.getControl(DiscoverView.RESULTS_LIST_ID)
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
        "lib.views.discover_view.auth.refresh_access_token",
        return_value={"access_token": "new", "refresh_token": "ref2"},
    ):
        win = DiscoverView(FakeWindow())
        win.activate()
        win.window.getControl(DiscoverView.SEARCH_EDIT_ID).setText("bob")
        win.window.setFocusId(DiscoverView.SEARCH_BUTTON_ID)
        win.handle_action(xbmcgui.Action(xbmcgui.ACTION_SELECT_ITEM))

    assert calls == [("old", "bob"), ("new", "bob")]
    results_control = win.window.getControl(DiscoverView.RESULTS_LIST_ID)
    assert results_control.size() == 2
    assert results_control._items[0].getLabel() == "Bob"


def test_missing_token_at_click_time_shows_an_error_instead_of_no_op():
    addon = _addon_with_token({"access_token": "tok", "refresh_token": "ref", "user_id": "u1"})
    with patch("xbmcaddon.Addon", return_value=addon), patch.object(
        api, "get_top_games", return_value=TOP_GAMES
    ):
        win = DiscoverView(FakeWindow())
        win.activate()
        # Another window cleared the token between activate() and the click.
        clear_token(addon)
        win.window.getControl(DiscoverView.SEARCH_EDIT_ID).setText("bob")
        win.window.setFocusId(DiscoverView.SEARCH_BUTTON_ID)
        win.handle_action(xbmcgui.Action(xbmcgui.ACTION_SELECT_ITEM))

    assert win.window.getControl(DiscoverView.ERROR_LABEL_ID).getLabel() != ""
    assert win.window.getControl(DiscoverView.GAMES_LIST_ID).size() == 2


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
    ), patch.object(api, "get_live_streams_by_game", return_value=STREAMS), patch.object(
        providers, "resolve_stream_url", return_value="https://example.invalid/stream.m3u8"
    ) as mock_resolve, patch(
        "lib.views.discover_view.player.play_stream", return_value=True
    ) as mock_play:
        win = DiscoverView(FakeWindow())
        win.activate()
        games_control = win.window.getControl(DiscoverView.GAMES_LIST_ID)
        games_control.selectItem(0)
        win.window.setFocusId(DiscoverView.GAMES_LIST_ID)
        win.handle_action(xbmcgui.Action(xbmcgui.ACTION_SELECT_ITEM))
        results_control = win.window.getControl(DiscoverView.RESULTS_LIST_ID)
        results_control.selectItem(0)
        win.window.setFocusId(DiscoverView.RESULTS_LIST_ID)
        win.handle_action(xbmcgui.Action(xbmcgui.ACTION_SELECT_ITEM))

    call_args = mock_resolve.call_args
    assert call_args.args[1] == "twitch"
    assert call_args.args[2] == STREAMS[0]["user_login"]
    mock_play.assert_called_once_with(
        "https://example.invalid/stream.m3u8",
        STREAMS[0]["user_login"],
        platform="twitch",
        access_token="tok",
        client_id="",
        user_id="u1",
    )


def test_selecting_an_offline_search_result_does_nothing():
    addon = _addon_with_token({"access_token": "tok", "refresh_token": "ref", "user_id": "u1"})
    with patch("xbmcaddon.Addon", return_value=addon), patch.object(
        api, "get_top_games", return_value=TOP_GAMES
    ), patch.object(api, "search_channels", return_value=SEARCH_RESULTS):
        win = DiscoverView(FakeWindow())
        win.activate()
        win.window.getControl(DiscoverView.SEARCH_EDIT_ID).setText("bob")
        win.window.setFocusId(DiscoverView.SEARCH_BUTTON_ID)
        win.handle_action(xbmcgui.Action(xbmcgui.ACTION_SELECT_ITEM))
        results_control = win.window.getControl(DiscoverView.RESULTS_LIST_ID)
        results_control.selectItem(1)  # Carol, offline per SEARCH_RESULTS[1]
        win.window.setFocusId(DiscoverView.RESULTS_LIST_ID)
        with patch.object(providers, "resolve_stream_url") as mock_resolve:
            win.handle_action(xbmcgui.Action(xbmcgui.ACTION_SELECT_ITEM))

    mock_resolve.assert_not_called()


def test_selecting_a_live_result_shows_results_error_when_resolution_fails():
    addon = _addon_with_token({"access_token": "tok", "refresh_token": "ref", "user_id": "u1"})
    with patch("xbmcaddon.Addon", return_value=addon), patch.object(
        api, "get_top_games", return_value=TOP_GAMES
    ), patch.object(api, "get_live_streams_by_game", return_value=STREAMS), patch.object(
        providers, "resolve_stream_url", side_effect=providers.StreamUnavailableError("alice"),
    ):
        win = DiscoverView(FakeWindow())
        win.activate()
        games_control = win.window.getControl(DiscoverView.GAMES_LIST_ID)
        games_control.selectItem(0)
        win.window.setFocusId(DiscoverView.GAMES_LIST_ID)
        win.handle_action(xbmcgui.Action(xbmcgui.ACTION_SELECT_ITEM))
        results_control = win.window.getControl(DiscoverView.RESULTS_LIST_ID)
        results_control.selectItem(0)
        win.window.setFocusId(DiscoverView.RESULTS_LIST_ID)
        win.handle_action(xbmcgui.Action(xbmcgui.ACTION_SELECT_ITEM))

    assert win.window.getControl(DiscoverView.ERROR_LABEL_ID).getLabel() != ""
    # Games row must survive a transient playback failure, same as a transient
    # search/browse failure already does.
    assert games_control.size() == 2


def test_selecting_a_live_result_shows_error_on_unexpected_exception():
    addon = _addon_with_token({"access_token": "tok", "refresh_token": "ref", "user_id": "u1"})
    with patch("xbmcaddon.Addon", return_value=addon), patch.object(
        api, "get_top_games", return_value=TOP_GAMES
    ), patch.object(api, "get_live_streams_by_game", return_value=STREAMS), patch.object(
        providers, "resolve_stream_url", side_effect=RuntimeError("boom"),
    ):
        win = DiscoverView(FakeWindow())
        win.activate()
        games_control = win.window.getControl(DiscoverView.GAMES_LIST_ID)
        games_control.selectItem(0)
        win.window.setFocusId(DiscoverView.GAMES_LIST_ID)
        win.handle_action(xbmcgui.Action(xbmcgui.ACTION_SELECT_ITEM))
        results_control = win.window.getControl(DiscoverView.RESULTS_LIST_ID)
        results_control.selectItem(0)
        win.window.setFocusId(DiscoverView.RESULTS_LIST_ID)
        win.handle_action(xbmcgui.Action(xbmcgui.ACTION_SELECT_ITEM))

    assert win.window.getControl(DiscoverView.ERROR_LABEL_ID).getLabel() != ""
    assert games_control.size() == 2


KICK_TOP_CATEGORIES = [{"id": 7, "name": "Just Chatting"}, {"id": 8, "name": "Slots"}]

KICK_CATEGORY_STREAM = {
    "platform": "kick",
    "id": "42",
    "login": "kickchannel",
    "display_name": "kickchannel",
    "is_live": True,
    "viewer_count": 88,
    "game_name": "Slots",
    "thumbnail_url": "https://example.invalid/kickthumb.jpg",
}


def test_oninit_populates_kick_categories_row():
    addon = _addon_with_token({"access_token": "tok", "refresh_token": "ref", "user_id": "u1"})
    with patch("xbmcaddon.Addon", return_value=addon), patch.object(
        api, "get_top_games", return_value=TOP_GAMES
    ), patch.object(providers, "get_kick_top_categories", return_value=KICK_TOP_CATEGORIES):
        win = DiscoverView(FakeWindow())
        win.activate()

    kick_control = win.window.getControl(DiscoverView.KICK_CATEGORIES_LIST_ID)
    assert kick_control.size() == 2
    assert kick_control.getListItem(0).getLabel() == "Just Chatting"
    assert kick_control.getListItem(0).getProperty("category_id") == "7"


def test_kick_categories_row_is_empty_when_no_kick_token():
    addon = _addon_with_token({"access_token": "tok", "refresh_token": "ref", "user_id": "u1"})
    with patch("xbmcaddon.Addon", return_value=addon), patch.object(
        api, "get_top_games", return_value=TOP_GAMES
    ), patch.object(providers, "get_kick_top_categories", return_value=[]):
        win = DiscoverView(FakeWindow())
        win.activate()

    kick_control = win.window.getControl(DiscoverView.KICK_CATEGORIES_LIST_ID)
    assert kick_control.size() == 0


def test_selecting_a_kick_category_populates_results_with_kick_items():
    addon = _addon_with_token({"access_token": "tok", "refresh_token": "ref", "user_id": "u1"})
    with patch("xbmcaddon.Addon", return_value=addon), patch.object(
        api, "get_top_games", return_value=TOP_GAMES
    ), patch.object(
        providers, "get_kick_top_categories", return_value=KICK_TOP_CATEGORIES
    ), patch.object(
        providers, "get_kick_category_streams", return_value=[KICK_CATEGORY_STREAM]
    ) as mock_get_streams:
        win = DiscoverView(FakeWindow())
        win.activate()
        kick_control = win.window.getControl(DiscoverView.KICK_CATEGORIES_LIST_ID)
        kick_control.selectItem(0)
        win.window.setFocusId(DiscoverView.KICK_CATEGORIES_LIST_ID)
        win.handle_action(xbmcgui.Action(xbmcgui.ACTION_SELECT_ITEM))

    mock_get_streams.assert_called_once()
    assert mock_get_streams.call_args.args[1] == "7"
    results_control = win.window.getControl(DiscoverView.RESULTS_LIST_ID)
    assert results_control.size() == 1
    assert results_control.getListItem(0).getProperty("broadcaster_login") == "kickchannel"
    assert results_control.getListItem(0).getProperty("platform") == "kick"


def test_selecting_a_live_kick_result_plays_it():
    addon = _addon_with_token({"access_token": "tok", "refresh_token": "ref", "user_id": "u1"})
    with patch("xbmcaddon.Addon", return_value=addon), patch.object(
        api, "get_top_games", return_value=TOP_GAMES
    ), patch.object(
        providers, "get_kick_top_categories", return_value=KICK_TOP_CATEGORIES
    ), patch.object(
        providers, "get_kick_category_streams", return_value=[KICK_CATEGORY_STREAM]
    ), patch.object(
        providers, "resolve_stream_url", return_value="https://kick.example/x.m3u8"
    ) as mock_resolve, patch(
        "lib.views.discover_view.player.play_stream", return_value=True
    ) as mock_play:
        win = DiscoverView(FakeWindow())
        win.activate()
        kick_control = win.window.getControl(DiscoverView.KICK_CATEGORIES_LIST_ID)
        kick_control.selectItem(0)
        win.window.setFocusId(DiscoverView.KICK_CATEGORIES_LIST_ID)
        win.handle_action(xbmcgui.Action(xbmcgui.ACTION_SELECT_ITEM))
        results_control = win.window.getControl(DiscoverView.RESULTS_LIST_ID)
        results_control.selectItem(0)
        win.window.setFocusId(DiscoverView.RESULTS_LIST_ID)
        win.handle_action(xbmcgui.Action(xbmcgui.ACTION_SELECT_ITEM))

    call_args = mock_resolve.call_args
    assert call_args.args[1] == "kick"
    assert call_args.args[2] == "kickchannel"
    mock_play.assert_called_once_with(
        "https://kick.example/x.m3u8", "kickchannel", platform="kick"
    )


def test_context_menu_on_kick_result_adds_favorite():
    addon = _addon_with_token({"access_token": "tok", "refresh_token": "ref", "user_id": "u1"})
    xbmcgui.Dialog.next_contextmenu_choice = 0
    xbmcgui.Dialog.notifications = []
    with patch("xbmcaddon.Addon", return_value=addon), patch.object(
        api, "get_top_games", return_value=TOP_GAMES
    ), patch.object(
        providers, "get_kick_top_categories", return_value=KICK_TOP_CATEGORIES
    ), patch.object(
        providers, "get_kick_category_streams", return_value=[KICK_CATEGORY_STREAM]
    ):
        win = DiscoverView(FakeWindow())
        win.activate()
        kick_control = win.window.getControl(DiscoverView.KICK_CATEGORIES_LIST_ID)
        kick_control.selectItem(0)
        win.window.setFocusId(DiscoverView.KICK_CATEGORIES_LIST_ID)
        win.handle_action(xbmcgui.Action(xbmcgui.ACTION_SELECT_ITEM))
        results_control = win.window.getControl(DiscoverView.RESULTS_LIST_ID)
        results_control.selectItem(0)
        win.window.setFocusId(DiscoverView.RESULTS_LIST_ID)
        win.handle_action(xbmcgui.Action(xbmcgui.ACTION_CONTEXT_MENU))

    assert providers.get_kick_favorites(addon) == ["kickchannel"]


def test_context_menu_on_twitch_result_does_nothing():
    addon = _addon_with_token({"access_token": "tok", "refresh_token": "ref", "user_id": "u1"})
    xbmcgui.Dialog.next_contextmenu_choice = 0
    xbmcgui.Dialog.notifications = []
    with patch("xbmcaddon.Addon", return_value=addon), patch.object(
        api, "get_top_games", return_value=TOP_GAMES
    ), patch.object(
        api, "get_live_streams_by_game", return_value=STREAMS
    ):
        win = DiscoverView(FakeWindow())
        win.activate()
        games_control = win.window.getControl(DiscoverView.GAMES_LIST_ID)
        games_control.selectItem(0)
        win.window.setFocusId(DiscoverView.GAMES_LIST_ID)
        win.handle_action(xbmcgui.Action(xbmcgui.ACTION_SELECT_ITEM))
        results_control = win.window.getControl(DiscoverView.RESULTS_LIST_ID)
        results_control.selectItem(0)
        win.window.setFocusId(DiscoverView.RESULTS_LIST_ID)
        win.handle_action(xbmcgui.Action(xbmcgui.ACTION_CONTEXT_MENU))

    assert providers.get_kick_favorites(addon) == []
    assert xbmcgui.Dialog.notifications == []
