import xbmcaddon

from lib.settings import Settings


def test_chat_display_mode_defaults_to_both():
    settings = Settings()
    assert settings.chat_display_mode == "both"


def test_chat_display_mode_reads_addon_setting():
    addon = xbmcaddon.Addon()
    addon.setSetting("chat_display_mode", "overlay")
    settings = Settings(addon=addon)
    assert settings.chat_display_mode == "overlay"
