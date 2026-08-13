from unittest.mock import MagicMock, patch

import xbmcgui

from lib.windows.main_window import MainWindow


class FakeView:
    def __init__(self, window, closed_event=None):
        self.window = window
        self.closed_event = closed_event
        self.activate_calls = 0
        self.actions = []
        self.clicks = []

    def activate(self):
        self.activate_calls += 1

    def handle_action(self, action):
        self.actions.append(action)

    def handle_click(self, control_id):
        self.clicks.append(control_id)


def _make_window(initial_view="menu"):
    views = {name: FakeView for name in ("login", "menu", "live_streams", "discover", "search")}
    return MainWindow(
        "script-twitch-center-main.xml", "/tmp", initial_view=initial_view, view_classes=views
    )


def test_oninit_activates_the_initial_view_and_shows_only_its_group():
    win = _make_window(initial_view="menu")
    win.onInit()
    assert win._active_name == "menu"
    assert win._views["menu"].activate_calls == 1
    assert win.getControl(win.GROUP_IDS["menu"]).isVisible() is True
    for name, group_id in win.GROUP_IDS.items():
        if name != "menu":
            assert win.getControl(group_id).isVisible() is False


def test_switch_view_hides_old_group_shows_new_group_and_activates_target():
    win = _make_window(initial_view="menu")
    win.onInit()
    win._switch_view("discover")
    assert win._active_name == "discover"
    assert win._views["discover"].activate_calls == 1
    assert win.getControl(win.GROUP_IDS["discover"]).isVisible() is True
    assert win.getControl(win.GROUP_IDS["menu"]).isVisible() is False


def test_onaction_back_switches_to_menu_from_a_non_menu_view():
    win = _make_window(initial_view="discover")
    win.onInit()
    with patch("lib.windows.main_window.xbmc.Player") as mock_player_cls:
        mock_player_cls.return_value.isPlaying.return_value = False
        win.onAction(xbmcgui.Action(xbmcgui.ACTION_NAV_BACK))
    assert win._active_name == "menu"
    assert not win.closed_event.is_set()
    assert not getattr(win.closed_event, "quit_requested", False)


def test_onaction_back_requests_quit_from_menu_when_nothing_playing():
    win = _make_window(initial_view="menu")
    win.onInit()
    with patch("lib.windows.main_window.xbmc.Player") as mock_player_cls:
        mock_player_cls.return_value.isPlaying.return_value = False
        win.onAction(xbmcgui.Action(xbmcgui.ACTION_NAV_BACK))
    assert win.closed_event.quit_requested is True
    assert win._active_name == "menu"


def test_onaction_back_stops_playback_instead_of_navigating_when_playing():
    win = _make_window(initial_view="discover")
    win.onInit()
    with patch("lib.windows.main_window.xbmc.Player") as mock_player_cls:
        mock_player_cls.return_value.isPlaying.return_value = True
        win.onAction(xbmcgui.Action(xbmcgui.ACTION_NAV_BACK))
        mock_player_cls.return_value.stop.assert_called_once()
    # Still on Discover - Back stopped the stream, didn't navigate away.
    assert win._active_name == "discover"
    assert not win.closed_event.quit_requested


def test_onaction_delegates_non_back_actions_to_the_active_view():
    win = _make_window(initial_view="search")
    win.onInit()
    action = xbmcgui.Action(xbmcgui.ACTION_SELECT_ITEM)
    win.onAction(action)
    assert win._views["search"].actions == [action]


def test_onclick_delegates_to_the_active_view():
    win = _make_window(initial_view="live_streams")
    win.onInit()
    win.onClick(201)
    assert win._views["live_streams"].clicks == [201]
