"""
SIGMA Streaming Hub addon entry point.

Dispatches RunScript calls and installs the custom keymap on startup.
"""
import sys

import xbmc

from lib import keymap_installer
from lib.player import audio


def dispatch(action, params):
    """Route a RunScript action to its handler."""
    if action == "cycle_audio":
        audio.cycle_audio_stream()
    else:
        xbmc.log(
            "script.twitch.center: unknown action '{}'".format(action),
            xbmc.LOGWARNING,
        )


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
