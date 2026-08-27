"""VODs & Clips channel picker: every followed Twitch channel, live or not - VODs and
Clips exist independent of current live status. Not a Window subclass - see MainWindow."""
import xbmc
import xbmcaddon
import xbmcgui

from lib.twitch import api, auth
from lib.views import utils as view_utils

CHANNEL_LIST_ID = 701
EMPTY_LABEL_ID = 702
ERROR_LABEL_ID = 703
RELOGIN_BUTTON_ID = 704
TITLE_LABEL_ID = 705

_MISSING_TOKEN_MESSAGE = "You're not logged in. Reopen the addon to log in."
_EMPTY_FOLLOWED_MESSAGE = "You're not following anyone yet."
_NETWORK_ERROR_MESSAGE = "Couldn't reach Twitch. Check your connection and reopen the addon."
_RELOGIN_MESSAGE = "Your session expired. Log in again to continue."


class VodClipsChannelsView:
    CHANNEL_LIST_ID = CHANNEL_LIST_ID
    EMPTY_LABEL_ID = EMPTY_LABEL_ID
    ERROR_LABEL_ID = ERROR_LABEL_ID
    RELOGIN_BUTTON_ID = RELOGIN_BUTTON_ID
    TITLE_LABEL_ID = TITLE_LABEL_ID

    def __init__(self, window, closed_event=None):
        self.window = window
        self.closed_event = closed_event
        self.context = None

    def _safe_control(self, control_id):
        try:
            return self.window.getControl(control_id)
        except Exception:
            return None

    def activate(self):
        addon = xbmcaddon.Addon()
        title_label = self._safe_control(self.TITLE_LABEL_ID)
        if title_label:
            title_label.setLabel("VODs & Clips")
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
            self._load_and_populate(addon, client_id, token)
        except api.TokenExpiredError:
            self._handle_expired_token(addon, client_id, token)
        except Exception as exc:
            xbmc.log(
                "script.twitch.center: VODs & Clips channel picker failed to load: " + repr(exc),
                xbmc.LOGERROR,
            )
            self._show_error(_NETWORK_ERROR_MESSAGE)

    def _load_and_populate(self, addon, client_id, token):
        followed = api.get_followed_channels(token["access_token"], client_id, token["user_id"])
        self._populate(followed)
        channel_list = self._safe_control(self.CHANNEL_LIST_ID)
        if channel_list and channel_list.size():
            self.window.setFocusId(self.CHANNEL_LIST_ID)
        else:
            self._show_relogin_button()

    def _handle_expired_token(self, addon, client_id, token):
        new_token = auth.refresh_access_token(
            client_id,
            token["refresh_token"],
            on_error=lambda reason: xbmc.log(
                "script.twitch.center: token refresh failed: " + reason, xbmc.LOGERROR
            ),
        )
        if new_token is None:
            auth.clear_token(addon)
            self._show_error(_RELOGIN_MESSAGE)
            return
        new_token["user_id"] = token.get("user_id")
        new_token["login"] = token.get("login")
        new_token["display_name"] = token.get("display_name")
        auth.save_token(new_token, addon)
        try:
            self._load_and_populate(addon, client_id, new_token)
        except api.TokenExpiredError:
            auth.clear_token(addon)
            self._show_error(_RELOGIN_MESSAGE)
        except Exception as exc:
            xbmc.log(
                "script.twitch.center: VODs & Clips channel picker failed after token "
                "refresh: " + repr(exc),
                xbmc.LOGERROR,
            )
            self._show_error(_NETWORK_ERROR_MESSAGE)

    def _populate(self, followed):
        empty_label = self._safe_control(self.EMPTY_LABEL_ID)
        if empty_label:
            empty_label.setLabel("")
        error_label = self._safe_control(self.ERROR_LABEL_ID)
        if error_label:
            error_label.setLabel("")
        relogin_btn = self._safe_control(self.RELOGIN_BUTTON_ID)
        if relogin_btn:
            relogin_btn.setVisible(False)
        control = self._safe_control(self.CHANNEL_LIST_ID)
        if control:
            control.reset()
            if not followed:
                if empty_label:
                    empty_label.setLabel(_EMPTY_FOLLOWED_MESSAGE)
                return
            items = [view_utils.build_followed_channel_item(c) for c in followed]
            control.addItems(items)

    def _show_error(self, message):
        channel_list = self._safe_control(self.CHANNEL_LIST_ID)
        if channel_list:
            channel_list.reset()
        empty_label = self._safe_control(self.EMPTY_LABEL_ID)
        if empty_label:
            empty_label.setLabel("")
        error_label = self._safe_control(self.ERROR_LABEL_ID)
        if error_label:
            error_label.setLabel(message)
        self._show_relogin_button()

    def _show_relogin_button(self):
        relogin_btn = self._safe_control(self.RELOGIN_BUTTON_ID)
        if relogin_btn:
            relogin_btn.setVisible(True)
            self.window.setFocusId(self.RELOGIN_BUTTON_ID)

    def handle_action(self, action):
        if action.getId() != xbmcgui.ACTION_SELECT_ITEM:
            return
        focus = self.window.getFocusId()
        if focus == self.RELOGIN_BUTTON_ID:
            self.window._switch_view("login")
        elif focus == self.CHANNEL_LIST_ID:
            self._on_channel_selected()

    def handle_click(self, control_id):
        pass

    def _on_channel_selected(self):
        control = self._safe_control(self.CHANNEL_LIST_ID)
        if not control:
            return
        selected = control.getSelectedItem()
        if selected is None:
            return
        context = {
            "broadcaster_id": selected.getProperty("broadcaster_id"),
            "broadcaster_login": selected.getProperty("broadcaster_login"),
            "broadcaster_name": selected.getProperty("broadcaster_name"),
        }
        self.window._switch_view("vod_clips", context=context)
