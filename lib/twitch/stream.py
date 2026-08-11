"""Resolves a Twitch channel name to a playable HLS URL via Twitch's GraphQL +
usher.ttvnw.net access-token endpoints. No xbmc* imports - pure Python, pytest-testable."""


def resolve_stream_url(channel_name):
    """Return a direct HLS (.m3u8) URL Kodi's player can open for the given
    live channel name."""
    raise NotImplementedError
