"""Local cache of Kick's full category catalog (~19k entries), used to support
client-side substring search over category names.

Kick's own /public/v2/categories `name` filter (lib.kick.api.search_categories)
only prefix-matches - querying "online" won't find "EVE Online" since "online"
is never a prefix of that name. There's no server-side way to search by an
arbitrary substring, so the only fix is to pull the whole catalog once and
filter it locally (see lib.providers.search_kick_categories).

Stored as a JSON file in the addon's profile directory rather than via
addon.setSetting/getSetting (as lib.kick.auth does for tokens) - a ~19k-row
catalog is far too big for settings.xml storage. This is the only lib/kick*
module that imports xbmc directly (translatePath is unavoidable to resolve a
real filesystem path), same exception lib/keymap_installer.py makes."""
import json
import os

import xbmc

CACHE_FILENAME = "kick_categories_cache.json"


def cache_path(addon):
    profile_path = xbmc.translatePath(addon.getAddonInfo("profile"))
    return os.path.join(profile_path, CACHE_FILENAME)


def load(addon):
    """Return the cached category list, or None if it hasn't been built yet
    or the file is missing/corrupt (treated the same as "not built yet")."""
    try:
        with open(cache_path(addon)) as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def save(addon, categories):
    path = cache_path(addon)
    directory = os.path.dirname(path)
    if directory and not os.path.isdir(directory):
        os.makedirs(directory)
    with open(path, "w") as f:
        json.dump(categories, f)
