"""Category streams view: live Twitch streams for one category picked in
TopCategoriesView (context {"game_id", "game_name"}). Back returns to the
grid. Not a Window subclass - see MainWindow."""
import xbmc
import xbmcaddon
import xbmcgui

from lib.twitch import api, auth
from lib.views import playback
from lib.views import utils as view_utils

STREAM_LIST_ID = 1101
EMPTY_LABEL_ID = 1102
ERROR_LABEL_ID = 1103
RELOGIN_BUTTON_ID = 1104
TITLE_LABEL_ID = 1105

STREAM_COUNT = 100

_NO_CONTEXT_MESSAGE = "No category selected. Go back and pick a category."
_MISSING_TOKEN_MESSAGE = "You're not logged in. Reopen the addon to log in."
_EMPTY_MESSAGE = "Nobody's live in this category right now."
_NETWORK_ERROR_MESSAGE = "Couldn't reach Twitch. Check your connection and reopen the addon."
_RELOGIN_MESSAGE = "Your session expired. Log in again to continue."


class CategoryStreamsView:
    STREAM_LIST_ID = STREAM_LIST_ID
    EMPTY_LABEL_ID = EMPTY_LABEL_ID
    ERROR_LABEL_ID = ERROR_LABEL_ID
    RELOGIN_BUTTON_ID = RELOGIN_BUTTON_ID
    TITLE_LABEL_ID = TITLE_LABEL_ID
    DEFAULT_FOCUS_ID = STREAM_LIST_ID
    BACK_TARGET = "top_categories"

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
        # MainWindow shows this group before activate()'s blocking fetch -
        # clear the previous category's streams so they can't be seen or
        # played under the new category's title meanwhile.
        self._clear()
        if not self.context or not self.context.get("game_id"):
            # Not an auth/network failure - leave the relogin button hidden,
            # same as VodClipsView's guard.
            self._show_list_error(_NO_CONTEXT_MESSAGE)
            return

        title_label = self._safe_control(self.TITLE_LABEL_ID)
        if title_label:
            title_label.setLabel(self.context.get("game_name", ""))

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
            self._load_and_populate(addon, client_id, token)
        except api.TokenExpiredError:
            self._handle_expired_token(addon, client_id, token)
        except Exception as exc:
            xbmc.log(
                "script.twitch.center: category streams failed to load: " + repr(exc),
                xbmc.LOGERROR,
            )
            self._show_error(_NETWORK_ERROR_MESSAGE)

    def _load_and_populate(self, addon, client_id, token):
        streams = api.get_live_streams_by_game(
            token["access_token"], client_id, self.context["game_id"], first=STREAM_COUNT
        )
        self._populate(streams)

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
                "script.twitch.center: category streams failed after token refresh: "
                + repr(exc),
                xbmc.LOGERROR,
            )
            self._show_error(_NETWORK_ERROR_MESSAGE)

    def _populate(self, streams):
        empty_label = self._safe_control(self.EMPTY_LABEL_ID)
        if empty_label:
            empty_label.setLabel("")
        error_label = self._safe_control(self.ERROR_LABEL_ID)
        if error_label:
            error_label.setLabel("")
        relogin_btn = self._safe_control(self.RELOGIN_BUTTON_ID)
        if relogin_btn:
            relogin_btn.setVisible(False)
        control = self._safe_control(self.STREAM_LIST_ID)
        if not control:
            return
        control.reset()
        if not streams:
            if empty_label:
                empty_label.setLabel(_EMPTY_MESSAGE)
            return
        control.addItems([view_utils.build_stream_item(stream) for stream in streams])
        self.window.setFocusId(self.STREAM_LIST_ID)

    def _clear(self):
        control = self._safe_control(self.STREAM_LIST_ID)
        if control:
            control.reset()
        for label_id in (self.EMPTY_LABEL_ID, self.ERROR_LABEL_ID):
            label = self._safe_control(label_id)
            if label:
                label.setLabel("")

    def _show_list_error(self, message):
        """Transient failure (e.g. playback): show the message, keep the list."""
        error_label = self._safe_control(self.ERROR_LABEL_ID)
        if error_label:
            error_label.setLabel(message)

    def _show_error(self, message):
        """Auth/network failure: clear the list and offer re-login."""
        control = self._safe_control(self.STREAM_LIST_ID)
        if control:
            control.reset()
        empty_label = self._safe_control(self.EMPTY_LABEL_ID)
        if empty_label:
            empty_label.setLabel("")
        self._show_list_error(message)
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
        elif focus == self.STREAM_LIST_ID:
            self._on_stream_selected()

    def handle_click(self, control_id):
        pass

    def _on_stream_selected(self):
        control = self._safe_control(self.STREAM_LIST_ID)
        if not control:
            return
        selected = control.getSelectedItem()
        if selected is None:
            return
        addon = xbmcaddon.Addon()
        token = auth.load_token(addon)
        if token is None:
            self._show_list_error(_MISSING_TOKEN_MESSAGE)
            return
        played = playback.play_channel(
            "twitch",
            selected.getProperty("broadcaster_login"),
            show_error=self._show_list_error,
            token=token,
            client_id=addon.getSetting("client_id"),
        )
        if played:
            self._show_list_error("")
