from unittest.mock import patch

import xbmcaddon
import xbmcgui

from lib.twitch import api, gql
from lib.twitch.auth import save_token
from lib.windows.discover import DiscoverWindow
from lib.windows.home import HomeWindow, _NO_LIVE_MESSAGE, _build_list_item, _merge_channels
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


def test_back_requests_quit_when_nothing_is_playing():
    # Back no longer closes the window directly; it asks main.run() to show a
    # confirmation dialog and only tear down if the user confirms.
    win = HomeWindow("script-twitch-center-home.xml", "/tmp")
    with patch("lib.windows.home.xbmc.Player") as mock_player_cls:
        mock_player_cls.return_value.isPlaying.return_value = False
        with patch.object(win, "close") as mock_close:
            win.onAction(xbmcgui.Action(xbmcgui.ACTION_NAV_BACK))
    mock_close.assert_not_called()
    assert not win.closed_event.is_set()
    assert win.closed_event.quit_requested is True


def test_back_stops_playback_instead_of_requesting_quit_when_stream_is_playing():
    # Kodi's own fullscreen-video Back only exits the fullscreen view, it
    # doesn't stop playback - Home regains focus with the stream still
    # running behind it. A Back press here must stop that stream rather
    # than treating it as a quit request.
    win = HomeWindow("script-twitch-center-home.xml", "/tmp")
    with patch("lib.windows.home.xbmc.Player") as mock_player_cls:
        mock_player_cls.return_value.isPlaying.return_value = True
        with patch.object(win, "close") as mock_close:
            win.onAction(xbmcgui.Action(xbmcgui.ACTION_NAV_BACK))
        mock_player_cls.return_value.stop.assert_called_once()
    mock_close.assert_not_called()
    assert not win.closed_event.is_set()
    assert not getattr(win.closed_event, "quit_requested", False)


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
    assert control.size() == 2
    assert win.getFocusId() == HomeWindow.CHANNEL_LIST_ID
    assert all(item.getProperty("is_live") == "true" for item in control._items)


def test_oninit_keeps_relogin_button_visible_even_without_an_error():
    # Doubles as a voluntary "switch account / re-authorize" affordance, not
    # just an error-recovery button - always reachable, not just on failure.
    addon = _addon_with_token({"access_token": "tok", "refresh_token": "ref", "user_id": "u1"})
    with patch("xbmcaddon.Addon", return_value=addon), patch.object(
        api, "get_followed_channels", return_value=FOLLOWED
    ), patch.object(api, "get_live_status", return_value=LIVE), patch.object(
        gql, "get_followed_live_games", return_value=[]
    ):
        win = HomeWindow("script-twitch-center-home.xml", "/tmp")
        win.onInit()
    assert win.getControl(HomeWindow.RELOGIN_BUTTON_ID).isVisible() is True


def test_oninit_still_hides_offline_channels_when_setting_is_off():
    addon = _addon_with_token({"access_token": "tok", "refresh_token": "ref", "user_id": "u1"})
    with patch("xbmcaddon.Addon", return_value=addon), patch.object(
        api, "get_followed_channels", return_value=FOLLOWED
    ), patch.object(api, "get_live_status", return_value=LIVE), patch.object(
        gql, "get_followed_live_games", return_value=[]
    ):
        win = HomeWindow("script-twitch-center-home.xml", "/tmp")
        win.onInit()
    control = win.getControl(HomeWindow.CHANNEL_LIST_ID)
    assert control.size() == 2


def test_oninit_shows_offline_channels_after_live_ones_when_setting_is_on():
    addon = _addon_with_token({"access_token": "tok", "refresh_token": "ref", "user_id": "u1"})
    addon.setSetting("show_offline_channels", True)
    with patch("xbmcaddon.Addon", return_value=addon), patch.object(
        api, "get_followed_channels", return_value=FOLLOWED
    ), patch.object(api, "get_live_status", return_value=LIVE), patch.object(
        gql, "get_followed_live_games", return_value=[]
    ):
        win = HomeWindow("script-twitch-center-home.xml", "/tmp")
        win.onInit()
    control = win.getControl(HomeWindow.CHANNEL_LIST_ID)
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
        win = HomeWindow("script-twitch-center-home.xml", "/tmp")
        win.onInit()
        games_control = win.getControl(HomeWindow.GAMES_LIST_ID)
        games_control.selectItem(1)  # "Just Chatting" - Bob is live playing it
        win.setFocusId(HomeWindow.GAMES_LIST_ID)
        win.onAction(xbmcgui.Action(xbmcgui.ACTION_SELECT_ITEM))

    control = win.getControl(HomeWindow.CHANNEL_LIST_ID)
    assert [item.getLabel() for item in control._items] == ["Bob"]


def test_oninit_shows_no_live_message_when_all_followed_channels_are_offline():
    addon = _addon_with_token({"access_token": "tok", "refresh_token": "ref", "user_id": "u1"})
    with patch("xbmcaddon.Addon", return_value=addon), patch.object(
        api, "get_followed_channels", return_value=FOLLOWED
    ), patch.object(api, "get_live_status", return_value=[]), patch.object(
        gql, "get_followed_live_games", return_value=[]
    ):
        win = HomeWindow("script-twitch-center-home.xml", "/tmp")
        win.onInit()
    assert win.getControl(HomeWindow.CHANNEL_LIST_ID).size() == 0
    assert win.getControl(HomeWindow.EMPTY_LABEL_ID).getLabel() == _NO_LIVE_MESSAGE


def test_oninit_passes_website_token_setting_to_followed_live_games():
    addon = _addon_with_token({"access_token": "tok", "refresh_token": "ref", "user_id": "u1"})
    addon.setSetting("website_token", "my-website-token")
    with patch("xbmcaddon.Addon", return_value=addon), patch.object(
        api, "get_followed_channels", return_value=FOLLOWED
    ), patch.object(api, "get_live_status", return_value=LIVE), patch.object(
        gql, "get_followed_live_games", return_value=[]
    ) as mock_games:
        win = HomeWindow("script-twitch-center-home.xml", "/tmp")
        win.onInit()
    mock_games.assert_called_once_with("my-website-token")


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
    # The channel list can't take focus while empty (the skin's
    # <defaultcontrol> targets it unconditionally) - Discover is the
    # explicit fallback rather than leaving Kodi's own fallback search to
    # land on an arbitrary button.
    assert win.getFocusId() == HomeWindow.DISCOVER_BUTTON_ID


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
    assert win.getControl(HomeWindow.CHANNEL_LIST_ID).size() == 0
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
        "lib.windows.home.auth.refresh_access_token", return_value=None
    ) as mock_refresh, patch("lib.windows.home.xbmc.log") as mock_log:
        win = HomeWindow("script-twitch-center-home.xml", "/tmp")
        win.onInit()
        # refresh_access_token's on_error callback is home.py's only way to
        # surface *why* the refresh failed, since auth.py stays free of xbmc
        # imports - confirm the wiring is actually connected.
        assert mock_refresh.call_args.kwargs["on_error"] is not None
        mock_refresh.call_args.kwargs["on_error"]("HTTP 401: invalid_grant")
        assert any(
            "invalid_grant" in call.args[0] for call in mock_log.call_args_list
        )

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
    # See test_oninit_shows_empty_state_when_no_followed_channels: same
    # explicit-focus race, this time the fallback is the Relogin button.
    assert win.getFocusId() == HomeWindow.RELOGIN_BUTTON_ID


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


def test_relogin_chain_requests_quit_only_when_login_window_back_is_pressed():
    """The event main.run() waits on must survive Home -> Login navigation.
    The login window signals a quit request on Back; main.run() then shows
    the confirmation dialog and performs the actual teardown."""
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

    assert login_window.closed_event.quit_requested is True
    assert not shared_event.is_set()


def test_selecting_settings_button_opens_addon_settings_and_reloads():
    addon = _addon_with_token({"access_token": "tok", "refresh_token": "ref", "user_id": "u1"})
    with patch("xbmcaddon.Addon", return_value=addon), patch.object(
        api, "get_followed_channels", return_value=FOLLOWED
    ), patch.object(api, "get_live_status", return_value=LIVE), patch.object(
        gql, "get_followed_live_games", return_value=[]
    ), patch.object(addon, "openSettings") as mock_open_settings:
        win = HomeWindow("script-twitch-center-home.xml", "/tmp")
        win.onInit()
        win.setFocusId(HomeWindow.SETTINGS_BUTTON_ID)
        win.onAction(xbmcgui.Action(xbmcgui.ACTION_SELECT_ITEM))

    mock_open_settings.assert_called_once()
    # Reloaded (not just left showing stale data) - the channel list is still
    # populated, proving onInit ran again rather than the window silently
    # doing nothing after openSettings() returned.
    assert win.getControl(HomeWindow.CHANNEL_LIST_ID).size() == 2


def test_selecting_settings_button_does_not_reload_if_window_already_closed():
    # openSettings() blocks; if the shared closed_event got set while it was
    # open (e.g. the whole script is shutting down), reloading afterwards
    # would resurrect a window nothing is waiting on anymore.
    addon = _addon_with_token({"access_token": "tok", "refresh_token": "ref", "user_id": "u1"})
    with patch("xbmcaddon.Addon", return_value=addon), patch.object(
        api, "get_followed_channels", return_value=FOLLOWED
    ), patch.object(api, "get_live_status", return_value=LIVE), patch.object(
        gql, "get_followed_live_games", return_value=[]
    ):
        win = HomeWindow("script-twitch-center-home.xml", "/tmp")
        win.onInit()

        def _close_during_settings():
            win.closed_event.set()

        with patch.object(
            addon, "openSettings", side_effect=_close_during_settings
        ) as mock_open_settings, patch.object(
            win, "onInit", wraps=win.onInit
        ) as mock_oninit:
            win.setFocusId(HomeWindow.SETTINGS_BUTTON_ID)
            win.onAction(xbmcgui.Action(xbmcgui.ACTION_SELECT_ITEM))

    mock_open_settings.assert_called_once()
    mock_oninit.assert_not_called()


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
    assert channel_control.size() == 2


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
    assert channel_control.size() == 2
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

    assert win.getControl(HomeWindow.CHANNEL_LIST_ID).size() == 2

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


def test_discover_chain_requests_quit_only_when_discover_back_is_pressed():
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

    assert discover_window.closed_event.quit_requested is True
    assert not shared_event.is_set()


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
    ), patch(
        "lib.windows.home.stream.resolve_stream_url",
        return_value="https://example.invalid/stream.m3u8",
    ) as mock_resolve, patch(
        "lib.windows.home.player.play_stream", return_value=True
    ) as mock_play:
        win = HomeWindow("script-twitch-center-home.xml", "/tmp")
        win.onInit()
        channel_control = win.getControl(HomeWindow.CHANNEL_LIST_ID)
        # LIVE-first order per _merge_channels: Carol (200 viewers) then Bob (50).
        channel_control.selectItem(0)  # Carol, live
        win.setFocusId(HomeWindow.CHANNEL_LIST_ID)
        win.onAction(xbmcgui.Action(xbmcgui.ACTION_SELECT_ITEM))

    mock_resolve.assert_called_once_with("carol", "")
    mock_play.assert_called_once_with("https://example.invalid/stream.m3u8", "carol")


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
    assert win.getControl(HomeWindow.CHANNEL_LIST_ID).size() == 2


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

    games_control = win.getControl(HomeWindow.GAMES_LIST_ID)
    games_control.selectItem(0)  # "All"
    win.setFocusId(HomeWindow.GAMES_LIST_ID)
    win.onAction(xbmcgui.Action(xbmcgui.ACTION_SELECT_ITEM))

    assert win.getControl(HomeWindow.ERROR_LABEL_ID).getLabel() == ""


def test_selecting_a_live_channel_clears_stale_error_on_successful_retry():
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

    with patch("xbmcaddon.Addon", return_value=addon), patch(
        "lib.windows.home.stream.resolve_stream_url",
        return_value="https://example.invalid/stream.m3u8",
    ), patch("lib.windows.home.player.play_stream", return_value=True):
        win.onAction(xbmcgui.Action(xbmcgui.ACTION_SELECT_ITEM))

    assert win.getControl(HomeWindow.ERROR_LABEL_ID).getLabel() == ""


def test_selecting_a_live_channel_shows_error_on_unexpected_exception():
    addon = _addon_with_token({"access_token": "tok", "refresh_token": "ref", "user_id": "u1"})
    with patch("xbmcaddon.Addon", return_value=addon), patch.object(
        api, "get_followed_channels", return_value=FOLLOWED
    ), patch.object(api, "get_live_status", return_value=LIVE), patch.object(
        gql, "get_followed_live_games", return_value=[]
    ), patch(
        "lib.windows.home.stream.resolve_stream_url",
        side_effect=RuntimeError("boom"),
    ):
        win = HomeWindow("script-twitch-center-home.xml", "/tmp")
        win.onInit()
        channel_control = win.getControl(HomeWindow.CHANNEL_LIST_ID)
        channel_control.selectItem(0)
        win.setFocusId(HomeWindow.CHANNEL_LIST_ID)
        win.onAction(xbmcgui.Action(xbmcgui.ACTION_SELECT_ITEM))

    assert win.getControl(HomeWindow.ERROR_LABEL_ID).getLabel() != ""
    assert win.getControl(HomeWindow.CHANNEL_LIST_ID).size() == 2


def test_missing_token_at_click_time_shows_an_error_instead_of_no_op():
    from lib.twitch.auth import clear_token

    addon = _addon_with_token({"access_token": "tok", "refresh_token": "ref", "user_id": "u1"})
    with patch("xbmcaddon.Addon", return_value=addon), patch.object(
        api, "get_followed_channels", return_value=FOLLOWED
    ), patch.object(api, "get_live_status", return_value=LIVE), patch.object(
        gql, "get_followed_live_games", return_value=[]
    ):
        win = HomeWindow("script-twitch-center-home.xml", "/tmp")
        win.onInit()
        # Another window cleared the token between onInit and the click.
        clear_token(addon)
        channel_control = win.getControl(HomeWindow.CHANNEL_LIST_ID)
        channel_control.selectItem(0)
        win.setFocusId(HomeWindow.CHANNEL_LIST_ID)
        win.onAction(xbmcgui.Action(xbmcgui.ACTION_SELECT_ITEM))

    assert win.getControl(HomeWindow.ERROR_LABEL_ID).getLabel() != ""
    assert win.getControl(HomeWindow.CHANNEL_LIST_ID).size() == 2
