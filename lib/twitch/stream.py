"""Resolves a Twitch channel name to a playable HLS URL via Twitch's GraphQL +
usher.ttvnw.net access-token endpoints. No xbmc* imports - pure Python, pytest-testable."""
from urllib.parse import quote

from lib.twitch import gql

USHER_BASE = "https://usher.ttvnw.net"


class StreamUnavailableError(Exception):
    """Raised when a channel's stream can't be resolved to a playable URL -
    the channel isn't live, Twitch denied access, or the underlying request
    failed for a non-401 reason. api.TokenExpiredError (a 401) is NOT wrapped
    here - it propagates unchanged so the caller can refresh and retry rather
    than treating an expired token the same as "this stream doesn't exist"."""


def resolve_stream_url(access_token, channel_login):
    """Return a direct HLS (.m3u8) URL Kodi's player can open for the given
    live channel login. Raises StreamUnavailableError if it can't be
    resolved; raises api.TokenExpiredError (via gql.get_playback_access_token)
    if the access token has expired."""
    token = gql.get_playback_access_token(access_token, channel_login)
    if token is None:
        raise StreamUnavailableError(channel_login)
    return (
        USHER_BASE
        + "/api/channel/hls/"
        + channel_login
        + ".m3u8"
        + "?token="
        + quote(token["value"], safe="")
        + "&sig="
        + token["signature"]
        + "&allow_source=true&fast_bread=true&player_backend=mediaplayer"
    )
