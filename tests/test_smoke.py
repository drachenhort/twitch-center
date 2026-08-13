"""Baseline 'does this even load' check across the whole lib package."""
import importlib


MODULES = [
    "lib.twitch.auth",
    "lib.twitch.api",
    "lib.twitch.stream",
    "lib.twitch.irc",
    "lib.windows.main_window",
    "lib.windows.player",
    "lib.windows.chat_overlay",
    "lib.windows.chat_window",
    "lib.views.login_view",
    "lib.views.menu_view",
    "lib.views.live_streams_view",
    "lib.views.discover_view",
    "lib.views.search_view",
    "lib.settings",
    "lib.main",
]


def test_all_lib_modules_import_cleanly():
    for module_name in MODULES:
        importlib.import_module(module_name)


def test_main_run_is_callable():
    from lib import main
    assert callable(main.run)
