"""Discover view: browse live channels by any game, or search by channel name,
Twitch game/category name, or Kick category name (toggle via
SEARCH_MODE_TOGGLE_ID). Also browses Kick's top categories in a separate row.
In Kick search mode, that row live-filters to matching category names as the
user types (Kick has ~19k categories - far too many to browse as a flat
list), so results are reached by selecting a category rather than jumping
straight to the best match's streams. Not a Window subclass - see MainWindow.
"""
import threading
import time

import xbmc
import xbmcaddon
import xbmcgui

from lib import providers
from lib.twitch import api, auth
from lib.views import utils as view_utils
from lib.views.kick_favorites_menu import show_kick_favorite_context_menu
from lib.windows import player

_LIVE_FILTER_POLL_INTERVAL = 0.25
_LIVE_FILTER_DEBOUNCE = 0.5

RESULTS_LIST_ID = 301
EMPTY_LABEL_ID = 302
ERROR_LABEL_ID = 303
RELOGIN_BUTTON_ID = 304
GAMES_LIST_ID = 305
SEARCH_EDIT_ID = 306
SEARCH_BUTTON_ID = 307
SEARCH_MODE_TOGGLE_ID = 308
KICK_CATEGORIES_LIST_ID = 309

_MISSING_TOKEN_MESSAGE = "You're not logged in. Reopen the addon to log in."
_MISSING_KICK_TOKEN_MESSAGE = "Set your Kick app's Client Secret in Settings to search Kick categories."
_EMPTY_RESULTS_MESSAGE = "Nothing found."
_EMPTY_GAME_SEARCH_MESSAGE = "No matching game found."
_EMPTY_KICK_CATEGORY_SEARCH_MESSAGE = "No matching Kick category found."
_EMPTY_GAMES_MESSAGE = "No games to browse right now."
_NETWORK_ERROR_MESSAGE = "Couldn't reach Twitch. Check your connection and reopen the addon."
_RELOGIN_MESSAGE = "Your session expired. Log in again to continue."
_PLAYBACK_ERROR_MESSAGE = "Couldn't start playback. Try again."
_SEARCH_MODES = ("channels", "games", "kick")
_SEARCH_MODE_LABELS = {
    "channels": "Searching: Channels",
    "games": "Searching: Games",
    "kick": "Searching: Kick",
}


_thumbnail_url = view_utils.thumbnail_url
_build_stream_item = view_utils.build_stream_item
_build_channel_item = view_utils.build_channel_item
_build_kick_result_item = view_utils.build_kick_result_item


class DiscoverView:
    RESULTS_LIST_ID = RESULTS_LIST_ID
    EMPTY_LABEL_ID = EMPTY_LABEL_ID
    ERROR_LABEL_ID = ERROR_LABEL_ID
    RELOGIN_BUTTON_ID = RELOGIN_BUTTON_ID
    GAMES_LIST_ID = GAMES_LIST_ID
    SEARCH_EDIT_ID = SEARCH_EDIT_ID
    SEARCH_BUTTON_ID = SEARCH_BUTTON_ID
    SEARCH_MODE_TOGGLE_ID = SEARCH_MODE_TOGGLE_ID
    KICK_CATEGORIES_LIST_ID = KICK_CATEGORIES_LIST_ID

    def __init__(self, window, closed_event=None):
        self.window = window
        # Shared across every view hosted by MainWindow, which bootstraps it.
        self.closed_event = closed_event
        self._search_mode = "channels"
        self._kick_top_categories = []
        self._live_filter_cancel = None

    def _safe_control(self, control_id):
        """Safely retrieve a control, returning None if it doesn't exist."""
        try:
            return self.window.getControl(control_id)
        except Exception:
            return None

    def activate(self):
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

        # Re-switching to this same view (Kodi re-firing onInit, or the user
        # navigating back to Discover) calls activate() again - cancel any
        # earlier poll thread first so they don't pile up.
        self.stop()
        self._live_filter_cancel = threading.Event()
        threading.Thread(
            target=self._live_filter_poll, args=(self._live_filter_cancel,), daemon=True
        ).start()

    def stop(self):
        if self._live_filter_cancel is not None:
            self._live_filter_cancel.set()

    def _live_filter_poll(self, cancel_event):
        """Background poll driving Kick's live category filter (see module
        docstring) - Kodi's edit control has no text-changed callback, so
        polling getText() is the only way to detect typing. Ticks every
        _LIVE_FILTER_POLL_INTERVAL; a query is applied once the text has sat
        unchanged for _LIVE_FILTER_DEBOUNCE seconds, so normal typing speed
        never fires a search per keystroke."""
        last_text = None
        last_change = 0.0
        applied_text = None
        while not cancel_event.wait(_LIVE_FILTER_POLL_INTERVAL):
            try:
                if self._search_mode != "kick":
                    continue
                if self.window.getFocusId() != self.SEARCH_EDIT_ID:
                    continue
                control = self._safe_control(self.SEARCH_EDIT_ID)
                if control is None:
                    continue
                text = (control.getText() or "").strip()
            except Exception:
                continue
            now = time.monotonic()
            if text != last_text:
                last_text = text
                last_change = now
                continue
            if text == applied_text or now - last_change < _LIVE_FILTER_DEBOUNCE:
                continue
            applied_text = text
            self._apply_live_kick_filter(text)

    def _apply_live_kick_filter(self, query):
        if not query:
            self._populate_kick_categories(self._kick_top_categories)
            return
        try:
            matches = providers.search_kick_categories(xbmcaddon.Addon(), query)
        except Exception:
            return
        self._populate_kick_categories(matches)

    def _load_games(self, addon, client_id, token):
        games = api.get_top_games(token["access_token"], client_id)
        self._populate_games(games)
        kick_categories = providers.get_kick_top_categories(addon)
        self._kick_top_categories = kick_categories
        self._populate_kick_categories(kick_categories)
        # Claim focus on the now-populated games list explicitly rather than
        # leaving it wherever the previous view left it - same race-avoidance
        # as LiveStreamsView._load_and_populate.
        games_list = self._safe_control(self.GAMES_LIST_ID)
        if games_list and games_list.size():
            self.window.setFocusId(self.GAMES_LIST_ID)

    def _handle_expired_token(self, addon, client_id, token, on_success=None, on_error=None):
        """Refresh the access token, then redo whatever the user was doing.

        on_success is a callable taking (addon, client_id, refreshed_token); it
        defaults to reloading the top-games row (activate's behaviour). Callers
        that were mid-action (browse-by-game, search) pass a closure that
        retries THAT action, so an expiry doesn't silently discard the user's
        click."""
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
        relogin_btn = self._safe_control(self.RELOGIN_BUTTON_ID)
        if relogin_btn:
            relogin_btn.setVisible(False)

        control = self._safe_control(self.GAMES_LIST_ID)
        if control:
            control.reset()
            if not games:
                # Without this the row would just render blank with no
                # explanation, unlike the results list which already says so.
                empty_label = self._safe_control(self.EMPTY_LABEL_ID)
                if empty_label:
                    empty_label.setLabel(_EMPTY_GAMES_MESSAGE)
                return
            items = []
            for game in games:
                item = xbmcgui.ListItem(game["name"])
                item.setProperty("game_id", game["id"])
                items.append(item)
            control.addItems(items)

    def _populate_kick_categories(self, categories):
        control = self._safe_control(self.KICK_CATEGORIES_LIST_ID)
        if control:
            control.reset()
            items = []
            for category in categories:
                item = xbmcgui.ListItem(category["name"])
                item.setProperty("category_id", str(category["id"]))
                items.append(item)
            control.addItems(items)

    def _populate_results(self, items):
        empty_label = self._safe_control(self.EMPTY_LABEL_ID)
        if empty_label:
            empty_label.setLabel("")
        error_label = self._safe_control(self.ERROR_LABEL_ID)
        if error_label:
            error_label.setLabel("")

        control = self._safe_control(self.RESULTS_LIST_ID)
        if control:
            control.reset()
            if not items:
                if empty_label:
                    empty_label.setLabel(_EMPTY_RESULTS_MESSAGE)
                return
            control.addItems(items)

    def _load_streams_for_game(self, addon, client_id, token, game_id):
        streams = api.get_live_streams_by_game(token["access_token"], client_id, game_id)
        self._populate_results([_build_stream_item(stream_data) for stream_data in streams])

    def _load_search_results(self, addon, client_id, token, query):
        channels = api.search_channels(token["access_token"], client_id, query)
        self._populate_results([_build_channel_item(channel) for channel in channels])

    def _load_game_search_results(self, addon, client_id, token, query):
        # Twitch's category search is fuzzy/free-text, not exact - take its
        # best (first) match rather than requiring the query to be the exact
        # game name, same convention as typing "warships" to find "World of
        # Warships".
        matches = api.search_categories(token["access_token"], client_id, query, first=1)
        if not matches:
            self._populate_results([])
            empty_label = self._safe_control(self.EMPTY_LABEL_ID)
            if empty_label:
                empty_label.setLabel(_EMPTY_GAME_SEARCH_MESSAGE)
            return
        streams = api.get_live_streams_by_game(token["access_token"], client_id, matches[0]["id"])
        self._populate_results([_build_stream_item(stream_data) for stream_data in streams])

    def _load_kick_category_search_results(self, addon, query):
        # Kick's name filter is a substring match, not exact, and Kick lists
        # multiple distinct category IDs under the same name (e.g. two
        # separate "EVE Online" categories) - taking only the first match's
        # streams can show an empty/near-empty duplicate while a livelier
        # one sits under a different ID. Pull streams from every match and
        # merge them so none of the duplicates get silently dropped.
        matches = providers.search_kick_categories(addon, query)
        if not matches:
            self._populate_results([])
            empty_label = self._safe_control(self.EMPTY_LABEL_ID)
            if empty_label:
                empty_label.setLabel(_EMPTY_KICK_CATEGORY_SEARCH_MESSAGE)
            return
        stream_lists = [providers.get_kick_category_streams(addon, match["id"]) for match in matches]
        streams = providers.merge_by_viewer_count(*stream_lists)
        self._populate_results([_build_kick_result_item(r) for r in streams])

    def _on_game_selected(self):
        control = self._safe_control(self.GAMES_LIST_ID)
        if not control:
            return
        selected = control.getSelectedItem()
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

    def _on_kick_category_selected(self):
        control = self._safe_control(self.KICK_CATEGORIES_LIST_ID)
        if not control:
            return
        selected = control.getSelectedItem()
        if selected is None:
            return
        addon = xbmcaddon.Addon()
        category_id = selected.getProperty("category_id")
        results = providers.get_kick_category_streams(addon, category_id)
        self._populate_results([_build_kick_result_item(r) for r in results])

    def _on_channel_selected(self):
        control = self._safe_control(self.RESULTS_LIST_ID)
        if not control:
            return
        selected = control.getSelectedItem()
        if selected is None or selected.getProperty("is_live") != "true":
            return
        platform = selected.getProperty("platform") or "twitch"
        broadcaster_login = selected.getProperty("broadcaster_login")
        if platform == "kick":
            self._play_channel("kick", broadcaster_login)
            return
        addon = xbmcaddon.Addon()
        token = auth.load_token(addon)
        if token is None:
            self._show_results_error(_MISSING_TOKEN_MESSAGE)
            return
        client_id = addon.getSetting("client_id")
        self._play_channel("twitch", broadcaster_login, token=token, client_id=client_id)

    def _play_channel(self, platform, broadcaster_login, token=None, client_id=None):
        addon = xbmcaddon.Addon()
        try:
            url = providers.resolve_stream_url(addon, platform, broadcaster_login)
            play_kwargs = {"platform": platform}
            if platform == "twitch":
                play_kwargs.update(
                    access_token=token["access_token"], client_id=client_id, user_id=token["user_id"]
                )
            played = player.play_stream(url, broadcaster_login, **play_kwargs)
        except providers.StreamUnavailableError:
            self._show_results_error(_PLAYBACK_ERROR_MESSAGE)
            return
        except Exception as exc:
            xbmc.log(
                "script.twitch.center: Discover channel selection failed: " + repr(exc),
                xbmc.LOGERROR,
            )
            self._show_results_error(_PLAYBACK_ERROR_MESSAGE)
            return
        if played:
            error_label = self._safe_control(self.ERROR_LABEL_ID)
            if error_label:
                error_label.setLabel("")
        else:
            self._show_results_error(_PLAYBACK_ERROR_MESSAGE)

    def _on_search(self):
        control = self._safe_control(self.SEARCH_EDIT_ID)
        if not control:
            return
        query = control.getText()
        if not query:
            return
        addon = xbmcaddon.Addon()

        if self._search_mode == "kick":
            if not addon.getSetting("kick_client_secret"):
                self._show_results_error(_MISSING_KICK_TOKEN_MESSAGE)
                return
            try:
                self._load_kick_category_search_results(addon, query)
            except Exception as exc:
                xbmc.log(
                    "script.twitch.center: Discover Kick category search failed: " + repr(exc),
                    xbmc.LOGERROR,
                )
                self._show_results_error(_NETWORK_ERROR_MESSAGE)
            return

        client_id = addon.getSetting("client_id")
        token = auth.load_token(addon)
        if token is None:
            self._show_results_error(_MISSING_TOKEN_MESSAGE)
            return
        load = (
            self._load_game_search_results
            if self._search_mode == "games"
            else self._load_search_results
        )
        try:
            load(addon, client_id, token, query)
        except api.TokenExpiredError:
            self._handle_expired_token(
                addon,
                client_id,
                token,
                on_success=lambda a, c, t: load(a, c, t, query),
                on_error=self._show_results_error,
            )
        except Exception as exc:
            xbmc.log("script.twitch.center: Discover search failed: " + repr(exc), xbmc.LOGERROR)
            self._show_results_error(_NETWORK_ERROR_MESSAGE)

    def _toggle_search_mode(self):
        # Deliberately doesn't touch SEARCH_EDIT_ID's label: Kodi's edit
        # control label is a heading separate from the typed value, but
        # changing it here isn't worth the risk of ever clobbering
        # in-progress user input for a cosmetic placeholder update - the
        # toggle button's own label is signal enough for which mode is active.
        current_index = _SEARCH_MODES.index(self._search_mode)
        self._search_mode = _SEARCH_MODES[(current_index + 1) % len(_SEARCH_MODES)]
        toggle_btn = self._safe_control(self.SEARCH_MODE_TOGGLE_ID)
        if toggle_btn:
            toggle_btn.setLabel(
                _SEARCH_MODE_LABELS[self._search_mode]
            )

    def _show_error(self, message):
        """Fatal failure (activate / expired session): the whole screen is
        unusable, so wipe everything and offer the re-login button."""
        games_list = self._safe_control(self.GAMES_LIST_ID)
        if games_list:
            games_list.reset()
        kick_categories_list = self._safe_control(self.KICK_CATEGORIES_LIST_ID)
        if kick_categories_list:
            kick_categories_list.reset()
        results_list = self._safe_control(self.RESULTS_LIST_ID)
        if results_list:
            results_list.reset()
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

    def _show_results_error(self, message):
        """Transient failure of one browse/search: keep the top-games row
        intact so a single network blip doesn't force an addon restart."""
        results_list = self._safe_control(self.RESULTS_LIST_ID)
        if results_list:
            results_list.reset()
        empty_label = self._safe_control(self.EMPTY_LABEL_ID)
        if empty_label:
            empty_label.setLabel("")
        error_label = self._safe_control(self.ERROR_LABEL_ID)
        if error_label:
            error_label.setLabel(message)

    def handle_action(self, action):
        if action.getId() == xbmcgui.ACTION_SELECT_ITEM:
            focus = self.window.getFocusId()
            if focus == self.RELOGIN_BUTTON_ID:
                self.window._switch_view("login")
            elif focus == self.GAMES_LIST_ID:
                self._on_game_selected()
            elif focus == self.KICK_CATEGORIES_LIST_ID:
                self._on_kick_category_selected()
            elif focus == self.SEARCH_BUTTON_ID:
                self._on_search()
            elif focus == self.SEARCH_MODE_TOGGLE_ID:
                self._toggle_search_mode()
            elif focus == self.RESULTS_LIST_ID:
                self._on_channel_selected()
        elif action.getId() == xbmcgui.ACTION_CONTEXT_MENU:
            if self.window.getFocusId() == self.RESULTS_LIST_ID:
                self._on_context_menu()

    def _on_context_menu(self):
        control = self._safe_control(self.RESULTS_LIST_ID)
        if not control:
            return
        selected = control.getSelectedItem()
        if selected is None or selected.getProperty("platform") != "kick":
            return
        addon = xbmcaddon.Addon()
        show_kick_favorite_context_menu(addon, selected.getProperty("broadcaster_login"))

    def handle_click(self, control_id):
        pass
