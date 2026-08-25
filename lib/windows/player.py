"""Launches Kodi's native player for a resolved Twitch stream URL."""
import threading
import time

import xbmc
import xbmcaddon
import xbmcgui
from inputstreamhelper import Helper

from lib import providers
from lib.hls_ad_relay import AdSkipRelay
from lib.settings import Settings
from lib.twitch import api
from lib.twitch import eventsub
from lib.twitch import irc
from lib.windows.chat_overlay import ChatOverlay
from lib.windows.variable_chat_overlay import VariableChatOverlay

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
    """Refreshes the stream URL (via the correct platform's resolver) and
    restarts Kodi playback. If relay/relay_url are set (skip_twitch_ads
    active), re-plays the relay's already-running local URL instead of
    re-resolving/reinstalling ISA - the relay's own fetch loop already
    retries network hiccups internally, so a stall here is most likely
    Kodi's player itself, not a dead upstream URL."""

    def __init__(self, player, channel, platform="twitch", relay=None, relay_url=None):
        self._player = player
        self._channel = channel
        self._platform = platform
        self._relay = relay
        self._relay_url = relay_url
        self._lock = threading.Lock()

    def recover(self):
        if not self._lock.acquire(blocking=False):
            return
        try:
            if self._relay is not None:
                list_item = xbmcgui.ListItem(path=self._relay_url)
                list_item.setMimeType("video/mp2t")
                list_item.setContentLookup(False)
                self._player.play(self._relay_url, list_item)
                xbmc.log(
                    "script.twitch.center: restarted playback via the ad-skip relay",
                    xbmc.LOGINFO,
                )
                return

            addon = xbmcaddon.Addon()
            try:
                new_url = providers.resolve_stream_url(addon, self._platform, self._channel)
            except providers.StreamUnavailableError as exc:
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
    def __init__(self, overlay, url=None, channel=None, platform="twitch", enable_watchdog=True,
                 relay=None):
        super().__init__()
        self._overlay = overlay
        self._url = url
        self._channel = channel
        self._paused = False
        self._ad_state = AdBreakState()
        self._relay = relay
        self._recovery = RecoveryManager(self, channel, platform, relay=relay, relay_url=url)
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
        if self._overlay is not None:
            self._overlay.close()
        if self._relay is not None:
            self._relay.stop()


def play_stream(url, channel, settings=None, access_token=None, client_id=None, user_id=None,
                 chat_overlay_cls=None, chat_client_cls=None, platform="twitch"):
    """Hand the resolved HLS URL to Kodi's player - via inputstream.adaptive,
    which handles proper adaptive-bitrate switching for live multi-quality
    HLS, unless settings.skip_twitch_ads is on, in which case a local
    AdSkipRelay is started first and its local relay URL is played directly
    (raw MPEG-TS, no ISA) instead of the original HLS URL. Returns True if
    playback was started, False if inputstream.adaptive isn't available and
    the user declined installing it (Helper.check_inputstream handles that
    install-prompt UI itself) - not applicable when skip_twitch_ads is on,
    since that path never touches ISA.

    If playback started and platform == "twitch", keeps a _ChatAwarePlayer
    alive at module level whenever there's a ChatOverlay to manage and/or an
    AdSkipRelay to tear down - its onPlaybackStopped/onPlaybackEnded/
    onPlaybackError callbacks close the overlay and stop the relay when this
    stream ends, since a locally-scoped instance would be garbage-collected
    and stop receiving Kodi's callbacks. platform=="kick" always skips chat
    entirely, regardless of chat_overlay_enabled - there is no Kick chat
    client yet.

    access_token/client_id/user_id are the logged-in Twitch user's Helix
    credentials - required only when settings.chat_engine == "eventsub"
    (to resolve the channel's numeric id and subscribe); ignored for the
    default "irc" engine and always ignored for platform=="kick"."""
    global _current_chat_watcher

    settings = settings or Settings()

    relay = None
    play_url = url
    if platform == "twitch" and settings.skip_twitch_ads:
        relay = AdSkipRelay(
            url,
            log_fn=lambda message: xbmc.log(
                "script.twitch.center: ad-skip relay: " + message, xbmc.LOGINFO
            ),
        )
        play_url = relay.start()
        list_item = xbmcgui.ListItem(path=play_url)
        list_item.setMimeType("video/mp2t")
        list_item.setContentLookup(False)
    else:
        is_helper = Helper("hls")
        if not is_helper.check_inputstream():
            return False
        list_item = xbmcgui.ListItem(path=play_url)
        list_item.setProperty("inputstream", is_helper.inputstream_addon)
        list_item.setProperty("inputstream.adaptive.manifest_type", "hls")
        list_item.setMimeType("application/x-mpegURL")
        list_item.setContentLookup(False)

    if _current_chat_watcher is not None:
        _current_chat_watcher._teardown()
        _current_chat_watcher = None

    overlay = None
    if platform == "twitch" and settings.chat_overlay_enabled:
        try:
            engine = settings.chat_engine
            broadcaster_user_id = None
            if chat_client_cls is None and engine == "eventsub":
                try:
                    user = api.get_user_by_login(access_token, client_id, channel)
                except Exception as exc:
                    xbmc.log(
                        "script.twitch.center: EventSub broadcaster-id lookup failed for "
                        "%r (%r), falling back to IRC" % (channel, repr(exc)),
                        xbmc.LOGWARNING,
                    )
                    user = None
                if user is None:
                    xbmc.log(
                        "script.twitch.center: EventSub chat engine could not resolve "
                        "broadcaster id for %r, falling back to IRC" % channel,
                        xbmc.LOGWARNING,
                    )
                    engine = "irc"
                else:
                    broadcaster_user_id = user["id"]

            resolved_chat_client_cls = chat_client_cls or _CHAT_CLIENT_CLS_BY_ENGINE.get(
                engine, irc.ChatClient
            )

            if chat_overlay_cls is not None:
                overlay_cls = chat_overlay_cls
            elif settings.chat_overlay_variable_height:
                overlay_cls = VariableChatOverlay
            else:
                overlay_cls = ChatOverlay
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
        except Exception as exc:
            xbmc.log(
                "script.twitch.center: chat overlay failed to start: " + repr(exc),
                xbmc.LOGERROR,
            )
            overlay = None

    if overlay is not None or relay is not None:
        _current_chat_watcher = _ChatAwarePlayer(
            overlay, url=play_url, channel=channel, platform=platform, relay=relay
        )
        _current_chat_watcher.play(play_url, list_item)
    else:
        xbmc.Player().play(play_url, list_item)

    return True
