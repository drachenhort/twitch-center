"""Live Streams view: the user's followed channels, live ones surfaced
first. Not a Window subclass - see MainWindow."""
import xbmc
import xbmcaddon
import xbmcgui

from lib import providers
from lib.settings import Settings
from lib.twitch import api, auth, gql
from lib.views import utils as view_utils
from lib.views.kick_favorites_menu import show_kick_favorite_context_menu
from lib.windows import player

CHANNEL_LIST_ID = 201
EMPTY_LABEL_ID = 202
ERROR_LABEL_ID = 203
RELOGIN_BUTTON_ID = 204
GAMES_LIST_ID = 205
TITLE_LABEL_ID = 207
REFRESH_BUTTON_ID = 206

_MISSING_TOKEN_MESSAGE = "You're not logged in. Reopen the addon to log in."
_EMPTY_FOLLOWED_MESSAGE = "You're not following anyone yet."
_NO_LIVE_MESSAGE = "None of your followed channels are live right now."
_NETWORK_ERROR_MESSAGE = "Couldn't reach Twitch. Check your connection and reopen the addon."
_RELOGIN_MESSAGE = "Your session expired. Log in again to continue."
_ALL_GAMES_LABEL = "All"
_NO_MATCHES_MESSAGE = "None of your live followed channels are playing this game right now."
_PLAYBACK_ERROR_MESSAGE = "Couldn't start playback. Try again."


_thumbnail_url = view_utils.thumbnail_url


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
    if stream_data:
        return view_utils.build_live_list_item(channel, stream_data)
    return view_utils.build_offline_list_item(channel)


_build_kick_list_item = view_utils.build_kick_list_item
_interleave_live_items = view_utils.interleave_live_items


class LiveStreamsView:
    CHANNEL_LIST_ID = CHANNEL_LIST_ID
    EMPTY_LABEL_ID = EMPTY_LABEL_ID
    ERROR_LABEL_ID = ERROR_LABEL_ID
    RELOGIN_BUTTON_ID = RELOGIN_BUTTON_ID
    GAMES_LIST_ID = GAMES_LIST_ID
    TITLE_LABEL_ID = TITLE_LABEL_ID
    REFRESH_BUTTON_ID = REFRESH_BUTTON_ID

    def __init__(self, window, closed_event=None, settings=None):
        self.window = window
        # Shared across every view hosted by MainWindow, which bootstraps it.
        self.closed_event = closed_event
        self._settings = settings or Settings()
        self._followed = []
        self._live = []
        self._games = []
        self._kick_live = []
        self._selected_game = None

    def _safe_control(self, control_id):
        """Safely retrieve a control, returning None if it doesn't exist."""
        try:
            return self.window.getControl(control_id)
        except Exception:
            return None

    def activate(self):
        addon = xbmcaddon.Addon()
        title_label = self._safe_control(self.TITLE_LABEL_ID)
        if title_label:
            title_label.setLabel("Live Streams")
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
        kick_live = providers.get_kick_live_favorites(addon)
        self._followed = followed
        self._live = live_list
        self._games = games
        self._kick_live = kick_live
        self._selected_game = None
        self._populate_games(games)
        self._populate(followed, live_list, kick_live)
        # MainWindow focuses a view's DEFAULT_FOCUS_ID (if any) before
        # activate() runs; claim the channel list explicitly now that it is
        # actually populated, so a leftover keypress can't trigger an
        # unintended action while focus is still up for grabs. If it stayed
        # empty there is nothing to focus, so offer the re-login button and
        # leave the explanatory message on screen (Back returns to Menu).
        channel_list = self._safe_control(self.CHANNEL_LIST_ID)
        if channel_list and channel_list.size():
            self.window.setFocusId(self.CHANNEL_LIST_ID)
        else:
            self._show_relogin_button()

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
        # A successful load supersedes any earlier error state.
        relogin_btn = self._safe_control(self.RELOGIN_BUTTON_ID)
        if relogin_btn:
            relogin_btn.setVisible(False)

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

    def _populate(self, followed, live_list, kick_live, game_filter=None):
        empty_label = self._safe_control(self.EMPTY_LABEL_ID)
        if empty_label:
            empty_label.setLabel("")
        error_label = self._safe_control(self.ERROR_LABEL_ID)
        if error_label:
            error_label.setLabel("")
        control = self._safe_control(self.CHANNEL_LIST_ID)
        if control:
            control.reset()
            if not followed and not kick_live:
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
                # The games filter is Twitch-only - Kick has no equivalent
                # taxonomy, so a selected filter hides Kick results entirely
                # rather than showing them unfiltered (documented decision).
                kick_live = []
            elif not self._settings.show_offline_channels:
                offline = []
            items = _interleave_live_items(live, kick_live)
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
        # Stay on Live Streams: switching to Menu here would hide the group
        # before the user could read the message we just set. Back (handled
        # centrally by MainWindow) still returns to Menu at any time.
        self._show_relogin_button()

    def _show_relogin_button(self):
        relogin_btn = self._safe_control(self.RELOGIN_BUTTON_ID)
        if relogin_btn:
            relogin_btn.setVisible(True)
            self.window.setFocusId(self.RELOGIN_BUTTON_ID)

    def _show_results_error(self, message):
        """Transient failure (e.g. one playback attempt): keep the channel
        list and games row intact so a single failure doesn't force an
        addon restart - mirrors DiscoverView's _show_results_error."""
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
            elif focus == self.CHANNEL_LIST_ID:
                self._on_channel_selected()
            elif focus == self.REFRESH_BUTTON_ID:
                self._on_refresh()
        elif action.getId() == xbmcgui.ACTION_CONTEXT_MENU:
            if self.window.getFocusId() == self.CHANNEL_LIST_ID:
                self._on_context_menu()

    def handle_click(self, control_id):
        pass

    def _on_refresh(self):
        self.activate()

    def _on_context_menu(self):
        control = self._safe_control(self.CHANNEL_LIST_ID)
        if not control:
            return
        selected = control.getSelectedItem()
        if selected is None or selected.getProperty("platform") != "kick":
            return
        addon = xbmcaddon.Addon()
        changed = show_kick_favorite_context_menu(addon, selected.getProperty("broadcaster_login"))
        if changed:
            self._kick_live = providers.get_kick_live_favorites(addon)
            self._populate(self._followed, self._live, self._kick_live, game_filter=self._selected_game)

    def _on_game_selected(self):
        control = self._safe_control(self.GAMES_LIST_ID)
        if not control:
            return
        selected = control.getSelectedItem()
        if selected is None:
            return
        game_name = selected.getProperty("game_name")
        self._selected_game = game_name or None
        self._populate(self._followed, self._live, self._kick_live, game_filter=self._selected_game)

    def _on_channel_selected(self):
        control = self._safe_control(self.CHANNEL_LIST_ID)
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
                "script.twitch.center: Live Streams channel selection failed: " + repr(exc),
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
