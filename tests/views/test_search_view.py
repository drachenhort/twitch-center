import xbmcgui

from lib.views.search_view import SearchView


class FakeWindow:
    def __init__(self):
        self._controls = {}
        self._focus_id = None

    def getControl(self, control_id):
        from xbmcgui import FakeListControl

        if control_id not in self._controls:
            self._controls[control_id] = FakeListControl()
        return self._controls[control_id]

    def setFocusId(self, control_id):
        self._focus_id = control_id

    def getFocusId(self):
        return self._focus_id


def test_activate_does_not_raise_and_focuses_search_input():
    # Regression test: onInit used to call
    # self.getControl(SEARCH_INPUT_ID).setFocus(True), but Kodi's
    # xbmcgui.ControlEdit has no setFocus method (only Window.setFocusId
    # exists for this) - the resulting uncaught AttributeError crashed
    # onInit, which Kodi's window manager reacted to by silently reverting
    # to the previous window. Symptom looked like "search flashes open then
    # bounces back to Home".
    win = SearchView(FakeWindow())
    win.activate()
    assert win.window.getFocusId() == SearchView.SEARCH_INPUT_ID
    assert win.window.getControl(SearchView.STATUS_LABEL_ID).getLabel() == ""


def test_back_is_a_no_op_pass_through():
    win = SearchView(FakeWindow())
    win.handle_action(xbmcgui.Action(xbmcgui.ACTION_NAV_BACK))
    # No assertion beyond "doesn't raise" - Back is centralized in
    # MainWindow now; SearchView never sees ACTION_NAV_BACK in practice.


from unittest.mock import patch

import xbmcaddon

from lib import providers
from lib.twitch import gql


def test_start_search_merges_twitch_and_kick_results_by_viewer_count():
    twitch_raw = [
        {"user_id": "1", "user_login": "alice", "user_name": "Alice", "viewer_count": 50, "game_name": "A"},
    ]
    kick_normalized = [
        {
            "platform": "kick",
            "id": "2",
            "login": "kickuser",
            "display_name": "kickuser",
            "is_live": True,
            "viewer_count": 500,
            "game_name": "B",
            "thumbnail_url": "",
        }
    ]
    with patch.object(gql, "search", return_value=(twitch_raw, None)), patch.object(
        providers, "get_kick_search_results", return_value=kick_normalized
    ):
        win = SearchView(FakeWindow())
        win.window.getControl(SearchView.SEARCH_INPUT_ID).setText("query")
        win.start_search()
        win.handle_action(xbmcgui.Action(999))  # drains _update_queue, see handle_action

    assert [r["login"] for r in win.search_results] == ["kickuser", "alice"]
    results_control = win.window.getControl(SearchView.RESULTS_LIST_ID)
    assert results_control.size() == 2
    assert results_control.getListItem(0).getProperty("platform") == "kick"
    assert results_control.getListItem(1).getProperty("platform") == "twitch"


def test_load_next_page_does_not_refetch_or_duplicate_kick_results():
    twitch_page_1 = [{"user_id": "1", "user_login": "alice", "user_name": "Alice", "viewer_count": 50, "game_name": "A"}]
    twitch_page_2 = [{"user_id": "2", "user_login": "bob", "user_name": "Bob", "viewer_count": 10, "game_name": "A"}]
    kick_normalized = [
        {
            "platform": "kick",
            "id": "3",
            "login": "kickuser",
            "display_name": "kickuser",
            "is_live": True,
            "viewer_count": 500,
            "game_name": "B",
            "thumbnail_url": "",
        }
    ]
    with patch.object(gql, "search", return_value=(twitch_page_1, "cursor-1")), patch.object(
        providers, "get_kick_search_results", return_value=kick_normalized
    ) as mock_kick_search:
        win = SearchView(FakeWindow())
        win.window.getControl(SearchView.SEARCH_INPUT_ID).setText("query")
        win.start_search()
        win.handle_action(xbmcgui.Action(999))

    assert mock_kick_search.call_count == 1

    with patch.object(gql, "search", return_value=(twitch_page_2, None)):
        win.load_next_page()
        win.handle_action(xbmcgui.Action(999))

    # Still exactly 1 Kick entry, not re-fetched or duplicated.
    kick_entries = [r for r in win.search_results if r["platform"] == "kick"]
    assert len(kick_entries) == 1
    assert mock_kick_search.call_count == 1
    assert [r["login"] for r in win.search_results] == ["kickuser", "alice", "bob"]


def test_play_selected_dispatches_to_the_selected_results_platform():
    with patch.object(providers, "resolve_stream_url", return_value="https://kick.example/x.m3u8") as mock_resolve, \
         patch("lib.views.search_view.player.play_stream") as mock_play:
        win = SearchView(FakeWindow())
        win.search_results = [
            {"platform": "kick", "login": "kickuser", "display_name": "kickuser"},
        ]
        win.window.getControl(SearchView.RESULTS_LIST_ID).addItem("kickuser")
        win.window.getControl(SearchView.RESULTS_LIST_ID).selectItem(0)
        win.play_selected()

    call_args = mock_resolve.call_args
    assert call_args.args[1] == "kick"
    assert call_args.args[2] == "kickuser"
    mock_play.assert_called_once_with("https://kick.example/x.m3u8", "kickuser", platform="kick")


def test_play_selected_shows_error_and_does_not_raise_when_stream_unavailable():
    with patch.object(
        providers, "resolve_stream_url", side_effect=providers.StreamUnavailableError("kickuser")
    ), patch("lib.views.search_view.player.play_stream") as mock_play:
        win = SearchView(FakeWindow())
        win.search_results = [
            {"platform": "kick", "login": "kickuser", "display_name": "kickuser"},
        ]
        win.window.getControl(SearchView.RESULTS_LIST_ID).addItem("kickuser")
        win.window.getControl(SearchView.RESULTS_LIST_ID).selectItem(0)
        win.play_selected()  # must not raise

    assert win.window.getControl(SearchView.STATUS_LABEL_ID).getLabel() != ""
    mock_play.assert_not_called()


def test_context_menu_on_kick_result_adds_favorite():
    xbmcgui.Dialog.next_contextmenu_choice = 0
    xbmcgui.Dialog.notifications = []
    addon = xbmcaddon.Addon()
    with patch("xbmcaddon.Addon", return_value=addon):
        win = SearchView(FakeWindow())
        win.search_results = [
            {"platform": "kick", "login": "kickuser", "display_name": "kickuser"},
        ]
        win.window.getControl(SearchView.RESULTS_LIST_ID).addItem("kickuser")
        win.window.getControl(SearchView.RESULTS_LIST_ID).selectItem(0)
        win.window.setFocusId(SearchView.RESULTS_LIST_ID)
        win.handle_action(xbmcgui.Action(xbmcgui.ACTION_CONTEXT_MENU))

    assert providers.get_kick_favorites(addon) == ["kickuser"]


def test_context_menu_on_twitch_result_does_nothing():
    xbmcgui.Dialog.next_contextmenu_choice = 0
    xbmcgui.Dialog.notifications = []
    addon = xbmcaddon.Addon()
    with patch("xbmcaddon.Addon", return_value=addon):
        win = SearchView(FakeWindow())
        win.search_results = [
            {"platform": "twitch", "login": "alice", "display_name": "Alice"},
        ]
        win.window.getControl(SearchView.RESULTS_LIST_ID).addItem("Alice")
        win.window.getControl(SearchView.RESULTS_LIST_ID).selectItem(0)
        win.window.setFocusId(SearchView.RESULTS_LIST_ID)
        win.handle_action(xbmcgui.Action(xbmcgui.ACTION_CONTEXT_MENU))

    assert providers.get_kick_favorites(addon) == []
    assert xbmcgui.Dialog.notifications == []
