"""Minimal stand-in for Kodi's built-in xbmcaddon module, for pytest-only use."""

_ADDON_INFO = {
    "id": "script.twitch.center",
    "name": "Twitch Center",
    "version": "0.1.0",
}


class Addon:
    def __init__(self, id=None):
        self._settings = {}

    def getSetting(self, id):
        return self._settings.get(id, "")

    def getSettingBool(self, id):
        return bool(self._settings.get(id, False))

    def setSetting(self, id, value):
        self._settings[id] = value

    def getAddonInfo(self, key):
        return _ADDON_INFO.get(key, "")
