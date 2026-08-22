import xbmcaddon

from lib import providers


def test_get_kick_favorites_defaults_to_empty_list():
    addon = xbmcaddon.Addon()
    assert providers.get_kick_favorites(addon) == []


def test_get_kick_favorites_returns_empty_list_for_malformed_json():
    addon = xbmcaddon.Addon()
    addon.setSetting("kick_favorite_channels", "not-json")
    assert providers.get_kick_favorites(addon) == []


def test_get_kick_favorites_returns_empty_list_for_non_list_json():
    addon = xbmcaddon.Addon()
    addon.setSetting("kick_favorite_channels", '{"not": "a list"}')
    assert providers.get_kick_favorites(addon) == []


def test_add_kick_favorite_appends_and_persists():
    addon = xbmcaddon.Addon()
    providers.add_kick_favorite(addon, "somechannel")
    assert providers.get_kick_favorites(addon) == ["somechannel"]


def test_add_kick_favorite_is_idempotent():
    addon = xbmcaddon.Addon()
    providers.add_kick_favorite(addon, "somechannel")
    providers.add_kick_favorite(addon, "somechannel")
    assert providers.get_kick_favorites(addon) == ["somechannel"]


def test_remove_kick_favorite_deletes_it():
    addon = xbmcaddon.Addon()
    providers.add_kick_favorite(addon, "somechannel")
    providers.add_kick_favorite(addon, "otherchannel")
    providers.remove_kick_favorite(addon, "somechannel")
    assert providers.get_kick_favorites(addon) == ["otherchannel"]


def test_remove_kick_favorite_is_a_no_op_if_not_present():
    addon = xbmcaddon.Addon()
    providers.add_kick_favorite(addon, "somechannel")
    providers.remove_kick_favorite(addon, "nosuchchannel")
    assert providers.get_kick_favorites(addon) == ["somechannel"]
