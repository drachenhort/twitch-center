"""Shared "play this channel" flow for views that list live streams
(Discover's results, the category streams page). Resolves the stream URL,
hands it to the player, and reports any failure through the caller's
show_error callback so each view can put the message in its own label."""
import xbmc
import xbmcaddon
import xbmcgui

from lib import providers
from lib.windows import player

PLAYBACK_ERROR_MESSAGE = "Couldn't start playback. Try again."


def play_channel(platform, broadcaster_login, show_error, token=None, client_id=None):
    """Play `broadcaster_login` on `platform` ("twitch" or "kick"). Twitch needs
    `token` and `client_id`. Returns True when playback started; otherwise
    calls show_error(PLAYBACK_ERROR_MESSAGE) and returns False. Never raises."""
    addon = xbmcaddon.Addon()
    try:
        url = providers.resolve_stream_url(addon, platform, broadcaster_login)
        play_kwargs = {"platform": platform}
        if platform == "twitch":
            play_kwargs.update(
                access_token=token["access_token"], client_id=client_id, user_id=token["user_id"]
            )
        played = player.play_stream(url, broadcaster_login, **play_kwargs)
    except providers.StreamStartError as exc:
        show_error(PLAYBACK_ERROR_MESSAGE)
        xbmcgui.Dialog().ok("Couldn't start stream", str(exc))
        return False
    except providers.StreamUnavailableError:
        show_error(PLAYBACK_ERROR_MESSAGE)
        return False
    except Exception as exc:
        xbmc.log(
            "script.twitch.center: channel selection failed: " + repr(exc),
            xbmc.LOGERROR,
        )
        show_error(PLAYBACK_ERROR_MESSAGE)
        return False
    if not played:
        show_error(PLAYBACK_ERROR_MESSAGE)
    return bool(played)
