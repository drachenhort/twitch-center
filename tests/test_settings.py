import xbmcaddon

from lib.settings import Settings


def test_chat_overlay_enabled_defaults_to_false():
    settings = Settings()
    assert settings.chat_overlay_enabled is False


def test_chat_overlay_enabled_reads_addon_setting():
    addon = xbmcaddon.Addon()
    addon.setSetting("chat_overlay_enabled", True)
    settings = Settings(addon=addon)
    assert settings.chat_overlay_enabled is True


def test_show_offline_channels_defaults_to_false():
    settings = Settings()
    assert settings.show_offline_channels is False


def test_show_offline_channels_reads_addon_setting():
    addon = xbmcaddon.Addon()
    addon.setSetting("show_offline_channels", True)
    settings = Settings(addon=addon)
    assert settings.show_offline_channels is True


def test_chat_engine_defaults_to_irc():
    settings = Settings()
    assert settings.chat_engine == "irc"


def test_chat_engine_reads_addon_setting():
    addon = xbmcaddon.Addon()
    addon.setSetting("chat_engine", "eventsub")
    settings = Settings(addon=addon)
    assert settings.chat_engine == "eventsub"


def test_chat_engine_falls_back_to_default_on_invalid_value():
    addon = xbmcaddon.Addon()
    addon.setSetting("chat_engine", "not-a-real-engine")
    settings = Settings(addon=addon)
    assert settings.chat_engine == "irc"


def test_chat_overlay_variable_height_defaults_to_false():
    settings = Settings()
    assert settings.chat_overlay_variable_height is False


def test_chat_overlay_variable_height_reads_addon_setting():
    addon = xbmcaddon.Addon()
    addon.setSetting("chat_overlay_variable_height", True)
    settings = Settings(addon=addon)
    assert settings.chat_overlay_variable_height is True
