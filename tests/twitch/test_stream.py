from unittest.mock import patch

import pytest

from lib.twitch import gql, stream


def test_resolve_stream_url_builds_usher_url_on_success():
    token = {"value": "opaque-token-json", "signature": "abc123"}
    with patch.object(gql, "get_playback_access_token", return_value=token) as mock_get_token:
        url = stream.resolve_stream_url("somechannel")
    mock_get_token.assert_called_once_with("somechannel", None)
    assert url.startswith(
        "https://usher.ttvnw.net/api/channel/hls/somechannel.m3u8"
        "?token=opaque-token-json&sig=abc123"
        "&allow_source=true&allow_audio_only=true&fast_bread=true&player_backend=mediaplayer"
        "&acmb=e30=&p="
    )


def test_resolve_stream_url_url_encodes_the_token_value():
    token = {"value": "value with spaces & symbols", "signature": "abc123"}
    with patch.object(gql, "get_playback_access_token", return_value=token):
        url = stream.resolve_stream_url("somechannel")
    assert "value%20with%20spaces%20%26%20symbols" in url


def test_resolve_stream_url_raises_stream_unavailable_when_token_is_none():
    with patch.object(gql, "get_playback_access_token", return_value=None):
        with pytest.raises(stream.StreamUnavailableError):
            stream.resolve_stream_url("somechannel")


def test_resolve_stream_url_passes_website_token_through():
    token = {"value": "opaque-token-json", "signature": "abc123"}
    with patch.object(gql, "get_playback_access_token", return_value=token) as mock_get_token:
        stream.resolve_stream_url("somechannel", "my-website-token")
    mock_get_token.assert_called_once_with("somechannel", "my-website-token")


def test_resolve_vod_url_builds_usher_vod_url_on_success():
    token = {"value": "vod-token-json", "signature": "abc123"}
    with patch.object(gql, "get_vod_playback_access_token", return_value=token) as mock_get_token:
        url = stream.resolve_vod_url("123456789")
    mock_get_token.assert_called_once_with("123456789", None)
    assert url.startswith("https://usher.ttvnw.net/vod/123456789.m3u8?token=vod-token-json&sig=abc123")


def test_resolve_vod_url_raises_stream_unavailable_when_token_is_none():
    with patch.object(gql, "get_vod_playback_access_token", return_value=None):
        with pytest.raises(stream.StreamUnavailableError):
            stream.resolve_vod_url("123456789")


def test_resolve_vod_url_passes_website_token_through():
    token = {"value": "v", "signature": "s"}
    with patch.object(gql, "get_vod_playback_access_token", return_value=token) as mock_get_token:
        stream.resolve_vod_url("123456789", "my-website-token")
    mock_get_token.assert_called_once_with("123456789", "my-website-token")


def test_resolve_clip_url_replaces_preview_suffix_with_mp4():
    thumb = "https://clips-media-assets2.twitch.tv/AB12CD34-preview-480x272.jpg"
    url = stream.resolve_clip_url(thumb)
    assert url == "https://clips-media-assets2.twitch.tv/AB12CD34.mp4"


def test_resolve_clip_url_raises_on_unexpected_format():
    with pytest.raises(stream.StreamUnavailableError):
        stream.resolve_clip_url("https://example.invalid/not-a-preview-url.jpg")
