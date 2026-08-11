"""Discover screen: browse live channels by any game, or search any channel by name."""
import threading

import xbmc
import xbmcaddon
import xbmcgui

from lib.twitch import api, auth
from lib.windows.login import LoginWindow

RESULTS_LIST_ID = 101
EMPTY_LABEL_ID = 102
ERROR_LABEL_ID = 103
RELOGIN_BUTTON_ID = 104
GAMES_LIST_ID = 105
SEARCH_EDIT_ID = 106
SEARCH_BUTTON_ID = 107

_MISSING_TOKEN_MESSAGE = "You're not logged in. Reopen the addon to log in."
_EMPTY_RESULTS_MESSAGE = "Nothing found."
_EMPTY_GAMES_MESSAGE = "No games to browse right now."
_NETWORK_ERROR_MESSAGE = "Couldn't reach Twitch. Check your connection and reopen the addon."
_RELOGIN_MESSAGE = "Your session expired. Log in again to continue."


def _thumbnail_url(raw_url, width=320, height=180):
    return raw_url.replace("{width}", str(width)).replace("{height}", str(height))


def _build_stream_item(stream):
    item = xbmcgui.ListItem(stream["user_name"])
    item.setLabel2(stream["game_name"] + " - " + str(stream["viewer_count"]) + " viewers")
    item.setArt({"thumb": _thumbnail_url(stream["thumbnail_url"])})
    item.setProperty("broadcaster_id", stream["user_id"])
    return item


def _build_channel_item(channel):
    item = xbmcgui.ListItem(channel["display_name"])
    if channel.get("is_live"):
        item.setLabel2("Live - " + channel.get("game_name", ""))
    else:
        item.setLabel2("Offline")
    item.setArt({"thumb": channel.get("thumbnail_url", "")})
    item.setProperty("broadcaster_id", channel.get("id", ""))
    return item


class DiscoverWindow(xbmcgui.WindowXML):
    RESULTS_LIST_ID = RESULTS_LIST_ID
    EMPTY_LABEL_ID = EMPTY_LABEL_ID
    ERROR_LABEL_ID = ERROR_LABEL_ID
    RELOGIN_BUTTON_ID = RELOGIN_BUTTON_ID
    GAMES_LIST_ID = GAMES_LIST_ID
    SEARCH_EDIT_ID = SEARCH_EDIT_ID
    SEARCH_BUTTON_ID = SEARCH_BUTTON_ID

    def __init__(self, *args, closed_event=None, **kwargs):
        super().__init__(*args, **kwargs)
        # Shared across the whole window-navigation chain - see LoginWindow.
        self.closed_event = closed_event or threading.Event()

    def onInit(self):
        addon = xbmcaddon.Addon()
        client_id = addon.getSetting("client_id")
        token = auth.load_token(addon)
        if token is None:
            self._show_error(_MISSING_TOKEN_MESSAGE)
            return
        if not token.get("user_id"):
            auth.clear_token(addon)
            self._show_error(_RELOGIN_MESSAGE)
            return

        try:
            self._load_games(addon, client_id, token)
        except api.TokenExpiredError:
            self._handle_expired_token(addon, client_id, token)
        except Exception as exc:
            xbmc.log(
                "script.twitch.center: Discover screen failed to load: " + repr(exc),
                xbmc.LOGERROR,
            )
            self._show_error(_NETWORK_ERROR_MESSAGE)

    def _load_games(self, addon, client_id, token):
        games = api.get_top_games(token["access_token"], client_id)
        self._populate_games(games)

    def _handle_expired_token(self, addon, client_id, token, on_success=None, on_error=None):
        """Refresh the access token, then redo whatever the user was doing.

        on_success is a callable taking the refreshed token; it defaults to
        reloading the top-games row (onInit's behaviour). Callers that were
        mid-action (browse-by-game, search) pass a closure that retries THAT
        action, so an expiry doesn't silently discard the user's click."""
        new_token = auth.refresh_access_token(client_id, token["refresh_token"])
        if new_token is None:
            auth.clear_token(addon)
            self._show_error(_RELOGIN_MESSAGE)
            return

        new_token["user_id"] = token.get("user_id")
        new_token["login"] = token.get("login")
        new_token["display_name"] = token.get("display_name")
        auth.save_token(new_token, addon)

        if on_success is None:
            on_success = self._load_games
        if on_error is None:
            on_error = self._show_error

        try:
            on_success(addon, client_id, new_token)
        except api.TokenExpiredError:
            auth.clear_token(addon)
            self._show_error(_RELOGIN_MESSAGE)
        except Exception as exc:
            xbmc.log(
                "script.twitch.center: Discover screen failed after token refresh: "
                + repr(exc),
                xbmc.LOGERROR,
            )
            on_error(_NETWORK_ERROR_MESSAGE)

    def _populate_games(self, games):
        self.getControl(self.RELOGIN_BUTTON_ID).setVisible(False)
        control = self.getControl(self.GAMES_LIST_ID)
        control.reset()
        if not games:
            # Without this the row would just render blank with no
            # explanation, unlike the results list which already says so.
            self.getControl(self.EMPTY_LABEL_ID).setLabel(_EMPTY_GAMES_MESSAGE)
            return
        items = []
        for game in games:
            item = xbmcgui.ListItem(game["name"])
            item.setProperty("game_id", game["id"])
            items.append(item)
        control.addItems(items)

    def _populate_results(self, items):
        self.getControl(self.EMPTY_LABEL_ID).setLabel("")
        self.getControl(self.ERROR_LABEL_ID).setLabel("")
        control = self.getControl(self.RESULTS_LIST_ID)
        control.reset()
        if not items:
            self.getControl(self.EMPTY_LABEL_ID).setLabel(_EMPTY_RESULTS_MESSAGE)
            return
        control.addItems(items)

    def _load_streams_for_game(self, addon, client_id, token, game_id):
        streams = api.get_live_streams_by_game(token["access_token"], client_id, game_id)
        self._populate_results([_build_stream_item(stream) for stream in streams])

    def _load_search_results(self, addon, client_id, token, query):
        channels = api.search_channels(token["access_token"], client_id, query)
        self._populate_results([_build_channel_item(channel) for channel in channels])

    def _on_game_selected(self):
        selected = self.getControl(self.GAMES_LIST_ID).getSelectedItem()
        if selected is None:
            return
        addon = xbmcaddon.Addon()
        client_id = addon.getSetting("client_id")
        token = auth.load_token(addon)
        if token is None:
            self._show_results_error(_MISSING_TOKEN_MESSAGE)
            return
        game_id = selected.getProperty("game_id")
        try:
            self._load_streams_for_game(addon, client_id, token, game_id)
        except api.TokenExpiredError:
            # Retry THIS game with the refreshed token rather than just
            # reloading the games row, which would silently drop the click.
            self._handle_expired_token(
                addon,
                client_id,
                token,
                on_success=lambda a, c, t: self._load_streams_for_game(a, c, t, game_id),
                on_error=self._show_results_error,
            )
        except Exception as exc:
            xbmc.log(
                "script.twitch.center: Discover browse-by-game failed: " + repr(exc),
                xbmc.LOGERROR,
            )
            self._show_results_error(_NETWORK_ERROR_MESSAGE)

    def _on_search(self):
        query = self.getControl(self.SEARCH_EDIT_ID).getText()
        if not query:
            return
        addon = xbmcaddon.Addon()
        client_id = addon.getSetting("client_id")
        token = auth.load_token(addon)
        if token is None:
            self._show_results_error(_MISSING_TOKEN_MESSAGE)
            return
        try:
            self._load_search_results(addon, client_id, token, query)
        except api.TokenExpiredError:
            self._handle_expired_token(
                addon,
                client_id,
                token,
                on_success=lambda a, c, t: self._load_search_results(a, c, t, query),
                on_error=self._show_results_error,
            )
        except Exception as exc:
            xbmc.log("script.twitch.center: Discover search failed: " + repr(exc), xbmc.LOGERROR)
            self._show_results_error(_NETWORK_ERROR_MESSAGE)

    def _show_error(self, message):
        """Fatal failure (onInit / expired session): the whole screen is
        unusable, so wipe everything and offer the re-login button."""
        self.getControl(self.GAMES_LIST_ID).reset()
        self.getControl(self.RESULTS_LIST_ID).reset()
        self.getControl(self.EMPTY_LABEL_ID).setLabel("")
        self.getControl(self.ERROR_LABEL_ID).setLabel(message)
        self.getControl(self.RELOGIN_BUTTON_ID).setVisible(True)

    def _show_results_error(self, message):
        """Transient failure of one browse/search: keep the top-games row
        intact so a single network blip doesn't force an addon restart."""
        self.getControl(self.RESULTS_LIST_ID).reset()
        self.getControl(self.EMPTY_LABEL_ID).setLabel("")
        self.getControl(self.ERROR_LABEL_ID).setLabel(message)

    def onAction(self, action):
        if action.getId() in (xbmcgui.ACTION_PREVIOUS_MENU, xbmcgui.ACTION_NAV_BACK):
            self.close()
            self.closed_event.set()
        elif action.getId() == xbmcgui.ACTION_SELECT_ITEM:
            focus = self.getFocusId()
            if focus == self.RELOGIN_BUTTON_ID:
                self._open_login_window()
            elif focus == self.GAMES_LIST_ID:
                self._on_game_selected()
            elif focus == self.SEARCH_BUTTON_ID:
                self._on_search()

    def _open_login_window(self):
        addon = xbmcaddon.Addon()
        login_window = LoginWindow(
            "script-twitch-center-login.xml",
            addon.getAddonInfo("path"),
            "Default",
            "1080i",
            closed_event=self.closed_event,
        )
        login_window.show()
        # Deliberately NOT setting closed_event: this window is handing off,
        # not ending the chain. The login window now owns the shared event.
        self.close()
