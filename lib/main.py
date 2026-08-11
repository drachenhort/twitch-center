"""Addon entry point, referenced by addon.xml's library="lib/main.py"."""
import sys

import xbmcaddon

from lib.twitch import auth
from lib.windows.home import HomeWindow
from lib.windows.login import LoginWindow


def run(argv, addon=None, login_window_cls=None, home_window_cls=None):
    """Route to LoginWindow if no token is saved, otherwise HomeWindow."""
    addon = addon or xbmcaddon.Addon()
    login_window_cls = login_window_cls or LoginWindow
    home_window_cls = home_window_cls or HomeWindow

    token = auth.load_token(addon)
    if token is None:
        window = login_window_cls("script-twitch-center-login.xml", addon.getAddonInfo("path"))
    else:
        window = home_window_cls("script-twitch-center-home.xml", addon.getAddonInfo("path"))
    window.show()


if __name__ == "__main__":
    run(sys.argv)
