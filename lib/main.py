"""Addon entry point, referenced by addon.xml's library="lib/main.py"."""
import os
import sys

# Kodi runs this file as a script, which puts its own directory (.../lib) on
# sys.path rather than the addon root — so "from lib.twitch import auth"
# below would fail with ModuleNotFoundError under real Kodi (though not
# under pytest, which adds the root via pytest.ini's pythonpath=.). Add the
# addon root explicitly before any lib.* import.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import xbmc
import xbmcaddon
import xbmcgui

from lib.twitch import auth
from lib.windows.main_window import MainWindow

# Release date of the version in addon.xml - bump this alongside the version number and
# CHANGELOG.md entry for every shipped feature/fix, so the on-screen label always matches
# the most recent changelog entry rather than drifting out of sync.
VERSION_DATE = "2026-08-29"


def show_quit_prompt():
    """Display a confirmation dialog when the user attempts to quit."""
    dialog = xbmcgui.Dialog()
    return dialog.yesno(
        "SIGMA Streaming Hub",
        "Are you sure you want to quit?\nYour chat and stream will be closed.",
        nolabel="No",
        yeslabel="Yes"
    )


def run(argv, addon=None, main_window_cls=None, monitor_cls=None):
    """Construct MainWindow once and block until it closes for real.

    Kodi's xbmc.python.script addons run to completion and tear down; a
    non-modal window (shown via show(), not doModal()) would be destroyed
    the instant run() returns. So after showing the window, block on an
    xbmc.Monitor() wait loop until either Kodi is shutting down or the
    window signals (via its closed_event) that it's done. This is the same
    wait-loop shape as before the persistent-window migration - only window
    construction collapsed from "one per screen transition" to "once, ever"."""
    addon = addon or xbmcaddon.Addon()
    main_window_cls = main_window_cls or MainWindow
    monitor_cls = monitor_cls or xbmc.Monitor

    token = auth.load_token(addon)
    initial_view = "menu" if token else "login"
    version_text = "v%s (%s)" % (addon.getAddonInfo("version"), VERSION_DATE)
    window = main_window_cls(
        "script-twitch-center-main.xml",
        addon.getAddonInfo("path"),
        "Default",
        "1080i",
        initial_view=initial_view,
        version_text=version_text,
    )
    window.show()

    monitor = monitor_cls()
    while not window.closed_event.is_set():
        if monitor.waitForAbort(1):
            break
        if getattr(window.closed_event, "quit_requested", False):
            if not show_quit_prompt():
                window.closed_event.quit_requested = False
                continue
            window.close()
            window.closed_event.set()
            window.closed_event.quit_requested = False
            break
        login_view = window._views.get("login")
        if login_view is not None and getattr(login_view, "login_succeeded", False):
            window._switch_view("menu")
            # Clear the flag rather than latching "we already switched once":
            # LoginView is reused for the whole session, so a LATER login
            # (via "Log in again") must be able to hand off to Menu too.
            login_view.login_succeeded = False
        kick_login_view = window._views.get("kick_login")
        if kick_login_view is not None and getattr(kick_login_view, "login_succeeded", False):
            window._switch_view("menu")
            kick_login_view.login_succeeded = False


if __name__ == "__main__":
    run(sys.argv)
