"""Kick Public API calls. No xbmc* imports - pure Python, pytest-testable."""
import requests

API_BASE = "https://api.kick.com/public/v1"


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
    """Return Kick's current top categories as a list of {"id", "name"} dicts."""
    body = _get(API_BASE + "/categories", access_token, params={"limit": first})
    return [{"id": category["id"], "name": category["name"]} for category in body["data"][:first]]


def get_user_by_login(access_token, slug):
    """Return {"id", "login", "display_name"} for the given channel slug, or
    None if no such user."""
    body = _get(API_BASE + "/channels", access_token, params={"slug": slug})
    channels = body["data"]
    if not channels:
        return None
    user = channels[0]
    return {"id": str(user["user_id"]), "login": slug, "display_name": user.get("name", slug)}
