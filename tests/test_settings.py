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


def test_follow_raids_enabled_defaults_to_false():
    settings = Settings()
    assert settings.follow_raids_enabled is False


def test_follow_raids_enabled_reads_addon_setting():
    addon = xbmcaddon.Addon()
    addon.setSetting("follow_raids_enabled", True)
    settings = Settings(addon=addon)
    assert settings.follow_raids_enabled is True


def test_skip_twitch_ads_defaults_to_false():
    settings = Settings()
    assert settings.skip_twitch_ads is False


def test_skip_twitch_ads_reads_addon_setting():
    addon = xbmcaddon.Addon()
    addon.setSetting("skip_twitch_ads", True)
    settings = Settings(addon=addon)
    assert settings.skip_twitch_ads is True


def test_kick_client_id_setting_is_readable_and_defaults_empty():
    addon = xbmcaddon.Addon()
    assert addon.getSetting("kick_client_id") == ""
    addon.setSetting("kick_client_id", "my-kick-client-id")
    assert addon.getSetting("kick_client_id") == "my-kick-client-id"


def test_kick_client_secret_setting_is_readable_and_defaults_empty():
    addon = xbmcaddon.Addon()
    assert addon.getSetting("kick_client_secret") == ""
    addon.setSetting("kick_client_secret", "my-kick-client-secret")
    assert addon.getSetting("kick_client_secret") == "my-kick-client-secret"


def test_kick_redirect_port_setting_is_readable():
    addon = xbmcaddon.Addon()
    addon.setSetting("kick_redirect_port", "9000")
    assert addon.getSetting("kick_redirect_port") == "9000"


def test_kick_token_setting_round_trips():
    addon = xbmcaddon.Addon()
    addon.setSetting("kick_token", '{"access_token": "tok"}')
    assert addon.getSetting("kick_token") == '{"access_token": "tok"}'


def test_kick_favorite_channels_setting_round_trips():
    addon = xbmcaddon.Addon()
    addon.setSetting("kick_favorite_channels", '["somechannel"]')
    assert addon.getSetting("kick_favorite_channels") == '["somechannel"]'
