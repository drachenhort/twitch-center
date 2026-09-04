"""Kick Public API calls. No xbmc* imports - pure Python, pytest-testable."""
import requests

API_BASE = "https://api.kick.com/public/v1"
API_BASE_V2 = "https://api.kick.com/public/v2"


class TokenExpiredError(Exception):
    """Raised when a Kick API call gets HTTP 401 - the access token no longer
    works. Callers decide what to do next (refresh, re-login, etc.)."""


def _headers(access_token):
    return {"Authorization": "Bearer " + access_token}


def _get(url, access_token, params=None):
    response = requests.get(url, headers=_headers(access_token), params=params, timeout=10)
    if response.status_code == 401:
        raise TokenExpiredError()
    response.raise_for_status()
    return response.json()


UNOFFICIAL_CHANNEL_URL = "https://kick.com/api/v2/channels/{slug}"


def get_unofficial_channel(channel_slug):
    """Return the unofficial kick.com/api/v2/channels/{slug} response, or
    None if no such channel. No access token needed - this endpoint is
    public and unauthenticated (confirmed live 2026-08-23).

    Only used for `playback_url`: the official Public API's GET /channels
    (see get_channel() above) always returns stream.url as an empty string
    even for a live channel (confirmed live 2026-08-23 against a real
    stream) - it just doesn't expose the HLS URL at all, despite that key
    existing. This unofficial endpoint (used by kick.com's own web client)
    is the only known way to get a real, playable stream URL."""
    response = requests.get(
        UNOFFICIAL_CHANNEL_URL.format(slug=channel_slug),
        headers={"User-Agent": "Mozilla/5.0"},
        timeout=10,
    )
    if response.status_code == 404:
        return None
    response.raise_for_status()
    return response.json()


def get_current_user(access_token):
    """Return the token owner's info as {id, login, display_name}, normalized
    to Twitch's field-naming so downstream code doesn't need to branch on
    platform for basic display."""
    body = _get(API_BASE + "/users", access_token)
    user = body["data"][0]
    return {
        "id": str(user["user_id"]),
        "login": user["name"].lower(),
        "display_name": user["name"],
    }


def get_channel(access_token, slug):
    """Return the channel dict (including live status/stream url under
    "stream") for the given slug, or None if no such channel."""
    body = _get(API_BASE + "/channels", access_token, params={"slug": slug})
    channels = body["data"]
    if not channels:
        return None
    return channels[0]


def get_live_streams(access_token, category_id=None, first=20):
    """Return currently-live streams (GET /livestreams), optionally filtered
    to one category_id."""
    params = {"limit": first}
    if category_id is not None:
        params["category_id"] = category_id
    body = _get(API_BASE + "/livestreams", access_token, params=params)
    return body["data"]


def get_top_categories(access_token, first=20):
    """Return Kick's categories as a list of {"id", "name"} dicts, via
    GET /public/v2/categories (confirmed live 2026-08-23: no search query
    required, unlike the deprecated v1 endpoint - this is a real
    browse-all-categories call, just capped to a page via `limit`)."""
    body = _get(API_BASE_V2 + "/categories", access_token, params={"limit": first})
    return [{"id": category["id"], "name": category["name"]} for category in body["data"]]


def get_all_categories(access_token, page_size=100):
    """Return every Kick category as a list of {"id", "name"} dicts, by
    paging GET /public/v2/categories to exhaustion via its cursor (confirmed
    live: `cursor` is the opaque pagination.next_cursor from the previous
    page; an empty next_cursor means the last page). This is a full ~19k-row
    catalog pull (~190 requests at the max page_size of 100) - callers should
    cache the result rather than calling this per search. Exists because
    Kick's `name` filter (see search_categories) only prefix-matches, so
    finding a category by a word anywhere in its name (e.g. "online" inside
    "EVE Online") requires pulling the whole list and filtering client-side."""
    results = []
    cursor = None
    while True:
        params = {"limit": page_size}
        if cursor:
            params["cursor"] = cursor
        body = _get(API_BASE_V2 + "/categories", access_token, params=params)
        for category in body["data"]:
            results.append({"id": category["id"], "name": category["name"]})
        cursor = body.get("pagination", {}).get("next_cursor")
        if not cursor:
            break
    return results


def search_categories(access_token, query, first=20):
    """Return Kick categories whose name matches `query`, via GET
    /public/v2/categories's `name` filter param (confirmed live 2026-09-04:
    case-insensitive PREFIX match against the category name - "eve" matches
    "EVE Online" because it's a prefix, but "online" does NOT, since "online"
    is never a prefix of "EVE Online". Not a substring match anywhere in the
    name, despite this function's name - see get_all_categories/
    lib.providers for the client-side substring search built on top of that
    limitation). Kick's own category data can list the same name more than
    once under different ids (confirmed live) - deduped here by id, keeping
    first-seen order."""
    body = _get(API_BASE_V2 + "/categories", access_token, params={"name": query, "limit": first})
    seen = set()
    results = []
    for category in body["data"]:
        if category["id"] in seen:
            continue
        seen.add(category["id"])
        results.append({"id": category["id"], "name": category["name"]})
    return results


def get_user_by_login(access_token, slug):
    """Return {"id", "login", "display_name"} for the given channel slug, or
    None if no such user."""
    body = _get(API_BASE + "/channels", access_token, params={"slug": slug})
    channels = body["data"]
    if not channels:
        return None
    user = channels[0]
    return {"id": str(user["broadcaster_user_id"]), "login": slug, "display_name": slug}
