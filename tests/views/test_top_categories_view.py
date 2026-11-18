from unittest.mock import patch

import requests
import xbmcaddon
import xbmcgui

from lib.twitch import api
from lib.twitch.auth import save_token
from lib.views.top_categories_view import TopCategoriesView

FakeAddon = xbmcaddon.Addon
TOKEN = {"access_token": "tok", "refresh_token": "ref", "user_id": "u1"}

GAMES = [
    {"id": "509658", "name": "Just Chatting",
     "box_art_url": "https://x.invalid/509658-{width}x{height}.jpg"},
    {"id": "21779", "name": "League of Legends",
     "box_art_url": "https://x.invalid/21779-{width}x{height}.jpg"},
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


def _select(view, index):
    view.window.getControl(TopCategoriesView.CATEGORY_LIST_ID).selectItem(index)
    view.window.setFocusId(TopCategoriesView.CATEGORY_LIST_ID)
    view.handle_action(xbmcgui.Action(xbmcgui.ACTION_SELECT_ITEM))


def _activate(view, context):
    view.context = context
    view.activate()


def test_activate_loads_top_100_with_box_art():
    addon = _addon_with_token(TOKEN)
    with patch("xbmcaddon.Addon", return_value=addon), patch.object(
        api, "get_top_games", return_value=GAMES
    ) as mock_games:
        view = TopCategoriesView(FakeWindow())
        _activate(view, {"refresh": True})
    assert mock_games.call_args.kwargs["first"] == 100
    control = view.window.getControl(TopCategoriesView.CATEGORY_LIST_ID)
    assert [control.getListItem(i).getLabel() for i in range(control.size())] == [
        "Just Chatting",
        "League of Legends",
    ]
    assert control.getListItem(0).getArt("thumb") == "https://x.invalid/509658-285x380.jpg"
    assert control.getListItem(0).getProperty("game_id") == "509658"
    assert view.window.getFocusId() == TopCategoriesView.CATEGORY_LIST_ID
    assert view.window.getControl(TopCategoriesView.TITLE_LABEL_ID).getLabel() == "Top Categories"


def test_selecting_a_tile_opens_category_streams():
    addon = _addon_with_token(TOKEN)
    with patch("xbmcaddon.Addon", return_value=addon), patch.object(
        api, "get_top_games", return_value=GAMES
    ):
        view = TopCategoriesView(FakeWindow())
        _activate(view, {"refresh": True})
        _select(view, 1)
    assert view.window.switched_to[-1] == (
        "category_streams",
        {"game_id": "21779", "game_name": "League of Legends"},
    )


def test_back_from_streams_restores_selection_without_refetch():
    addon = _addon_with_token(TOKEN)
    with patch("xbmcaddon.Addon", return_value=addon), patch.object(
        api, "get_top_games", return_value=GAMES
    ) as mock_games:
        view = TopCategoriesView(FakeWindow())
        _activate(view, {"refresh": True})
        _select(view, 1)
        _activate(view, None)
    assert mock_games.call_count == 1
    control = view.window.getControl(TopCategoriesView.CATEGORY_LIST_ID)
    assert control.size() == 2
    assert control.getSelectedPosition() == 1
    assert view.window.getFocusId() == TopCategoriesView.CATEGORY_LIST_ID


def test_reentry_from_discover_resets_selection():
    addon = _addon_with_token(TOKEN)
    with patch("xbmcaddon.Addon", return_value=addon), patch.object(
        api, "get_top_games", side_effect=[GAMES, GAMES[:1]]
    ) as mock_games:
        view = TopCategoriesView(FakeWindow())
        _activate(view, {"refresh": True})
        _select(view, 1)
        _activate(view, {"refresh": True})
    assert mock_games.call_count == 2
    control = view.window.getControl(TopCategoriesView.CATEGORY_LIST_ID)
    assert control.size() == 1
    assert control._selected_index == 0


def test_back_with_no_cached_categories_refetches():
    addon = _addon_with_token(TOKEN)
    with patch("xbmcaddon.Addon", return_value=addon), patch.object(
        api, "get_top_games", side_effect=[requests.ConnectionError("down"), GAMES]
    ) as mock_games:
        view = TopCategoriesView(FakeWindow())
        _activate(view, {"refresh": True})
        assert view.window.getControl(TopCategoriesView.ERROR_LABEL_ID).getLabel() != ""
        _activate(view, None)
    assert mock_games.call_count == 2
    assert view.window.getControl(TopCategoriesView.CATEGORY_LIST_ID).size() == 2
    assert view.window.getControl(TopCategoriesView.ERROR_LABEL_ID).getLabel() == ""


def test_category_without_box_art_still_renders():
    addon = _addon_with_token(TOKEN)
    games = [{"id": "1", "name": "No Art", "box_art_url": ""}]
    with patch("xbmcaddon.Addon", return_value=addon), patch.object(
        api, "get_top_games", return_value=games
    ):
        view = TopCategoriesView(FakeWindow())
        _activate(view, {"refresh": True})
    control = view.window.getControl(TopCategoriesView.CATEGORY_LIST_ID)
    assert control.size() == 1
    assert control.getListItem(0).getLabel() == "No Art"
    assert not control.getListItem(0).getArt("thumb")


def test_empty_result_shows_message():
    addon = _addon_with_token(TOKEN)
    with patch("xbmcaddon.Addon", return_value=addon), patch.object(
        api, "get_top_games", return_value=[]
    ):
        view = TopCategoriesView(FakeWindow())
        _activate(view, {"refresh": True})
    assert (
        view.window.getControl(TopCategoriesView.EMPTY_LABEL_ID).getLabel()
        == "No categories right now."
    )


def test_missing_token_shows_error_and_relogin():
    addon = _addon_with_token(None)
    with patch("xbmcaddon.Addon", return_value=addon), patch.object(api, "get_top_games") as mock_games:
        view = TopCategoriesView(FakeWindow())
        _activate(view, {"refresh": True})
    mock_games.assert_not_called()
    assert view.window.getControl(TopCategoriesView.ERROR_LABEL_ID).getLabel() != ""
    assert view.window.getControl(TopCategoriesView.RELOGIN_BUTTON_ID).isVisible() is True
    assert view.window.getFocusId() == TopCategoriesView.RELOGIN_BUTTON_ID


def test_expired_token_refreshes_then_loads():
    addon = _addon_with_token(TOKEN)
    refreshed = {"access_token": "new", "refresh_token": "ref2"}
    with patch("xbmcaddon.Addon", return_value=addon), patch.object(
        api, "get_top_games", side_effect=[api.TokenExpiredError(), GAMES]
    ) as mock_games, patch(
        "lib.views.top_categories_view.auth.refresh_access_token", return_value=refreshed
    ):
        view = TopCategoriesView(FakeWindow())
        _activate(view, {"refresh": True})
    assert mock_games.call_args.args[0] == "new"
    assert view.window.getControl(TopCategoriesView.CATEGORY_LIST_ID).size() == 2


def test_relogin_button_switches_to_login():
    view = TopCategoriesView(FakeWindow())
    view.window.setFocusId(TopCategoriesView.RELOGIN_BUTTON_ID)
    view.handle_action(xbmcgui.Action(xbmcgui.ACTION_SELECT_ITEM))
    assert view.window.switched_to[-1] == ("login", None)
