"""Resolves a Twitch channel name to a playable HLS URL via Twitch's GraphQL +
usher.ttvnw.net access-token endpoints. No xbmc* imports - pure Python, pytest-testable."""
import json
import random
from urllib.parse import quote, urlsplit

import requests

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
        + "&allow_source=true&allow_audio_only=true&fast_bread=true&player_backend=mediaplayer"
        + "&acmb=e30="
        + "&p="
        + str(random.randint(1, 999999))
    )


def check_playlist(url, timeout=10):
    """Fetch an HLS master playlist ourselves before Kodi's player gets it, so a failure can be
    shown to the user with its actual cause instead of Kodi's generic "Playback failed" dialog
    (Kodi gives add-ons no way to read why inputstream.adaptive's own fetch failed). Returns None
    if the URL served a playlist, otherwise a short human-readable reason. Never raises."""
    host = urlsplit(url).hostname or url
    try:
        response = requests.get(url, timeout=timeout)
    except requests.exceptions.Timeout:
        return "Twitch video server ({}) didn't answer within {}s.".format(host, timeout)
    except requests.exceptions.RequestException as exc:
        return "Can't reach Twitch video server ({}): {}.".format(host, type(exc).__name__)
    if response.status_code != 200:
        return "Twitch refused the stream (HTTP {}){}.".format(
            response.status_code, _usher_error_suffix(response.text)
        )
    if not response.text.lstrip().startswith("#EXTM3U"):
        return "Twitch video server ({}) sent a response that is not a playlist.".format(host)
    return None


def _usher_error_suffix(body):
    """usher.ttvnw.net error bodies are a JSON list like
    [{"error": "Can not find channel", "error_code": "...", ...}] - return ": <error>" from it,
    or "" if the body isn't that shape."""
    try:
        errors = json.loads(body)
        message = errors[0]["error"]
    except (ValueError, LookupError, TypeError):
        return ""
    return ": " + str(message) if message else ""


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


def resolve_clip_url(clip_slug, website_token=None):
    """Return a clip's direct MP4 URL, given its Helix clip id (the "slug" in Twitch's clip
    GQL API - same value). Raises StreamUnavailableError if it can't be resolved.

    Used to be a deterministic thumbnail_url-to-MP4 suffix substitution (no GQL/auth needed) -
    Twitch moved clip thumbnails to a CDN path with no derivable video-file name, breaking that
    trick for every clip (confirmed live). This GQL query is the replacement."""
    url = gql.get_clip_video_url(clip_slug, website_token)
    if url is None:
        raise StreamUnavailableError(clip_slug)
    return url
