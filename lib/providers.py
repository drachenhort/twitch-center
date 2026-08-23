"""Cross-platform dispatch layer: normalizes lib.twitch and lib.kick results
into one common shape (see the plan's Global Constraints for the exact dict
shape) so views merge/render/dispatch on channels without branching on
platform. No xbmc* imports - Kodi access happens only through the `addon`
parameter callers pass in, same discipline as lib/settings.py."""
import json

from lib.kick import auth as kick_auth
from lib.kick import stream as kick_stream
from lib.kick.api import get_channel as _kick_get_channel
from lib.kick.api import get_live_streams as _kick_get_live_streams
from lib.kick.api import get_top_categories as _kick_get_top_categories
from lib.twitch import stream as twitch_stream


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
    category = channel.get("category") or {}
    slug = channel.get("slug", "")
    return {
        "platform": "kick",
        "id": str(channel.get("broadcaster_user_id", "")),
        "login": slug,
        "display_name": slug,
        "is_live": bool(stream_info.get("is_live", False)),
        "viewer_count": stream_info.get("viewer_count", 0),
        "game_name": category.get("name", ""),
        "thumbnail_url": stream_info.get("thumbnail", ""),
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
    """Return Kick's categories, or [] if there's no saved Kick token or the
    call fails - never raises. Used to populate Discover's Kick categories
    row, which simply doesn't appear (via an empty row) rather than erroring
    when the user isn't logged into Kick.

    Uses GET /public/v2/categories (confirmed live 2026-08-23 - no search
    query required, unlike the deprecated v1 endpoint this replaced)."""
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
    slug = entry.get("slug", "")
    return {
        "platform": "kick",
        "id": str(entry.get("broadcaster_user_id", "")),
        "login": slug,
        "display_name": slug,
        "is_live": True,
        "viewer_count": entry.get("viewer_count", 0),
        "game_name": category.get("name", ""),
        "thumbnail_url": entry.get("thumbnail", ""),
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


def normalize_twitch_search_result(item):
    """Convert one raw dict from lib.twitch.gql.search() - which returns a
    mix of Twitch's search/channels shape (broadcaster_login, display_name,
    is_live, no viewer_count) and search/streams shape (user_login,
    user_name, viewer_count, always live) - into the shared normalized dict.
    Mirrors the .get() fallback chain lib/views/search_view.py's
    _render_results/play_selected already use for display/login, extended to
    the full normalized shape."""
    display_name = item.get("display_name") or item.get("user_name") or "Unknown"
    login = item.get("broadcaster_login") or item.get("user_login") or item.get("login") or ""
    viewer_count = item.get("viewer_count", 0)
    return {
        "platform": "twitch",
        "id": item.get("id") or item.get("user_id") or "",
        "login": login,
        "display_name": display_name,
        "is_live": bool(item.get("is_live", False)) or "viewer_count" in item,
        "viewer_count": viewer_count,
        "game_name": item.get("game_name", ""),
        "thumbnail_url": _twitch_thumbnail_url(item["thumbnail_url"]) if item.get("thumbnail_url") else "",
    }


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


class StreamUnavailableError(Exception):
    """Raised when a channel (either platform) can't be resolved to a
    playable URL - wraps lib.twitch.stream.StreamUnavailableError and
    lib.kick.stream.StreamUnavailableError so callers catch one exception
    type regardless of platform."""


def resolve_stream_url(addon, platform, identifier):
    """Resolve `identifier` (a Twitch login or Kick slug) to a playable HLS
    URL for the given platform. Raises StreamUnavailableError - never the
    underlying per-platform exception - on any failure, including "not
    logged into Kick" (unlike listing, an explicit play action needs a
    definite error, not a silent empty result)."""
    if platform == "twitch":
        website_token = addon.getSetting("website_token")
        try:
            return twitch_stream.resolve_stream_url(identifier, website_token)
        except twitch_stream.StreamUnavailableError as exc:
            raise StreamUnavailableError(str(exc)) from exc
        except Exception as exc:
            # twitch_stream.resolve_stream_url can also let requests exceptions
            # (HTTPError, RequestException, ...) propagate on a network failure,
            # none of which is twitch_stream.StreamUnavailableError. Catch those
            # too so this function never lets a raw per-platform/library
            # exception escape, matching its documented contract - mirrors the
            # Kick branch below.
            raise StreamUnavailableError(str(exc)) from exc
    if platform == "kick":
        token = kick_auth.load_token(addon)
        if token is None:
            raise StreamUnavailableError("not logged into Kick")
        try:
            return kick_stream.resolve_stream_url(token["access_token"], identifier)
        except kick_stream.StreamUnavailableError as exc:
            raise StreamUnavailableError(str(exc)) from exc
        except Exception as exc:
            # kick_stream.resolve_stream_url's call chain (lib.kick.api.get_channel
            # -> lib.kick.api._get) can also raise TokenExpiredError or let
            # requests exceptions (HTTPError, RequestException, ...) propagate on
            # an expired token, HTTP error, or network failure - none of which is
            # kick_stream.StreamUnavailableError. Catch those too so this function
            # never lets a raw per-platform/library exception escape, matching its
            # documented contract.
            raise StreamUnavailableError(str(exc)) from exc
    raise StreamUnavailableError("unknown platform: " + repr(platform))
