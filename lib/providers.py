"""Cross-platform dispatch layer: normalizes lib.twitch and lib.kick results
into one common shape (see the plan's Global Constraints for the exact dict
shape) so views merge/render/dispatch on channels without branching on
platform. No xbmc* imports - Kodi access happens only through the `addon`
parameter callers pass in, same discipline as lib/settings.py."""
import json

from lib.kick import auth as kick_auth
from lib.kick.api import get_channel as _kick_get_channel
from lib.kick.api import get_live_streams as _kick_get_live_streams, get_top_categories as _kick_get_top_categories


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


def _twitch_thumbnail_url(raw_url, width=320, height=180):
    return raw_url.replace("{width}", str(width)).replace("{height}", str(height))


def normalize_twitch_channel(channel, stream_data=None):
    """Convert a (channel, stream_data) pair from lib.twitch.api's followed-
    channels/live-status shape into the shared normalized dict. stream_data
    is None for an offline channel."""
    if stream_data:
        return {
            "platform": "twitch",
            "id": channel["broadcaster_id"],
            "login": channel["broadcaster_login"],
            "display_name": channel["broadcaster_name"],
            "is_live": True,
            "viewer_count": stream_data["viewer_count"],
            "game_name": stream_data["game_name"],
            "thumbnail_url": _twitch_thumbnail_url(stream_data["thumbnail_url"]),
        }
    return {
        "platform": "twitch",
        "id": channel["broadcaster_id"],
        "login": channel["broadcaster_login"],
        "display_name": channel["broadcaster_name"],
        "is_live": False,
        "viewer_count": 0,
        "game_name": "",
        "thumbnail_url": "",
    }


def _normalize_kick_channel(channel):
    """Convert one lib.kick.api.get_channel() response into the shared
    normalized dict. Field names beyond broadcaster_user_id/slug/stream.is_live
    are unconfirmed against a real API response (see this task's note in the
    plan) - every read here uses .get() with a safe default so a wrong guess
    degrades gracefully instead of raising."""
    stream_info = channel.get("stream") or {}
    category = stream_info.get("category") or {}
    thumbnail = stream_info.get("thumbnail") or {}
    slug = channel.get("slug", "")
    return {
        "platform": "kick",
        "id": str(channel.get("broadcaster_user_id", "")),
        "login": slug,
        "display_name": slug,
        "is_live": bool(stream_info.get("is_live", False)),
        "viewer_count": stream_info.get("viewer_count", 0),
        "game_name": category.get("name", ""),
        "thumbnail_url": thumbnail.get("url", ""),
    }


def get_kick_live_favorites(addon, get_channel_fn=None):
    """Return normalized, LIVE-only entries for every favorited Kick channel.
    Silently returns [] if there's no saved Kick token (Kick login is
    optional and independent of Twitch's) - never raises. A favorite whose
    lookup itself raises (network error, deleted channel, etc.) is skipped
    rather than failing the whole list, so one bad favorite can't blank the
    screen."""
    if get_channel_fn is None:
        get_channel_fn = _kick_get_channel
    token = kick_auth.load_token(addon)
    if token is None:
        return []
    results = []
    for slug in get_kick_favorites(addon):
        try:
            channel = get_channel_fn(token["access_token"], slug)
        except Exception:
            continue
        if channel is None:
            continue
        normalized = _normalize_kick_channel(channel)
        if normalized["is_live"]:
            results.append(normalized)
    return results


def get_kick_top_categories(addon, get_top_categories_fn=None):
    """Return Kick's top categories, or [] if there's no saved Kick token or
    the call fails - never raises. Used to populate Discover's Kick
    categories row, which simply doesn't appear (via an empty row) rather
    than erroring when the user isn't logged into Kick."""
    if get_top_categories_fn is None:
        get_top_categories_fn = _kick_get_top_categories
    token = kick_auth.load_token(addon)
    if token is None:
        return []
    try:
        return get_top_categories_fn(token["access_token"])
    except Exception:
        return []


def _normalize_kick_live_stream_entry(entry):
    """Convert one entry from lib.kick.api.get_live_streams() (flat shape,
    NOT nested under "stream" like get_channel()'s response) into the shared
    normalized dict. Every entry from this endpoint is live by definition.
    Field names beyond broadcaster_user_id/slug are unconfirmed (see this
    plan's Task 2 note) - .get() throughout."""
    category = entry.get("category") or {}
    thumbnail = entry.get("thumbnail") or {}
    slug = entry.get("slug", "")
    return {
        "platform": "kick",
        "id": str(entry.get("broadcaster_user_id", "")),
        "login": slug,
        "display_name": slug,
        "is_live": True,
        "viewer_count": entry.get("viewer_count", 0),
        "game_name": category.get("name", ""),
        "thumbnail_url": thumbnail.get("url", ""),
    }


def get_kick_category_streams(addon, category_id, get_live_streams_fn=None):
    """Return normalized live streams for one Kick category, or [] if
    there's no saved Kick token or the call fails - never raises."""
    if get_live_streams_fn is None:
        get_live_streams_fn = _kick_get_live_streams
    token = kick_auth.load_token(addon)
    if token is None:
        return []
    try:
        entries = get_live_streams_fn(token["access_token"], category_id=category_id)
    except Exception:
        return []
    return [_normalize_kick_live_stream_entry(entry) for entry in entries]


def merge_by_viewer_count(*lists):
    """Combine any number of normalized-dict lists into one, sorted by
    viewer_count descending. Used to interleave Twitch and Kick results
    (Live Streams, Search, category browsing) without either view knowing
    the other platform exists."""
    combined = []
    for items in lists:
        combined.extend(items)
    combined.sort(key=lambda item: item["viewer_count"], reverse=True)
    return combined
