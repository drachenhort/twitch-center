"""Twitch Helix API calls. No xbmc* imports - pure Python, pytest-testable."""
import requests

HELIX_BASE = "https://api.twitch.tv/helix"
_MAX_USER_IDS_PER_REQUEST = 100


class TokenExpiredError(Exception):
    """Raised when a Helix call gets HTTP 401 - the access token no longer works.
    Callers decide what to do next (refresh, re-login, etc.) - this module has
    no knowledge of tokens beyond the one it was handed for this call."""


def _headers(access_token, client_id):
    return {"Authorization": "Bearer " + access_token, "Client-Id": client_id}


def _get(url, access_token, client_id, params=None):
    response = requests.get(
        url, headers=_headers(access_token, client_id), params=params, timeout=10
    )
    if response.status_code == 401:
        raise TokenExpiredError()
    response.raise_for_status()
    return response.json()


def get_current_user(access_token, client_id):
    """Return the token owner's Twitch user info: {id, login, display_name}."""
    body = _get(HELIX_BASE + "/users", access_token, client_id)
    user = body["data"][0]
    return {"id": user["id"], "login": user["login"], "display_name": user["display_name"]}


def get_followed_channels(access_token, client_id, user_id):
    """Return the user's followed channels as a list of dicts (Helix
    /channels/followed), each with at least broadcaster_id, broadcaster_login,
    broadcaster_name. Follows Twitch's pagination cursor to completion."""
    channels = []
    cursor = None
    while True:
        params = {"user_id": user_id, "first": 100}
        if cursor:
            params["after"] = cursor
        body = _get(HELIX_BASE + "/channels/followed", access_token, client_id, params=params)
        channels.extend(body["data"])
        cursor = body.get("pagination", {}).get("cursor")
        if not cursor:
            break
    return channels


def get_live_status(access_token, client_id, user_ids):
    """Return live-stream info (Helix /streams) for the given broadcaster user_ids -
    only entries for currently-live channels are returned. Twitch caps this endpoint
    at 100 user_id params per request, so user_ids is split into chunks of 100 and
    the results concatenated."""
    if not user_ids:
        return []
    results = []
    for i in range(0, len(user_ids), _MAX_USER_IDS_PER_REQUEST):
        chunk = user_ids[i : i + _MAX_USER_IDS_PER_REQUEST]
        params = [("first", 100)] + [("user_id", uid) for uid in chunk]
        body = _get(HELIX_BASE + "/streams", access_token, client_id, params=params)
        results.extend(body["data"])
    return results


def get_games_for_channels(access_token, user_ids):
    """Return a dict mapping user_id -> game_id for the given broadcaster user_ids,
    derived from their current/most recent live stream."""
    raise NotImplementedError


def get_top_games(access_token, client_id, first=20):
    """Return Twitch's current top-viewed games (Helix /games/top) as a list of
    {"id", "name"} dicts."""
    body = _get(HELIX_BASE + "/games/top", access_token, client_id, params={"first": first})
    return [{"id": game["id"], "name": game["name"]} for game in body["data"]]


def get_live_streams_by_game(access_token, client_id, game_id, first=20):
    """Return currently-live streams (Helix /streams?game_id=) for the given game_id -
    any streamer, not just followed channels."""
    body = _get(
        HELIX_BASE + "/streams",
        access_token,
        client_id,
        params={"game_id": game_id, "first": first},
    )
    return body["data"]


def search_channels(access_token, client_id, query, live_only=True, first=20):
    """Free-text channel search (Helix /search/channels) for the given query string.
    Defaults to only currently-live channels - this app is about finding something
    to watch now, not a general channel directory."""
    body = _get(
        HELIX_BASE + "/search/channels",
        access_token,
        client_id,
        params={"query": query, "live_only": live_only, "first": first},
    )
    return body["data"]
