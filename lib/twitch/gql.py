"""Twitch's unofficial internal GraphQL API. No xbmc* imports - pure Python.

Unofficial/undocumented - same risk tier as lib/twitch/stream.py's playback
resolution: uses Twitch's public web client ID, not our registered Helix
client_id, and can break without notice if Twitch changes its persisted-query
hash or response shape. Every function here is best-effort: failures return
an empty result rather than raising, since this data is decoration
(a filter convenience) on top of the official-Helix-backed channel list, not
something the rest of Home should ever fail over."""
import requests

from lib.twitch import api

GQL_URL = "https://gql.twitch.tv/gql"
WEB_CLIENT_ID = "kimne78kx3ncx6brgo4mv6wki5h1ko"

_FOLLOWING_GAMES_QUERY_HASH = "f3c5d45175d623ed3d5ff4ca4c7de379ea6a1a4852236087dc1b81b7dbfd3114"
_PLAYBACK_ACCESS_TOKEN_QUERY_HASH = "ed230aa1e33e07eebb8928504583da78a5173989fadfb1ac94be06a04f3cdbe9"


def get_followed_live_games(access_token, limit=100):
    """Return the user's followed games that currently have live viewers, as
    a list of {"id", "name", "displayName"} dicts. Best-effort: returns []
    on any failure (network error, non-200, unexpected response shape) -
    never raises. The response field names here are inferred from Twitch's
    typical GraphQL naming conventions and have not been independently
    confirmed against a real captured response (the request shape - operation
    name, persisted-query hash, variables - was captured directly from
    Twitch's own web client; the response shape was not, per
    docs/superpowers/specs/2026-08-11-followed-games-filter-design.md's
    "Known limitation" section). Defensive parsing means a wrong guess about
    field names degrades to an empty list rather than crashing."""
    try:
        response = requests.post(
            GQL_URL,
            json=[
                {
                    "operationName": "FollowingGames_CurrentUser",
                    "variables": {"limit": limit, "type": "LIVE"},
                    "extensions": {
                        "persistedQuery": {
                            "version": 1,
                            "sha256Hash": _FOLLOWING_GAMES_QUERY_HASH,
                        }
                    },
                }
            ],
            headers={
                "Client-Id": WEB_CLIENT_ID,
                "Authorization": "OAuth " + access_token,
            },
            timeout=10,
        )
    except requests.RequestException:
        return []

    if response.status_code != 200:
        return []

    try:
        body = response.json()
        nodes = body[0]["data"]["currentUser"]["followedGames"]["nodes"]
    except (ValueError, KeyError, IndexError, TypeError):
        return []

    games = []
    for node in nodes:
        if not isinstance(node, dict):
            continue
        display_name = node.get("displayName") or node.get("name")
        if not display_name:
            continue
        games.append(
            {"id": node.get("id", ""), "name": node.get("name", ""), "displayName": display_name}
        )
    return games


def get_playback_access_token(access_token, channel_login):
    """Return a {"value", "signature"} playback access token for the given
    live channel login, or None on any non-401 failure (network error,
    non-200, unexpected response shape) - never raises for those. Raises
    api.TokenExpiredError on HTTP 401, unlike get_followed_live_games's pure
    best-effort convention: playback is not decoration, so an expired token
    here must be distinguishable from genuine unavailability, to let the
    caller retry after a refresh rather than just failing silently.

    "value" is an opaque JSON string Twitch issues - never parse it, just
    pass it through unchanged to usher.ttvnw.net."""
    try:
        response = requests.post(
            GQL_URL,
            json={
                "operationName": "PlaybackAccessToken",
                "variables": {
                    "isLive": True,
                    "login": channel_login,
                    "isVod": False,
                    "vodID": "",
                    "playerType": "site",
                    "platform": "web",
                },
                "extensions": {
                    "persistedQuery": {
                        "version": 1,
                        "sha256Hash": _PLAYBACK_ACCESS_TOKEN_QUERY_HASH,
                    }
                },
            },
            headers={
                "Client-Id": WEB_CLIENT_ID,
                "Authorization": "OAuth " + access_token,
            },
            timeout=10,
        )
    except requests.RequestException:
        return None

    if response.status_code == 401:
        raise api.TokenExpiredError()
    if response.status_code != 200:
        return None

    try:
        body = response.json()
        token = body["data"]["streamPlaybackAccessToken"]
        value = token["value"]
        signature = token["signature"]
    except (ValueError, KeyError, TypeError):
        return None

    if not value or not signature:
        return None

    return {"value": value, "signature": signature}
