"""
SIGMA Streaming Hub addon entry point.

Dispatches RunScript calls and installs the custom keymap on startup.
"""
import sys

import xbmc
import xbmcaddon
import xbmcgui

from lib import keymap_installer, providers
from lib.player import audio


def dispatch(action, params):
    """Route a RunScript action to its handler."""
    if action == "cycle_audio":
        audio.cycle_audio_stream()
    elif action == "refresh_kick_categories":
        _refresh_kick_categories()
    else:
        xbmc.log(
            "script.twitch.center: unknown action '{}'".format(action),
            xbmc.LOGWARNING,
        )


def _refresh_kick_categories():
    """Handler for the "Refresh Kick categories" settings button - rebuilds
    the local category cache search runs against (see
    lib.kick_category_cache), since Kick's search API can't be queried live
    for this and the cache otherwise never updates itself."""
    addon = xbmcaddon.Addon()
    dialog = xbmcgui.Dialog()
    progress = xbmcgui.DialogProgressBG()
    progress.create("SIGMA Streaming Hub", "Refreshing Kick categories...")
    try:
        categories = providers.refresh_kick_categories_cache(addon)
    except Exception as exc:
        xbmc.log(
            "script.twitch.center: Kick category cache refresh failed: " + repr(exc),
            xbmc.LOGERROR,
        )
        dialog.notification("SIGMA Streaming Hub", "Kick category refresh failed - see log.")
        return
    finally:
        progress.close()
    dialog.notification("SIGMA Streaming Hub", "Kick categories updated ({} found).".format(len(categories)))


def main():
    # Always ensure the custom keymap is installed (idempotent).
    keymap_installer.install()

    args = sys.argv[1:]
    if args:
        dispatch(args[0], args[1:])
    else:
        # Default entry point: the addon was opened from the programs menu.
        xbmc.log("script.twitch.center: default entry point", xbmc.LOGINFO)


if __name__ == "__main__":
    main()
