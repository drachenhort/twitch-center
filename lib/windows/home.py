"""Home screen: the user's followed channels, live ones surfaced first."""
import threading

import xbmc
import xbmcaddon
import xbmcgui

from lib.twitch import api, auth
from lib.windows.login import LoginWindow

CHANNEL_LIST_ID = 101
EMPTY_LABEL_ID = 102
ERROR_LABEL_ID = 103
RELOGIN_BUTTON_ID = 104

_MISSING_TOKEN_MESSAGE = "You're not logged in. Reopen the addon to log in."
_EMPTY_FOLLOWED_MESSAGE = "You're not following anyone yet."
_NETWORK_ERROR_MESSAGE = "Couldn't reach Twitch. Check your connection and reopen the addon."
_RELOGIN_MESSAGE = "Your session expired. Log in again to continue."


def _thumbnail_url(raw_url, width=320, height=180):
    return raw_url.replace("{width}", str(width)).replace("{height}", str(height))


def _merge_channels(followed, live_list):
    """Split followed channels into (live, offline). live is a list of
    (channel, stream) tuples sorted by viewer_count descending; offline is a
    list of channel dicts sorted alphabetically by broadcaster_name."""
    live_by_id = {stream["user_id"]: stream for stream in live_list}
    live = []
    offline = []
    for channel in followed:
        stream = live_by_id.get(channel["broadcaster_id"])
        if stream:
            live.append((channel, stream))
        else:
            offline.append(channel)
    live.sort(key=lambda pair: pair[1]["viewer_count"], reverse=True)
    offline.sort(key=lambda c: c["broadcaster_name"].lower())
    return live, offline


def _build_list_item(channel, stream=None):
    item = xbmcgui.ListItem(channel["broadcaster_name"])
    if stream:
        item.setLabel2(stream["game_name"] + " - " + str(stream["viewer_count"]) + " viewers")
        item.setArt({"thumb": _thumbnail_url(stream["thumbnail_url"])})
    else:
        item.setLabel2("Offline")
    item.setProperty("broadcaster_id", channel["broadcaster_id"])
    return item


class HomeWindow(xbmcgui.WindowXML):
    CHANNEL_LIST_ID = CHANNEL_LIST_ID
    EMPTY_LABEL_ID = EMPTY_LABEL_ID
    ERROR_LABEL_ID = ERROR_LABEL_ID
    RELOGIN_BUTTON_ID = RELOGIN_BUTTON_ID

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.closed_event = threading.Event()

    def onInit(self):
        addon = xbmcaddon.Addon()
        client_id = addon.getSetting("client_id")
        token = auth.load_token(addon)
        if token is None:
            self._show_error(_MISSING_TOKEN_MESSAGE)
            return
        if not token.get("user_id"):
            # Tokens saved by the earlier device-code-login feature (before
            # user_id/login/display_name caching was added) don't have this
            # key. Treat that the same as an expired session rather than
            # letting the KeyError below get swallowed as a network error.
            auth.clear_token(addon)
            self._show_error(_RELOGIN_MESSAGE)
            return

        try:
            self._load_and_populate(addon, client_id, token)
        except api.TokenExpiredError:
            self._handle_expired_token(addon, client_id, token)
        except Exception as exc:
            xbmc.log(
                "script.twitch.center: Home screen failed to load: " + repr(exc), xbmc.LOGERROR
            )
            self._show_error(_NETWORK_ERROR_MESSAGE)

    def _load_and_populate(self, addon, client_id, token):
        followed = api.get_followed_channels(token["access_token"], client_id, token["user_id"])
        broadcaster_ids = [c["broadcaster_id"] for c in followed]
        live_list = api.get_live_status(token["access_token"], client_id, broadcaster_ids)
        self._populate(followed, live_list)

    def _handle_expired_token(self, addon, client_id, token):
        new_token = auth.refresh_access_token(client_id, token["refresh_token"])
        if new_token is None:
            auth.clear_token(addon)
            self._show_error(_RELOGIN_MESSAGE)
            return

        new_token["user_id"] = token.get("user_id")
        new_token["login"] = token.get("login")
        new_token["display_name"] = token.get("display_name")

        # Twitch's device-code refresh tokens are single-use for public
        # clients: the moment refresh_access_token succeeded above, the OLD
        # refresh_token was invalidated. Persist the new token now, before
        # the retry below - if the retry hits a transient (non-401) error,
        # we still want the new refresh_token on disk rather than the
        # now-dead old one, or the next launch's refresh would fail outright.
        auth.save_token(new_token, addon)

        try:
            self._load_and_populate(addon, client_id, new_token)
        except api.TokenExpiredError:
            auth.clear_token(addon)
            self._show_error(_RELOGIN_MESSAGE)
            return
        except Exception as exc:
            xbmc.log(
                "script.twitch.center: Home screen failed after token refresh: " + repr(exc),
                xbmc.LOGERROR,
            )
            self._show_error(_NETWORK_ERROR_MESSAGE)
            return

    def _populate(self, followed, live_list):
        self.getControl(self.RELOGIN_BUTTON_ID).setVisible(False)
        control = self.getControl(self.CHANNEL_LIST_ID)
        control.reset()
        if not followed:
            self.getControl(self.EMPTY_LABEL_ID).setLabel(_EMPTY_FOLLOWED_MESSAGE)
            return
        live, offline = _merge_channels(followed, live_list)
        items = [_build_list_item(channel, stream) for channel, stream in live]
        items += [_build_list_item(channel) for channel in offline]
        control.addItems(items)

    def _show_error(self, message):
        self.getControl(self.ERROR_LABEL_ID).setLabel(message)
        self.getControl(self.RELOGIN_BUTTON_ID).setVisible(True)

    def onAction(self, action):
        if action.getId() in (xbmcgui.ACTION_PREVIOUS_MENU, xbmcgui.ACTION_NAV_BACK):
            self.close()
            self.closed_event.set()
        elif (
            action.getId() == xbmcgui.ACTION_SELECT_ITEM
            and self.getFocusId() == self.RELOGIN_BUTTON_ID
        ):
            self._open_login_window()

    def _open_login_window(self):
        addon = xbmcaddon.Addon()
        login_window = LoginWindow(
            "script-twitch-center-login.xml", addon.getAddonInfo("path"), "Default", "1080i"
        )
        login_window.show()
        self.close()
        self.closed_event.set()
