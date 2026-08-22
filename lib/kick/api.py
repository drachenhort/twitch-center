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
