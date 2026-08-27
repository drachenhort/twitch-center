"""Twitch's unofficial internal GraphQL API. No xbmc* imports - pure Python.

Unofficial/undocumented - same risk tier as lib/twitch/stream.py's playback
resolution: uses Twitch's public web client ID, not our registered Helix
client_id, and can break without notice if Twitch changes its persisted-query
hash or response shape. Every function here is best-effort: failures return
an empty result rather than raising, since this data is decoration
(a filter convenience) on top of the official-Helix-backed channel list, not
something the rest of Home should ever fail over.

Every function here takes an optional website_token: gql.twitch.tv rejects
any Authorization token issued to a non-Twitch client_id (verified directly
against the live API - see get_playback_access_token's docstring), so our own
Helix-issued access_token is useless here regardless of which query is being
made. website_token is instead the user's own twitch.tv browser session
token (the "auth-token" cookie, manually copied in by the user via Settings)
- optional everywhere, since every query here also has a working anonymous
fallback (public data only, no subscriber-only perks)."""
import requests

GQL_URL = "https://gql.twitch.tv/gql"
WEB_CLIENT_ID = "kimne78kx3ncx6brgo4mv6wki5h1ko"

_FOLLOWING_GAMES_QUERY_HASH = "f3c5d45175d623ed3d5ff4ca4c7de379ea6a1a4852236087dc1b81b7dbfd3114"
_PLAYBACK_ACCESS_TOKEN_QUERY_HASH = "ed230aa1e33e07eebb8928504583da78a5173989fadfb1ac94be06a04f3cdbe9"


def _headers(website_token=None):
    headers = {"Client-Id": WEB_CLIENT_ID}
    if website_token:
        headers["Authorization"] = "OAuth " + website_token
    return headers


def get_followed_live_games(website_token=None, limit=100):
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
    field names degrades to an empty list rather than crashing.

    This query is inherently user-specific (the *current* user's follows), so
    unlike get_playback_access_token, it has no meaningful anonymous mode -
    without a valid website_token it always returns [] (a 401, same as any
    other non-200 response)."""
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
            headers=_headers(website_token),
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


def get_playback_access_token(channel_login, website_token=None):
    """Return a {"value", "signature"} playback access token for the given
    live channel login, or None on any failure (network error, non-200,
    unexpected response shape) - never raises.

    website_token is optional: our own Helix-issued access_token is USELESS
    here regardless - gql.twitch.tv rejects Authorization tokens issued to
    any client_id it doesn't recognize as one of Twitch's own first-party
    surfaces (verified directly against the live API - a freshly issued,
    Helix-valid user token still got a 401 "Authorization token is invalid"
    here, regardless of which Client-Id header accompanied it; refreshing
    such a token can't fix that rejection). Anonymous requests (no
    website_token) work fine for public live streams - that's this addon's
    default. Passing the user's own twitch.tv website_token additionally
    unlocks ad-free/subscriber-perk playback where the account has it.

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
            headers=_headers(website_token),
            timeout=10,
        )
    except requests.RequestException:
        return None

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


def get_vod_playback_access_token(vod_id, website_token=None):
    """Return a {"value", "signature"} playback access token for the given VOD id, or None
    on any failure - never raises. Same persisted query as get_playback_access_token, with
    isLive/isVod/vodID/login swapped for the VOD case instead of the live case.

    Known limitation: the query variables here (isVod/vodID) are well-documented in
    Twitch's public web client and high-confidence, but this persisted query's response
    shape was captured for the LIVE case (get_playback_access_token) - whether Twitch's
    fixed response selection set for this exact persisted hash includes
    videoPlaybackAccessToken for a VOD request is unconfirmed until live-tested. If it
    doesn't, this returns None the same as any other failure - no crash, VOD playback
    just won't work until this is revisited."""
    try:
        response = requests.post(
            GQL_URL,
            json={
                "operationName": "PlaybackAccessToken",
                "variables": {
                    "isLive": False,
                    "login": "",
                    "isVod": True,
                    "vodID": vod_id,
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
            headers=_headers(website_token),
            timeout=10,
        )
    except requests.RequestException:
        return None

    if response.status_code != 200:
        return None

    try:
        body = response.json()
        token = body["data"]["videoPlaybackAccessToken"]
        value = token["value"]
        signature = token["signature"]
    except (ValueError, KeyError, TypeError):
        return None

    if not value or not signature:
        return None

    return {"value": value, "signature": signature}
