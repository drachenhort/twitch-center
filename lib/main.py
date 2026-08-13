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
from lib.windows.home import HomeWindow
from lib.windows.login import LoginWindow


def show_quit_prompt():
    """Display a confirmation dialog when the user attempts to quit."""
    dialog = xbmcgui.Dialog()
    return dialog.yesno(
        "Twitch Center",
        "Are you sure you want to quit?",
        "Your chat and stream will be closed."
    )


def run(argv, addon=None, login_window_cls=None, home_window_cls=None, monitor_cls=None):
    """Route to LoginWindow if no token is saved, otherwise HomeWindow.

    Kodi's xbmc.python.script addons run to completion and tear down; a
    non-modal window (shown via show(), not doModal()) would be destroyed
    the instant run() returns. So after showing the window, block on an
    xbmc.Monitor() wait loop until either Kodi is shutting down or the
    window signals (via its closed_event) that it's done."""
    addon = addon or xbmcaddon.Addon()
    login_window_cls = login_window_cls or LoginWindow
    home_window_cls = home_window_cls or HomeWindow
    monitor_cls = monitor_cls or xbmc.Monitor

    token = auth.load_token(addon)
    if token is None:
        window = login_window_cls(
            "script-twitch-center-login.xml", addon.getAddonInfo("path"), "Default", "1080i"
        )
    else:
        window = home_window_cls(
            "script-twitch-center-home.xml", addon.getAddonInfo("path"), "Default", "1080i"
        )
    window.show()

    monitor = monitor_cls()
    while not window.closed_event.is_set():
        if monitor.waitForAbort(1):
            break
        if getattr(window, "quit_requested", False):
            if not show_quit_prompt():
                continue
            window.quit_requested = False
        if getattr(window, "login_succeeded", False):
            # LoginWindow can't open Home itself: _on_status runs on its
            # background polling thread, and xbmcgui window creation must
            # happen on the main thread (unlike Home/Discover's own
            # transitions, which fire from onAction on the main thread).
            closed_event = window.closed_event
            window.close()
            window = home_window_cls(
                "script-twitch-center-home.xml",
                addon.getAddonInfo("path"),
                "Default",
                "1080i",
                closed_event=closed_event,
            )
            window.show()


if __name__ == "__main__":
    run(sys.argv)
