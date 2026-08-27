"""Typed wrapper over xbmcaddon settings. Only lib/windows/* and this module import Kodi's xbmc* modules."""
import xbmcaddon

VALID_CHAT_ENGINES = ("irc", "eventsub")
DEFAULT_CHAT_ENGINE = "irc"


class Settings:
    def __init__(self, addon=None):
        self._addon = addon or xbmcaddon.Addon()

    @property
    def chat_overlay_enabled(self):
        return self._addon.getSettingBool("chat_overlay_enabled")

    @property
    def chat_engine(self):
        value = self._addon.getSetting("chat_engine")
        if value in VALID_CHAT_ENGINES:
            return value
        return DEFAULT_CHAT_ENGINE

    @property
    def show_offline_channels(self):
        return self._addon.getSettingBool("show_offline_channels")

    @property
    def chat_overlay_variable_height(self):
        return self._addon.getSettingBool("chat_overlay_variable_height")

    @property
    def skip_twitch_ads(self):
        return self._addon.getSettingBool("skip_twitch_ads")

    @property
    def live_notify_enabled(self):
        return self._addon.getSettingBool("live_notify_enabled")

    @property
    def live_notify_verbose_logging(self):
        return self._addon.getSettingBool("live_notify_verbose_logging")
