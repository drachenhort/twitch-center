"""Cross-platform dispatch layer: normalizes lib.twitch and lib.kick results
into one common shape (see the plan's Global Constraints for the exact dict
shape) so views merge/render/dispatch on channels without branching on
platform. No xbmc* imports - Kodi access happens only through the `addon`
parameter callers pass in, same discipline as lib/settings.py."""
import json


def get_kick_favorites(addon):
    """Return the list of favorited Kick channel slugs, stored as a JSON
    array in the kick_favorite_channels setting. Malformed/missing/non-list
    JSON all normalize to an empty list rather than raising - this is
    user-editable-adjacent state (built up one add_kick_favorite call at a
    time), not something that should ever crash a screen load."""
    raw = addon.getSetting("kick_favorite_channels")
    if not raw:
        return []
    try:
        favorites = json.loads(raw)
    except ValueError:
        return []
    if not isinstance(favorites, list):
        return []
    return favorites


def add_kick_favorite(addon, slug):
    favorites = get_kick_favorites(addon)
    if slug not in favorites:
        favorites.append(slug)
        addon.setSetting("kick_favorite_channels", json.dumps(favorites))


def remove_kick_favorite(addon, slug):
    favorites = get_kick_favorites(addon)
    if slug in favorites:
        favorites.remove(slug)
        addon.setSetting("kick_favorite_channels", json.dumps(favorites))
