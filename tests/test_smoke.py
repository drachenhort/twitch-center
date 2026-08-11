"""Baseline 'does this even load' check across the whole lib package."""
import importlib


MODULES = [
    "lib.twitch.auth",
    "lib.twitch.api",
    "lib.twitch.stream",
    "lib.twitch.irc",
    "lib.windows.login",
    "lib.windows.home",
    "lib.windows.discover",
    "lib.windows.player",
    "lib.windows.chat_overlay",
    "lib.windows.chat_window",
    "lib.settings",
    "lib.main",
]


def test_all_lib_modules_import_cleanly():
    for module_name in MODULES:
        importlib.import_module(module_name)


def test_main_run_is_callable():
    from lib import main
    assert callable(main.run)
