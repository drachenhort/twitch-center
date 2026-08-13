"""Live Streams view: the user's followed channels, live ones surfaced
first. Not a Window subclass - see MainWindow."""
import threading

import xbmc
import xbmcaddon
import xbmcgui

from lib.settings import Settings
from lib.twitch import api, auth, gql, stream
from lib.windows import player

CHANNEL_LIST_ID = 201
EMPTY_LABEL_ID = 202
ERROR_LABEL_ID = 203
GAMES_LIST_ID = 205
TITLE_LABEL_ID = 207

_MISSING_TOKEN_MESSAGE = "You're not logged in. Reopen the addon to log in."
_EMPTY_FOLLOWED_MESSAGE = "You're not following anyone yet."
_NO_LIVE_MESSAGE = "None of your followed channels are live right now."
_NETWORK_ERROR_MESSAGE = "Couldn't reach Twitch. Check your connection and reopen the addon."
_RELOGIN_MESSAGE = "Your session expired. Log in again to continue."
_ALL_GAMES_LABEL = "All"
_NO_MATCHES_MESSAGE = "None of your live followed channels are playing this game right now."
_PLAYBACK_ERROR_MESSAGE = "Couldn't start playback. Try again."


def _thumbnail_url(raw_url, width=320, height=180):
    return raw_url.replace("{width}", str(width)).replace("{height}", str(height))


def _merge_channels(followed, live_list):
    """Split followed channels into (live, offline). live is a list of
    (channel, stream_data) tuples sorted by viewer_count descending; offline
    is a list of channel dicts sorted alphabetically by broadcaster_name."""
    live_by_id = {stream_data["user_id"]: stream_data for stream_data in live_list}
    live = []
    offline = []
    for channel in followed:
        stream_data = live_by_id.get(channel["broadcaster_id"])
        if stream_data:
            live.append((channel, stream_data))
        else:
            offline.append(channel)
    live.sort(key=lambda pair: pair[1]["viewer_count"], reverse=True)
    offline.sort(key=lambda c: c["broadcaster_name"].lower())
    return live, offline


def _build_list_item(channel, stream_data=None):
    item = xbmcgui.ListItem(channel["broadcaster_name"])
    if stream_data:
        item.setLabel2(
            stream_data["game_name"] + " - " + str(stream_data["viewer_count"]) + " viewers"
        )
        item.setArt({"thumb": _thumbnail_url(stream_data["thumbnail_url"])})
        item.setProperty("is_live", "true")
    else:
        item.setLabel2("Offline")
        item.setProperty("is_live", "false")
    item.setProperty("broadcaster_id", channel["broadcaster_id"])
    item.setProperty("broadcaster_login", channel["broadcaster_login"])
    return item


class LiveStreamsView:
    CHANNEL_LIST_ID = CHANNEL_LIST_ID
    EMPTY_LABEL_ID = EMPTY_LABEL_ID
    ERROR_LABEL_ID = ERROR_LABEL_ID
    GAMES_LIST_ID = GAMES_LIST_ID
    TITLE_LABEL_ID = TITLE_LABEL_ID

    def __init__(self, window, closed_event=None, settings=None):
        self.window = window
        # Shared across the whole window-navigation chain - see LoginWindow.
        self.closed_event = closed_event or threading.Event()
        if not hasattr(self.closed_event, "quit_requested"):
            self.closed_event.quit_requested = False
        self._settings = settings or Settings()
        self._followed = []
        self._live = []
        self._games = []
        self._selected_game = None

    def _safe_control(self, control_id):
        """Safely retrieve a control, returning None if it doesn't exist."""
        try:
            return self.window.getControl(control_id)
        except Exception:
            return None

    def activate(self):
        addon = xbmcaddon.Addon()
        version = addon.getAddonInfo("version")
        title_label = self._safe_control(self.TITLE_LABEL_ID)
        if title_label:
            title_label.setLabel("Twitch Center v" + version)
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
        games = gql.get_followed_live_games(addon.getSetting("website_token"))
        self._followed = followed
        self._live = live_list
        self._games = games
        self._selected_game = None
        self._populate_games(games)
        self._populate(followed, live_list)
        # The skin's <defaultcontrol> targets the (still empty at skin-parse
        # time) channel list, so Kodi's initial focus lands wherever its
        # fallback search finds first - often a button. Explicitly claim
        # focus now that the list is actually populated (or switch to Menu
        # if it stayed empty), so a leftover keypress can't trigger an
        # unintended action while focus is still up for grabs.
        channel_list = self._safe_control(self.CHANNEL_LIST_ID)
        if channel_list and channel_list.size():
            self.window.setFocusId(self.CHANNEL_LIST_ID)
        else:
            self.window._switch_view("menu")

    def _handle_expired_token(self, addon, client_id, token, on_success=None, on_error=None):
        """Refresh the access token, then redo whatever the user was doing.

        on_success is a callable taking (addon, client_id, refreshed_token); it
        defaults to reloading the whole Live Streams view (activate's
        behaviour). Callers that were mid-action (e.g. playback) pass a
        closure that retries THAT action, so an expiry doesn't silently
        discard the user's click."""
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

        # Twitch's device-code refresh tokens are single-use for public
        # clients: the moment refresh_access_token succeeded above, the OLD
        # refresh_token was invalidated. Persist the new token now, before
        # the retry below - if the retry hits a transient (non-401) error,
        # we still want the new refresh_token on disk rather than the
        # now-dead old one, or the next launch's refresh would fail outright.
        auth.save_token(new_token, addon)

        if on_success is None:
            on_success = self._load_and_populate
        if on_error is None:
            on_error = self._show_error

        try:
            on_success(addon, client_id, new_token)
        except api.TokenExpiredError:
            auth.clear_token(addon)
            self._show_error(_RELOGIN_MESSAGE)
        except Exception as exc:
            xbmc.log(
                "script.twitch.center: Home screen failed after token refresh: " + repr(exc),
                xbmc.LOGERROR,
            )
            on_error(_NETWORK_ERROR_MESSAGE)

    def _populate_games(self, games):
        control = self._safe_control(self.GAMES_LIST_ID)
        if control:
            control.reset()
            all_item = xbmcgui.ListItem(_ALL_GAMES_LABEL)
            items = [all_item]
            for game in games:
                item = xbmcgui.ListItem(game["displayName"])
                # Use displayName, not the GQL "name" slug: the filter below
                # compares against Helix's live-status game_name field, which is
                # the human-readable form (e.g. "Just Chatting"), not a slug.
                item.setProperty("game_name", game["displayName"])
                items.append(item)
            control.addItems(items)

    def _populate(self, followed, live_list, game_filter=None):
        empty_label = self._safe_control(self.EMPTY_LABEL_ID)
        if empty_label:
            empty_label.setLabel("")
        error_label = self._safe_control(self.ERROR_LABEL_ID)
        if error_label:
            error_label.setLabel("")
        control = self._safe_control(self.CHANNEL_LIST_ID)
        if control:
            control.reset()
            if not followed:
                if empty_label:
                    empty_label.setLabel(_EMPTY_FOLLOWED_MESSAGE)
                return
            live, offline = _merge_channels(followed, live_list)
            if game_filter is not None:
                live = [
                    (channel, stream_data)
                    for channel, stream_data in live
                    if stream_data["game_name"] == game_filter
                ]
                offline = []
            elif not self._settings.show_offline_channels:
                offline = []
            items = [_build_list_item(channel, stream_data) for channel, stream_data in live]
            items += [_build_list_item(channel) for channel in offline]
            if not items:
                if empty_label:
                    empty_label.setLabel(_NO_MATCHES_MESSAGE if game_filter else _NO_LIVE_MESSAGE)
                return
            control.addItems(items)

    def _show_error(self, message):
        games_list = self._safe_control(self.GAMES_LIST_ID)
        if games_list:
            games_list.reset()
        channel_list = self._safe_control(self.CHANNEL_LIST_ID)
        if channel_list:
            channel_list.reset()
        empty_label = self._safe_control(self.EMPTY_LABEL_ID)
        if empty_label:
            empty_label.setLabel("")
        error_label = self._safe_control(self.ERROR_LABEL_ID)
        if error_label:
            error_label.setLabel(message)
        # See _load_and_populate: claim a definite destination explicitly
        # rather than leaving focus to Kodi's fallback search over an empty
        # defaultcontrol list - there's no relogin button to focus anymore,
        # so route to Menu instead.
        self.window._switch_view("menu")

    def _show_results_error(self, message):
        """Transient failure (e.g. one playback attempt): keep the channel
        list and games row intact so a single failure doesn't force an
        addon restart - mirrors DiscoverWindow's _show_results_error."""
        error_label = self._safe_control(self.ERROR_LABEL_ID)
        if error_label:
            error_label.setLabel(message)

    def handle_action(self, action):
        if action.getId() == xbmcgui.ACTION_SELECT_ITEM:
            if self.window.getFocusId() == self.GAMES_LIST_ID:
                self._on_game_selected()
            elif self.window.getFocusId() == self.CHANNEL_LIST_ID:
                self._on_channel_selected()

    def handle_click(self, control_id):
        pass

    def _on_game_selected(self):
        control = self._safe_control(self.GAMES_LIST_ID)
        if not control:
            return
        selected = control.getSelectedItem()
        if selected is None:
            return
        game_name = selected.getProperty("game_name")
        self._selected_game = game_name or None
        self._populate(self._followed, self._live, game_filter=self._selected_game)

    def _on_channel_selected(self):
        control = self._safe_control(self.CHANNEL_LIST_ID)
        if not control:
            return
        selected = control.getSelectedItem()
        if selected is None or selected.getProperty("is_live") != "true":
            return
        addon = xbmcaddon.Addon()
        token = auth.load_token(addon)
        if token is None:
            self._show_results_error(_MISSING_TOKEN_MESSAGE)
            return
        broadcaster_login = selected.getProperty("broadcaster_login")
        try:
            self._play_channel(broadcaster_login)
        except stream.StreamUnavailableError:
            self._show_results_error(_PLAYBACK_ERROR_MESSAGE)
        except Exception as exc:
            xbmc.log(
                "script.twitch.center: Home channel selection failed: " + repr(exc),
                xbmc.LOGERROR,
            )
            self._show_results_error(_PLAYBACK_ERROR_MESSAGE)

    def _play_channel(self, broadcaster_login):
        website_token = xbmcaddon.Addon().getSetting("website_token")
        url = stream.resolve_stream_url(broadcaster_login, website_token)
        if player.play_stream(url, broadcaster_login):
            error_label = self._safe_control(self.ERROR_LABEL_ID)
            if error_label:
                error_label.setLabel("")
        else:
            self._show_results_error(_PLAYBACK_ERROR_MESSAGE)
