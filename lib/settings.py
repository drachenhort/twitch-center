"""Typed wrapper over xbmcaddon settings. Only lib/windows/* and this module import Kodi's xbmc* modules."""
import xbmcaddon

VALID_CHAT_DISPLAY_MODES = ("overlay", "standalone", "both")
DEFAULT_CHAT_DISPLAY_MODE = "both"

VALID_CHAT_ENGINES = ("irc", "eventsub")
DEFAULT_CHAT_ENGINE = "irc"


class Settings:
    def __init__(self, addon=None):
        self._addon = addon or xbmcaddon.Addon()

    @property
    def chat_display_mode(self):
        value = self._addon.getSetting("chat_display_mode")
        if value in VALID_CHAT_DISPLAY_MODES:
            return value
        return DEFAULT_CHAT_DISPLAY_MODE

    @property
    def chat_engine(self):
        value = self._addon.getSetting("chat_engine")
        if value in VALID_CHAT_ENGINES:
            return value
        return DEFAULT_CHAT_ENGINE

    @property
    def show_offline_channels(self):
        return self._addon.getSettingBool("show_offline_channels")
