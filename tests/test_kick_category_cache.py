"""Exercises the real cache_path/save/load functions (not injected fakes) so a
wrong Kodi API name here - e.g. xbmc.translatePath, which was removed in Kodi
21 and broke every live Kick category search silently - gets caught by CI
instead of only ever surfacing live."""
import xbmcaddon

from lib import kick_category_cache


def _addon_with_profile(tmp_path):
    addon = xbmcaddon.Addon()
    addon._info["profile"] = str(tmp_path) + "/"
    return addon


def test_load_returns_none_when_cache_file_missing(tmp_path):
    addon = _addon_with_profile(tmp_path)
    assert kick_category_cache.load(addon) is None


def test_save_then_load_round_trips_categories(tmp_path):
    addon = _addon_with_profile(tmp_path)
    categories = [{"id": 166, "name": "EVE Online"}]
    kick_category_cache.save(addon, categories)
    assert kick_category_cache.load(addon) == categories
