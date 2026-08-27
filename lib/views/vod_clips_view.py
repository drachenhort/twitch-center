"""VODs & Clips content screen: the selected followed channel's VODs and Clips, both
video-only playback (no chat, no ad-skip relay - platform="twitch_vod"/"twitch_clip"
already route player.play_stream around both). Not a Window subclass - see MainWindow."""
import xbmc
import xbmcaddon
import xbmcgui

from lib import providers
from lib.twitch import api, auth
from lib.views import utils as view_utils
from lib.windows import player

VODS_LIST_ID = 801
CLIPS_LIST_ID = 802
TITLE_LABEL_ID = 803
ERROR_LABEL_ID = 804
RELOGIN_BUTTON_ID = 805

_MISSING_TOKEN_MESSAGE = "You're not logged in. Reopen the addon to log in."
_NETWORK_ERROR_MESSAGE = "Couldn't reach Twitch. Check your connection and reopen the addon."
_RELOGIN_MESSAGE = "Your session expired. Log in again to continue."
_NO_CONTEXT_MESSAGE = "No channel selected. Go back and pick a followed channel."
_PLAYBACK_ERROR_MESSAGE = "Couldn't start playback. Try again."
_EMPTY_RESULTS_MESSAGE = "No VODs or Clips for this channel."


class VodClipsView:
    VODS_LIST_ID = VODS_LIST_ID
    CLIPS_LIST_ID = CLIPS_LIST_ID
    TITLE_LABEL_ID = TITLE_LABEL_ID
    ERROR_LABEL_ID = ERROR_LABEL_ID
    RELOGIN_BUTTON_ID = RELOGIN_BUTTON_ID
    BACK_TARGET = "vod_clips_channels"

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
        if not self.context or not self.context.get("broadcaster_id"):
            # Not an auth/network failure - don't route through _show_error,
            # which unconditionally shows the "Log in again" button. Leave
            # the relogin button's visibility untouched (invisible by
            # default per the skin's <visible>false</visible>).
            error_label = self._safe_control(self.ERROR_LABEL_ID)
            if error_label:
                error_label.setLabel(_NO_CONTEXT_MESSAGE)
            return

        title_label = self._safe_control(self.TITLE_LABEL_ID)
        if title_label:
            title_label.setLabel(self.context.get("broadcaster_name", ""))

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
                "script.twitch.center: VODs & Clips content failed to load: " + repr(exc),
                xbmc.LOGERROR,
            )
            self._show_error(_NETWORK_ERROR_MESSAGE)

    def _load_and_populate(self, addon, client_id, token):
        broadcaster_id = self.context["broadcaster_id"]
        videos = api.get_videos(token["access_token"], client_id, broadcaster_id)
        clips = api.get_clips(token["access_token"], client_id, broadcaster_id)
        self._populate(videos, clips)

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
                "script.twitch.center: VODs & Clips content failed after token refresh: "
                + repr(exc),
                xbmc.LOGERROR,
            )
            self._show_error(_NETWORK_ERROR_MESSAGE)

    def _populate(self, videos, clips):
        error_label = self._safe_control(self.ERROR_LABEL_ID)
        if error_label:
            error_label.setLabel("")
        relogin_btn = self._safe_control(self.RELOGIN_BUTTON_ID)
        if relogin_btn:
            relogin_btn.setVisible(False)

        vods_control = self._safe_control(self.VODS_LIST_ID)
        if vods_control:
            vods_control.reset()
            vods_control.addItems([view_utils.build_video_list_item(v) for v in videos])

        clips_control = self._safe_control(self.CLIPS_LIST_ID)
        if clips_control:
            clips_control.reset()
            clips_control.addItems([view_utils.build_clip_list_item(c) for c in clips])

        if vods_control and vods_control.size():
            self.window.setFocusId(self.VODS_LIST_ID)
        elif clips_control and clips_control.size():
            self.window.setFocusId(self.CLIPS_LIST_ID)
        else:
            # A channel with no VODs and no Clips is a normal, common case -
            # not an authentication problem, so no relogin button here.
            if error_label:
                error_label.setLabel(_EMPTY_RESULTS_MESSAGE)

    def _show_error(self, message):
        vods_control = self._safe_control(self.VODS_LIST_ID)
        if vods_control:
            vods_control.reset()
        clips_control = self._safe_control(self.CLIPS_LIST_ID)
        if clips_control:
            clips_control.reset()
        error_label = self._safe_control(self.ERROR_LABEL_ID)
        if error_label:
            error_label.setLabel(message)
        self._show_relogin_button()

    def _show_relogin_button(self):
        relogin_btn = self._safe_control(self.RELOGIN_BUTTON_ID)
        if relogin_btn:
            relogin_btn.setVisible(True)
            self.window.setFocusId(self.RELOGIN_BUTTON_ID)

    def _show_results_error(self, message):
        error_label = self._safe_control(self.ERROR_LABEL_ID)
        if error_label:
            error_label.setLabel(message)

    def handle_action(self, action):
        if action.getId() != xbmcgui.ACTION_SELECT_ITEM:
            return
        focus = self.window.getFocusId()
        if focus == self.RELOGIN_BUTTON_ID:
            self.window._switch_view("login")
        elif focus == self.VODS_LIST_ID:
            self._on_vod_selected()
        elif focus == self.CLIPS_LIST_ID:
            self._on_clip_selected()

    def handle_click(self, control_id):
        pass

    def _on_vod_selected(self):
        control = self._safe_control(self.VODS_LIST_ID)
        if not control:
            return
        selected = control.getSelectedItem()
        if selected is None:
            return
        video_id = selected.getProperty("video_id")
        title = selected.getLabel()
        addon = xbmcaddon.Addon()
        try:
            url = providers.resolve_vod_url(addon, video_id)
            played = player.play_stream(url, title, platform="twitch_vod")
        except providers.StreamUnavailableError as exc:
            xbmc.log(
                "script.twitch.center: VOD unavailable (video_id=%r): %s" % (video_id, exc),
                xbmc.LOGERROR,
            )
            self._show_results_error(_PLAYBACK_ERROR_MESSAGE)
            return
        except Exception as exc:
            xbmc.log(
                "script.twitch.center: VOD selection failed: " + repr(exc), xbmc.LOGERROR
            )
            self._show_results_error(_PLAYBACK_ERROR_MESSAGE)
            return
        if not played:
            self._show_results_error(_PLAYBACK_ERROR_MESSAGE)

    def _on_clip_selected(self):
        control = self._safe_control(self.CLIPS_LIST_ID)
        if not control:
            return
        selected = control.getSelectedItem()
        if selected is None:
            return
        clip_id = selected.getProperty("clip_id")
        title = selected.getLabel()
        addon = xbmcaddon.Addon()
        try:
            url = providers.resolve_clip_url(addon, clip_id)
            played = player.play_stream(url, title, platform="twitch_clip")
        except providers.StreamUnavailableError as exc:
            xbmc.log(
                "script.twitch.center: Clip unavailable (clip_id=%r): %s" % (clip_id, exc),
                xbmc.LOGERROR,
            )
            self._show_results_error(_PLAYBACK_ERROR_MESSAGE)
            return
        except Exception as exc:
            xbmc.log(
                "script.twitch.center: Clip selection failed: " + repr(exc), xbmc.LOGERROR
            )
            self._show_results_error(_PLAYBACK_ERROR_MESSAGE)
            return
        if not played:
            self._show_results_error(_PLAYBACK_ERROR_MESSAGE)
