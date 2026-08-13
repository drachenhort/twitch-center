"""Resolves a Twitch channel name to a playable HLS URL via Twitch's GraphQL +
usher.ttvnw.net access-token endpoints. No xbmc* imports - pure Python, pytest-testable."""
import random
from urllib.parse import quote

from lib.twitch import gql

USHER_BASE = "https://usher.ttvnw.net"


class StreamUnavailableError(Exception):
    """Raised when a channel's stream can't be resolved to a playable URL -
    the channel isn't live, Twitch denied access, or the underlying request
    failed."""


def resolve_stream_url(channel_login, website_token=None):
    """Return a direct HLS (.m3u8) URL Kodi's player can open for the given
    live channel login. Raises StreamUnavailableError if it can't be
    resolved. website_token is optional - see
    gql.get_playback_access_token's docstring for what it does and why our
    own Helix access_token can't be used here instead."""
    token = gql.get_playback_access_token(channel_login, website_token)
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
        + "&acmb=e30="
        + "&p="
        + str(random.randint(1, 999999))
    )
