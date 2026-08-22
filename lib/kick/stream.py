"""Resolves a Kick channel slug to a playable HLS URL. No xbmc* imports -
pure Python, pytest-testable."""
from lib.kick import api


class StreamUnavailableError(Exception):
    """Raised when a channel's stream can't be resolved to a playable URL -
    the channel isn't live, doesn't exist, or the API response is missing
    the playback URL."""


# UNVERIFIED: this function assumes the official Public API's GET
# /public/v1/channels response embeds the playback URL inline at
# channel["stream"]["url"]. That assumption has not been confirmed against
# the real official API, and it directly conflicts with this repo's own
# research in docs/kick-integration-notes.md (section 2, "Playback URL
# (HLS/m3u8)"), which found that the official API does NOT expose a
# playback URL and that the community workaround is the unofficial
# GET https://kick.com/api/v2/channels/{slug} endpoint (SEARCH_BASE +
# "/channels/" + slug, same host already used by api.search_channels),
# whose response carries the URL under "playback_url" (not "stream.url").
# If channel["stream"]["url"] turns out to be missing/absent in practice,
# fall back to that unofficial endpoint's "playback_url" field instead.
# This must be confirmed/fixed before sub-project 4 (playback wiring).
def resolve_stream_url(access_token, channel_slug):
    """Return the direct HLS (.m3u8) URL for the given live channel slug.
    Unlike Twitch, Kick's channel API response includes the playback URL
    directly - no separate signed-access-token exchange needed. Raises
    StreamUnavailableError if the channel doesn't exist, isn't live, or the
    response is missing the URL field."""
    channel = api.get_channel(access_token, channel_slug)
    if channel is None:
        raise StreamUnavailableError(channel_slug)
    stream_info = channel.get("stream") or {}
    if not stream_info.get("is_live"):
        raise StreamUnavailableError(channel_slug)
    url = stream_info.get("url")
    if not url:
        raise StreamUnavailableError(channel_slug)
    return url
