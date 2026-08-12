"""Launches Kodi's native player for a resolved Twitch stream URL."""
import xbmc
import xbmcaddon
import xbmcgui
from inputstreamhelper import Helper

from lib.settings import Settings
from lib.windows.chat_overlay import ChatOverlay

_current_chat_watcher = None


class _ChatAwarePlayer(xbmc.Player):
    def __init__(self, overlay):
        super().__init__()
        self._overlay = overlay

    def onPlaybackStopped(self):
        self._teardown()

    def onPlaybackEnded(self):
        self._teardown()

    def onPlaybackError(self):
        self._teardown()

    def _teardown(self):
        self._overlay.close()


def play_stream(url, channel, settings=None, chat_overlay_cls=None, chat_client_cls=None):
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
    garbage-collected and stop receiving Kodi's callbacks."""
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
            overlay_cls = chat_overlay_cls or ChatOverlay
            overlay = overlay_cls(
                "script-twitch-center-chat-overlay.xml",
                xbmcaddon.Addon().getAddonInfo("path"),
                "Default",
                "1080i",
                channel=channel,
                chat_client_cls=chat_client_cls,
            )
            overlay.show()
            _current_chat_watcher = _ChatAwarePlayer(overlay)
        except Exception as exc:
            xbmc.log(
                "script.twitch.center: chat overlay failed to start: " + repr(exc),
                xbmc.LOGERROR,
            )

    return True
