"""Cross-platform dispatch layer: normalizes lib.twitch and lib.kick results
into one common shape (see the plan's Global Constraints for the exact dict
shape) so views merge/render/dispatch on channels without branching on
platform. No xbmc* imports - Kodi access happens only through the `addon`
parameter callers pass in, same discipline as lib/settings.py."""
import json

from lib.kick import auth as kick_auth
from lib.kick import stream as kick_stream
from lib.kick.api import get_live_streams as _kick_get_live_streams
from lib.kick.api import get_top_categories as _kick_get_top_categories
from lib.kick.api import get_unofficial_channel as _kick_get_unofficial_channel
from lib.kick.api import search_categories as _kick_search_categories
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


def _normalize_unofficial_kick_channel(channel):
    """Convert one lib.kick.api.get_unofficial_channel() response into the
    shared normalized dict. This is the public, unauthenticated
    kick.com/api/v2/channels/{slug} endpoint - see kick_stream.resolve_stream_url's
    docstring. Field names beyond id/slug/livestream.is_live are unconfirmed
    against a real response - every read here uses .get() with a safe
    default so a wrong guess degrades gracefully instead of raising."""
    livestream = channel.get("livestream") or {}
    categories = livestream.get("categories") or []
    category_name = categories[0].get("name", "") if categories else ""
    thumbnail = livestream.get("thumbnail") or {}
    slug = channel.get("slug", "")
    return {
        "platform": "kick",
        "id": str(channel.get("id", "")),
        "login": slug,
        "display_name": slug,
        "is_live": bool(livestream.get("is_live", False)),
        "viewer_count": livestream.get("viewer_count", 0),
        "game_name": category_name,
        "thumbnail_url": thumbnail.get("url", ""),
    }


def get_kick_live_favorites(addon, get_unofficial_channel_fn=None):
    """Return normalized, LIVE-only entries for every favorited Kick channel.
    Uses the public, unauthenticated unofficial channel endpoint - no Kick
    login required, same as playback (see resolve_stream_url). Never raises;
    a favorite whose lookup itself raises (network error, deleted channel,
    etc.) is skipped rather than failing the whole list, so one bad favorite
    can't blank the screen."""
    if get_unofficial_channel_fn is None:
        get_unofficial_channel_fn = _kick_get_unofficial_channel
    results = []
    for slug in get_kick_favorites(addon):
        try:
            channel = get_unofficial_channel_fn(slug)
        except Exception:
            continue
        if channel is None:
            continue
        normalized = _normalize_unofficial_kick_channel(channel)
        if normalized["is_live"]:
            results.append(normalized)
    return results


def _kick_app_access_token(addon):
    """Return an App Access Token (client_credentials grant) for the
    addon's configured Kick app, or None if kick_client_id/kick_client_secret
    aren't set or the token request fails. No user login involved - Kick's
    read-only browsing endpoints (categories, livestreams) only need
    "publicly available data" per docs.kick.com, which App Access Tokens can
    reach."""
    client_id = addon.getSetting("kick_client_id")
    client_secret = addon.getSetting("kick_client_secret")
    return kick_auth.get_app_access_token(client_id, client_secret)


def get_kick_top_categories(addon, get_top_categories_fn=None):
    """Return Kick's categories, or [] if no kick_client_id/kick_client_secret
    are configured or the call fails - never raises. Used to populate
    Discover's Kick categories row, which simply doesn't appear (via an
    empty row) rather than erroring when Kick app credentials aren't set.

    Uses GET /public/v2/categories (confirmed live 2026-08-23 - no search
    query required, unlike the deprecated v1 endpoint this replaced)."""
    if get_top_categories_fn is None:
        get_top_categories_fn = _kick_get_top_categories
    access_token = _kick_app_access_token(addon)
    if access_token is None:
        return []
    try:
        return get_top_categories_fn(access_token)
    except Exception:
        return []


def search_kick_categories(addon, query, search_categories_fn=None):
    """Return Kick categories matching `query` by name, or [] if no Kick app
    credentials are configured or the call fails - never raises. Mirrors
    get_kick_top_categories's silent-empty contract; Discover's search
    treats an empty result the same as "nothing found", not an error."""
    if search_categories_fn is None:
        search_categories_fn = _kick_search_categories
    access_token = _kick_app_access_token(addon)
    if access_token is None:
        return []
    try:
        return search_categories_fn(access_token, query)
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
    """Return normalized live streams for one Kick category, or [] if no
    Kick app credentials are configured or the call fails - never raises."""
    if get_live_streams_fn is None:
        get_live_streams_fn = _kick_get_live_streams
    access_token = _kick_app_access_token(addon)
    if access_token is None:
        return []
    try:
        entries = get_live_streams_fn(access_token, category_id=category_id)
    except Exception:
        return []
    return [_normalize_kick_live_stream_entry(entry) for entry in entries]


def merge_by_viewer_count(*lists):
    """Combine any number of normalized-dict lists into one, sorted by
    viewer_count descending. Used to interleave Twitch and Kick results
    (Live Streams, category browsing) without either view knowing the
    other platform exists."""
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
    underlying per-platform exception - on any failure (unlike listing, an
    explicit play action needs a definite error, not a silent empty
    result)."""
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
        # No token needed: kick_stream.resolve_stream_url uses the
        # unofficial, unauthenticated kick.com/api/v2/channels/{slug}
        # endpoint - see its docstring. Kick playback never required login.
        try:
            return kick_stream.resolve_stream_url(None, identifier)
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


def resolve_vod_url(addon, vod_id):
    """Resolve a Twitch VOD id to a playable HLS URL. Raises StreamUnavailableError -
    never the underlying twitch_stream exception - on any failure, matching
    resolve_stream_url's contract."""
    website_token = addon.getSetting("website_token")
    try:
        return twitch_stream.resolve_vod_url(vod_id, website_token)
    except twitch_stream.StreamUnavailableError as exc:
        raise StreamUnavailableError(str(exc)) from exc
    except Exception as exc:
        # twitch_stream.resolve_vod_url can also let requests exceptions
        # (HTTPError, RequestException, ...) propagate on a network failure,
        # none of which is twitch_stream.StreamUnavailableError. Catch those
        # too so this function never lets a raw underlying exception escape,
        # matching resolve_stream_url's precedent above.
        raise StreamUnavailableError(str(exc)) from exc


def resolve_clip_url(addon, clip_id):
    """Resolve a Twitch clip id to its playable direct MP4 URL. Raises
    StreamUnavailableError - never the underlying twitch_stream exception - on any
    failure, matching resolve_stream_url's contract."""
    website_token = addon.getSetting("website_token")
    try:
        return twitch_stream.resolve_clip_url(clip_id, website_token)
    except twitch_stream.StreamUnavailableError as exc:
        raise StreamUnavailableError(str(exc)) from exc
    except Exception as exc:
        raise StreamUnavailableError(str(exc)) from exc
