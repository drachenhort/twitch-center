from unittest.mock import patch

import pytest

from lib.twitch import gql, stream


def test_resolve_stream_url_builds_usher_url_on_success():
    token = {"value": "opaque-token-json", "signature": "abc123"}
    with patch.object(gql, "get_playback_access_token", return_value=token) as mock_get_token:
        url = stream.resolve_stream_url("somechannel")
    mock_get_token.assert_called_once_with("somechannel", None)
    assert url == (
        "https://usher.ttvnw.net/api/channel/hls/somechannel.m3u8"
        "?token=opaque-token-json&sig=abc123"
        "&allow_source=true&fast_bread=true&player_backend=mediaplayer"
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
