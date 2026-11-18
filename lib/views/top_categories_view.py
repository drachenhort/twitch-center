"""Top Categories view: Twitch's top 100 categories (Helix /games/top) as a
box-art grid, opened from Discover's "Browse Twitch Categories" button.
Selecting a tile opens CategoryStreamsView for that category. Back from there
lands here again on the same tile, without refetching. Not a Window subclass -
see MainWindow."""
import xbmc
import xbmcaddon
import xbmcgui

from lib.twitch import api, auth
from lib.views import utils as view_utils

CATEGORY_LIST_ID = 1001
EMPTY_LABEL_ID = 1002
ERROR_LABEL_ID = 1003
RELOGIN_BUTTON_ID = 1004
TITLE_LABEL_ID = 1005

TOP_CATEGORY_COUNT = 100
BOX_ART_WIDTH = 285
BOX_ART_HEIGHT = 380

_MISSING_TOKEN_MESSAGE = "You're not logged in. Reopen the addon to log in."
_EMPTY_MESSAGE = "No categories right now."
_NETWORK_ERROR_MESSAGE = "Couldn't reach Twitch. Check your connection and reopen the addon."
_RELOGIN_MESSAGE = "Your session expired. Log in again to continue."


class TopCategoriesView:
    CATEGORY_LIST_ID = CATEGORY_LIST_ID
    EMPTY_LABEL_ID = EMPTY_LABEL_ID
    ERROR_LABEL_ID = ERROR_LABEL_ID
    RELOGIN_BUTTON_ID = RELOGIN_BUTTON_ID
    TITLE_LABEL_ID = TITLE_LABEL_ID
    DEFAULT_FOCUS_ID = CATEGORY_LIST_ID
    BACK_TARGET = "discover"

    def __init__(self, window, closed_event=None):
        self.window = window
        self.closed_event = closed_event
        self.context = None
        self._categories = []
        self._selected = 0

    def _safe_control(self, control_id):
        try:
            return self.window.getControl(control_id)
        except Exception:
            return None

    def activate(self):
        title_label = self._safe_control(self.TITLE_LABEL_ID)
        if title_label:
            title_label.setLabel("Top Categories")
        # Discover passes {"refresh": True}; Back from the streams page passes
        # no context, so the cached list and the user's place in it are kept.
        # An empty cache (first load failed or returned nothing) always refetches.
        if self._categories and not (self.context or {}).get("refresh"):
            self._populate(self._categories)
            return

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
                "script.twitch.center: Top Categories failed to load: " + repr(exc),
                xbmc.LOGERROR,
            )
            self._show_error(_NETWORK_ERROR_MESSAGE)

    def _load_and_populate(self, addon, client_id, token):
        categories = api.get_top_games(token["access_token"], client_id, first=TOP_CATEGORY_COUNT)
        self._categories = categories
        self._selected = 0
        self._populate(categories)

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
                "script.twitch.center: Top Categories failed after token refresh: " + repr(exc),
                xbmc.LOGERROR,
            )
            self._show_error(_NETWORK_ERROR_MESSAGE)

    def _populate(self, categories):
        empty_label = self._safe_control(self.EMPTY_LABEL_ID)
        if empty_label:
            empty_label.setLabel("")
        error_label = self._safe_control(self.ERROR_LABEL_ID)
        if error_label:
            error_label.setLabel("")
        relogin_btn = self._safe_control(self.RELOGIN_BUTTON_ID)
        if relogin_btn:
            relogin_btn.setVisible(False)
        control = self._safe_control(self.CATEGORY_LIST_ID)
        if not control:
            return
        control.reset()
        if not categories:
            if empty_label:
                empty_label.setLabel(_EMPTY_MESSAGE)
            return
        control.addItems([self._build_item(category) for category in categories])
        control.selectItem(self._selected)
        self.window.setFocusId(self.CATEGORY_LIST_ID)

    @staticmethod
    def _build_item(category):
        item = xbmcgui.ListItem(category["name"])
        item.setProperty("game_id", category["id"])
        if category.get("box_art_url"):
            item.setArt(
                {
                    "thumb": view_utils.thumbnail_url(
                        category["box_art_url"], BOX_ART_WIDTH, BOX_ART_HEIGHT
                    )
                }
            )
        return item

    def _show_error(self, message):
        control = self._safe_control(self.CATEGORY_LIST_ID)
        if control:
            control.reset()
        empty_label = self._safe_control(self.EMPTY_LABEL_ID)
        if empty_label:
            empty_label.setLabel("")
        error_label = self._safe_control(self.ERROR_LABEL_ID)
        if error_label:
            error_label.setLabel(message)
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
        elif focus == self.CATEGORY_LIST_ID:
            self._on_category_selected()

    def handle_click(self, control_id):
        pass

    def _on_category_selected(self):
        control = self._safe_control(self.CATEGORY_LIST_ID)
        if not control:
            return
        selected = control.getSelectedItem()
        if selected is None:
            return
        self._selected = control.getSelectedPosition()
        self.window._switch_view(
            "category_streams",
            context={"game_id": selected.getProperty("game_id"), "game_name": selected.getLabel()},
        )
