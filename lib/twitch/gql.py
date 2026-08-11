"""Twitch's unofficial internal GraphQL API. No xbmc* imports - pure Python.

Unofficial/undocumented - same risk tier as lib/twitch/stream.py's playback
resolution: uses Twitch's public web client ID, not our registered Helix
client_id, and can break without notice if Twitch changes its persisted-query
hash or response shape. Every function here is best-effort: failures return
an empty result rather than raising, since this data is decoration
(a filter convenience) on top of the official-Helix-backed channel list, not
something the rest of Home should ever fail over."""
import requests

GQL_URL = "https://gql.twitch.tv/gql"
WEB_CLIENT_ID = "kimne78kx3ncx6brgo4mv6wki5h1ko"

_FOLLOWING_GAMES_QUERY_HASH = "f3c5d45175d623ed3d5ff4ca4c7de379ea6a1a4852236087dc1b81b7dbfd3114"


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
        return [
            {"id": node["id"], "name": node["name"], "displayName": node["displayName"]}
            for node in nodes
        ]
    except (ValueError, KeyError, IndexError, TypeError):
        return []
