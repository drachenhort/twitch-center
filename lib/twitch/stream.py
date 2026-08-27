"""Resolves a Twitch channel name to a playable HLS URL via Twitch's GraphQL +
usher.ttvnw.net access-token endpoints. No xbmc* imports - pure Python, pytest-testable."""
import random
import re
from urllib.parse import quote

from lib.twitch import gql

USHER_BASE = "https://usher.ttvnw.net"
_CLIP_PREVIEW_SUFFIX_RE = re.compile(r"-preview-\d+x\d+\.jpg$")


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
        + "&allow_source=true&allow_audio_only=true&fast_bread=true&player_backend=mediaplayer"
        + "&acmb=e30="
        + "&p="
        + str(random.randint(1, 999999))
    )


def resolve_vod_url(vod_id, website_token=None):
    """Return a direct HLS (.m3u8) URL for the given VOD id. Raises
    StreamUnavailableError if it can't be resolved."""
    token = gql.get_vod_playback_access_token(vod_id, website_token)
    if token is None:
        raise StreamUnavailableError(vod_id)
    return (
        USHER_BASE
        + "/vod/"
        + vod_id
        + ".m3u8"
        + "?token="
        + quote(token["value"], safe="")
        + "&sig="
        + token["signature"]
    )


def resolve_clip_url(thumbnail_url):
    """Derive a clip's direct MP4 URL from its Helix thumbnail_url (e.g.
    ".../AB12CD34-preview-480x272.jpg" -> ".../AB12CD34.mp4"). Raises
    StreamUnavailableError if thumbnail_url doesn't match that pattern - a well-known,
    deterministic technique (no GQL/auth needed), but dependent on Twitch's thumbnail
    naming convention not changing."""
    if not _CLIP_PREVIEW_SUFFIX_RE.search(thumbnail_url):
        raise StreamUnavailableError(thumbnail_url)
    return _CLIP_PREVIEW_SUFFIX_RE.sub(".mp4", thumbnail_url)
