"""Typed wrapper over xbmcaddon settings. Only lib/windows.py and this module touch xbmcaddon."""
import xbmcaddon

VALID_CHAT_DISPLAY_MODES = ("overlay", "standalone", "both")
DEFAULT_CHAT_DISPLAY_MODE = "both"


class Settings:
    def __init__(self, addon=None):
        self._addon = addon or xbmcaddon.Addon()

    @property
    def chat_display_mode(self):
        value = self._addon.getSetting("chat_display_mode")
        if value in VALID_CHAT_DISPLAY_MODES:
            return value
        return DEFAULT_CHAT_DISPLAY_MODE
