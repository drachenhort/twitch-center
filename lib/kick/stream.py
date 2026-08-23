"""Resolves a Kick channel slug to a playable HLS URL. No xbmc* imports -
pure Python, pytest-testable."""
from lib.kick import api


class StreamUnavailableError(Exception):
    """Raised when a channel's stream can't be resolved to a playable URL -
    the channel isn't live, doesn't exist, or the API response is missing
    the playback URL."""


def resolve_stream_url(access_token, channel_slug):
    """Return the direct HLS (.m3u8) URL for the given live channel slug.

    Confirmed live 2026-08-23: the official Public API's GET /channels
    response always has stream.url as an empty string, even for a real live
    channel - it doesn't expose a playback URL at all despite the key
    existing (this used to be an unverified assumption in this function;
    see git history). Uses the unofficial kick.com/api/v2/channels/{slug}
    endpoint instead, whose response carries the URL under "playback_url".
    That endpoint is public/unauthenticated - access_token is unused here,
    kept only so this function's signature (and the "must be logged into
    Kick to play" gate in lib/providers.py, which is about the addon's own
    design, not this endpoint's requirements) doesn't change.

    Raises StreamUnavailableError if the channel doesn't exist, isn't live,
    or the response is missing the URL field."""
    channel = api.get_unofficial_channel(channel_slug)
    if channel is None:
        raise StreamUnavailableError(channel_slug)
    livestream = channel.get("livestream") or {}
    if not livestream.get("is_live"):
        raise StreamUnavailableError(channel_slug)
    url = channel.get("playback_url")
    if not url:
        raise StreamUnavailableError(channel_slug)
    return url
