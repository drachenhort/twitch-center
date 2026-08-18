"""Launches Kodi's native player for a resolved Twitch stream URL."""
import threading
import time

import xbmc
import xbmcaddon
import xbmcgui
from inputstreamhelper import Helper

from lib.settings import Settings
from lib.twitch import api
from lib.twitch import eventsub
from lib.twitch import irc
from lib.twitch import stream
from lib.windows.chat_overlay import ChatOverlay

_current_chat_watcher = None

_CHAT_CLIENT_CLS_BY_ENGINE = {"irc": irc.ChatClient, "eventsub": eventsub.ChatClient}


class AdBreakState:
    """Tracks an active Twitch ad-break notification."""

    def __init__(self):
        self.active = False
        self.started_at = None
        self.duration = 0
        self.channel = None
        self.is_automatic = False

    def begin(self, event):
        self.active = True
        self.started_at = event.get("started_at")
        self.duration = int(event.get("duration_seconds", 0))
        self.channel = event.get("broadcaster_user_login")
        self.is_automatic = bool(event.get("is_automatic", False))

    def clear(self):
        self.active = False
        self.started_at = None
        self.duration = 0
        self.channel = None
        self.is_automatic = False


class RecoveryManager:
    """Refreshes the Twitch stream URL and restarts Kodi playback."""

    def __init__(self, player, channel, website_token=None):
        self._player = player
        self._channel = channel
        self._website_token = website_token
        self._lock = threading.Lock()

    def recover(self):
        if not self._lock.acquire(blocking=False):
            return
        try:
            try:
                new_url = stream.resolve_stream_url(self._channel, self._website_token)
            except stream.StreamUnavailableError as exc:
                xbmc.log(
                    "script.twitch.center: recovery cannot resolve stream: " + repr(exc),
                    xbmc.LOGERROR,
                )
                return

            is_helper = Helper("hls")
            if not is_helper.check_inputstream():
                xbmc.log(
                    "script.twitch.center: recovery aborted, inputstream.adaptive unavailable",
                    xbmc.LOGERROR,
                )
                return

            list_item = xbmcgui.ListItem(path=new_url)
            list_item.setProperty("inputstream", is_helper.inputstream_addon)
            list_item.setProperty("inputstream.adaptive.manifest_type", "hls")
            list_item.setMimeType("application/x-mpegURL")
            list_item.setContentLookup(False)
            self._player.play(new_url, list_item)
            xbmc.log(
                "script.twitch.center: restarted playback with fresh stream URL",
                xbmc.LOGINFO,
            )
        finally:
            self._lock.release()


class PlaybackWatchdog:
    """Monitors Kodi playback and triggers recovery when it stalls."""

    _CHECK_INTERVAL = 1.0
    _STALL_THRESHOLD = 15.0
    _AD_GRACE_PERIOD = 10.0

    def __init__(self, player, ad_state, recovery_manager, is_paused_fn=None):
        self._player = player
        self._ad_state = ad_state
        self._recovery = recovery_manager
        self._is_paused_fn = is_paused_fn or (lambda: False)
        self._last_position = -1.0
        self._last_progress_time = None
        self._cancel_event = threading.Event()
        self._thread = None

    def start(self):
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self):
        self._cancel_event.set()
        if self._thread is not None:
            self._thread.join(timeout=2)

    def _run(self):
        while not self._cancel_event.is_set():
            self._cancel_event.wait(self._CHECK_INTERVAL)
            if self._cancel_event.is_set():
                break
            self._check_once()

    def _check_once(self):
        if not self._player.isPlaying():
            self._last_progress_time = None
            return False
        try:
            if self._is_paused_fn():
                return False
            position = self._player.getTime()
        except Exception:
            return False

        if position != self._last_position:
            self._last_position = position
            self._last_progress_time = time.monotonic()
            return False

        if self._last_progress_time is None:
            self._last_progress_time = time.monotonic()
            return False

        stall_duration = time.monotonic() - self._last_progress_time
        threshold = self._stall_threshold()
        if stall_duration >= threshold:
            xbmc.log(
                "script.twitch.center: playback stalled for "
                + str(int(stall_duration))
                + "s, recovering",
                xbmc.LOGINFO,
            )
            self._recovery.recover()
            self._last_progress_time = time.monotonic()
            return True
        return False

    def _stall_threshold(self):
        if self._ad_state.active:
            return max(self._ad_state.duration, 0) + self._AD_GRACE_PERIOD
        return self._STALL_THRESHOLD


class _ChatAwarePlayer(xbmc.Player):
    def __init__(self, overlay, url=None, channel=None, website_token=None, enable_watchdog=True):
        super().__init__()
        self._overlay = overlay
        self._url = url
        self._channel = channel
        self._website_token = website_token
        self._paused = False
        self._ad_state = AdBreakState()
        self._recovery = RecoveryManager(self, channel, website_token)
        self._watchdog = PlaybackWatchdog(
            self, self._ad_state, self._recovery, is_paused_fn=lambda: self._paused
        )
        if enable_watchdog:
            self._watchdog.start()

    def onPlayBackPaused(self):
        self._paused = True

    def onPlayBackResumed(self):
        self._paused = False

    def onPlayBackSpeedChanged(self, speed):
        self._paused = speed == 0

    def onPlayBackStopped(self):
        self._teardown()

    def onPlayBackEnded(self):
        self._teardown()

    def onPlayBackError(self):
        self._teardown()

    def _teardown(self):
        self._watchdog.stop()
        self._overlay.close()


def _website_token_from_settings(settings):
    return getattr(settings, "website_token", None) or None


def play_stream(url, channel, settings=None, access_token=None, client_id=None, user_id=None,
                 chat_overlay_cls=None, chat_client_cls=None):
    """Hand the resolved HLS URL to Kodi's player via inputstream.adaptive,
    which handles proper adaptive-bitrate switching for live multi-quality
    HLS (unlike Kodi's native demuxer playing the URL directly). Returns
    True if playback was started, False if inputstream.adaptive isn't
    available and the user declined installing it (Helper.check_inputstream
    handles that install-prompt UI itself).

    If playback started and chat_display_mode includes "overlay", also
    creates and shows a ChatOverlay for `channel`, and keeps a
    _ChatAwarePlayer alive at module level so its onPlaybackStopped/
    onPlaybackEnded callbacks close the overlay and disconnect its chat
    client when this stream ends - a locally-scoped instance would be
    garbage-collected and stop receiving Kodi's callbacks.

    access_token/client_id/user_id are the logged-in user's Helix
    credentials - required only when settings.chat_engine == "eventsub"
    (to resolve the channel's numeric id and subscribe); ignored for the
    default "irc" engine."""
    global _current_chat_watcher

    is_helper = Helper("hls")
    if not is_helper.check_inputstream():
        return False

    list_item = xbmcgui.ListItem(path=url)
    list_item.setProperty("inputstream", is_helper.inputstream_addon)
    list_item.setProperty("inputstream.adaptive.manifest_type", "hls")
    list_item.setMimeType("application/x-mpegURL")
    list_item.setContentLookup(False)
    xbmc.Player().play(url, list_item)

    settings = settings or Settings()
    if settings.chat_display_mode in ("overlay", "both"):
        try:
            if _current_chat_watcher is not None:
                _current_chat_watcher._teardown()
                _current_chat_watcher = None

            engine = settings.chat_engine
            broadcaster_user_id = None
            if chat_client_cls is None and engine == "eventsub":
                user = api.get_user_by_login(access_token, client_id, channel)
                if user is None:
                    xbmc.log(
                        "script.twitch.center: EventSub chat engine could not resolve "
                        "broadcaster id for %r, falling back to IRC" % channel,
                        xbmc.LOGWARNING,
                    )
                    engine = "irc"
                else:
                    broadcaster_user_id = user["id"]

            resolved_chat_client_cls = chat_client_cls or _CHAT_CLIENT_CLS_BY_ENGINE[engine]

            overlay_cls = chat_overlay_cls or ChatOverlay
            overlay = overlay_cls(
                "script-twitch-center-chat-overlay.xml",
                xbmcaddon.Addon().getAddonInfo("path"),
                "Default",
                "1080i",
                channel=channel,
                access_token=access_token,
                client_id=client_id,
                broadcaster_user_id=broadcaster_user_id,
                user_id=user_id,
                chat_client_cls=resolved_chat_client_cls,
            )
            overlay.show()
            website_token = _website_token_from_settings(settings)
            _current_chat_watcher = _ChatAwarePlayer(
                overlay, url=url, channel=channel, website_token=website_token
            )
        except Exception as exc:
            xbmc.log(
                "script.twitch.center: chat overlay failed to start: " + repr(exc),
                xbmc.LOGERROR,
            )

    return True
