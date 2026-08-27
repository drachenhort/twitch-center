"""Twitch Helix API calls. No xbmc* imports - pure Python, pytest-testable."""
import requests

HELIX_BASE = "https://api.twitch.tv/helix"
_MAX_USER_IDS_PER_REQUEST = 100


class TokenExpiredError(Exception):
    """Raised when a Helix call gets HTTP 401 - the access token no longer works.
    Callers decide what to do next (refresh, re-login, etc.) - this module has
    no knowledge of tokens beyond the one it was handed for this call."""


class _RateLimitedResult(dict):
    """A JSON response body that also carries the response's Ratelimit-* headers (see
    https://dev.twitch.tv/docs/api/guide/#rate-limits). Behaves as a plain dict for callers
    that only care about the body - LiveNotifyClient additionally reads .headers to throttle
    proactively, before its subscribe-call bucket empties, instead of only reacting after a
    429 (live-tested: reacting only on failure still let most of a cold-start 140-channel
    subscribe burst fail, because the burst outran the bucket before any 429 triggered
    backoff)."""

    def __init__(self, data, headers):
        super().__init__(data)
        self.headers = headers


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


def get_videos(access_token, client_id, user_id, first=20):
    """Return the given broadcaster's VODs (Helix /videos, type=archive), newest first.
    sort=time is Helix's own default - passed explicitly so this doesn't silently change
    if Twitch ever changes that default."""
    body = _get(
        HELIX_BASE + "/videos",
        access_token, client_id,
        params={"user_id": user_id, "type": "archive", "sort": "time", "first": first},
    )
    return body["data"]


def get_clips(access_token, client_id, broadcaster_id, first=20):
    """Return the given broadcaster's Clips (Helix /clips), sorted newest first.
    Twitch's Clips endpoint does NOT guarantee chronological order in its response (it's
    view-count-biased) - re-sort client-side by created_at before returning."""
    body = _get(
        HELIX_BASE + "/clips",
        access_token, client_id,
        params={"broadcaster_id": broadcaster_id, "first": first},
    )
    return sorted(body["data"], key=lambda clip: clip["created_at"], reverse=True)


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


def search_categories(access_token, client_id, query, first=20):
    """Free-text game/category search (Helix /search/categories) for the given
    query string. Returns a list of {"id", "name"} dicts, best match first (as
    ordered by Twitch)."""
    body = _get(
        HELIX_BASE + "/search/categories",
        access_token,
        client_id,
        params={"query": query, "first": first},
    )
    return [{"id": game["id"], "name": game["name"]} for game in body["data"]]


def search_channels(access_token, client_id, query, live_only=True, first=20):
    """Free-text channel search (Helix /search/channels) for the given query string.
    Defaults to only currently-live channels - this app is about finding something
    to watch now, not a general channel directory."""
    body = _get(
        HELIX_BASE + "/search/channels",
        access_token,
        client_id,
        # Serialise the bool ourselves: requests would render a bare Python
        # True/False as the literal "True"/"False", which Helix rejects - it
        # wants lowercase true/false.
        params={
            "query": query,
            "live_only": "true" if live_only else "false",
            "first": first,
        },
    )
    return body["data"]


def get_user_by_login(access_token, client_id, login):
    """Return {"id", "login", "display_name"} for the given login name, or None if no such user -
    Twitch returns an empty data list rather than a 404 for an unknown login."""
    body = _get(HELIX_BASE + "/users", access_token, client_id, params={"login": login})
    users = body["data"]
    if not users:
        return None
    user = users[0]
    return {"id": user["id"], "login": user["login"], "display_name": user["display_name"]}


def create_eventsub_subscription(access_token, client_id, session_id, sub_type, condition, version="1"):
    """POST /helix/eventsub/subscriptions with transport {method: websocket, session_id}. Raises
    requests.HTTPError on failure - unlike this module's other best-effort-on-decoration functions,
    a failed chat subscription isn't decoration, so the caller (eventsub.ChatClient._run) needs to
    see the failure and go through its own backoff-retry path rather than getting an empty/None
    result it can't distinguish from "no subscription needed"."""
    response = requests.post(
        HELIX_BASE + "/eventsub/subscriptions",
        headers=_headers(access_token, client_id),
        json={
            "type": sub_type,
            "version": version,
            "condition": condition,
            "transport": {"method": "websocket", "session_id": session_id},
        },
        timeout=10,
    )
    response.raise_for_status()
    return _RateLimitedResult(response.json(), response.headers)


def delete_eventsub_subscription(access_token, client_id, subscription_id):
    """DELETE /helix/eventsub/subscriptions?id=... Raises requests.HTTPError on failure - same
    reasoning as create_eventsub_subscription: a caller relying on this to actually remove a
    stale subscription needs to see a failure, not a silently-ignored one."""
    response = requests.delete(
        HELIX_BASE + "/eventsub/subscriptions",
        headers=_headers(access_token, client_id),
        params={"id": subscription_id},
        timeout=10,
    )
    response.raise_for_status()
    return None
