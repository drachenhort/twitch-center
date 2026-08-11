from unittest.mock import patch

import pytest

from lib.twitch import api, gql, stream


def test_resolve_stream_url_builds_usher_url_on_success():
    token = {"value": "opaque-token-json", "signature": "abc123"}
    with patch.object(gql, "get_playback_access_token", return_value=token) as mock_get_token:
        url = stream.resolve_stream_url("access-token", "somechannel")
    mock_get_token.assert_called_once_with("access-token", "somechannel")
    assert url == (
        "https://usher.ttvnw.net/api/channel/hls/somechannel.m3u8"
        "?token=opaque-token-json&sig=abc123"
        "&allow_source=true&fast_bread=true&player_backend=mediaplayer"
    )


def test_resolve_stream_url_url_encodes_the_token_value():
    token = {"value": "value with spaces & symbols", "signature": "abc123"}
    with patch.object(gql, "get_playback_access_token", return_value=token):
        url = stream.resolve_stream_url("access-token", "somechannel")
    assert "value%20with%20spaces%20%26%20symbols" in url


def test_resolve_stream_url_raises_stream_unavailable_when_token_is_none():
    with patch.object(gql, "get_playback_access_token", return_value=None):
        with pytest.raises(stream.StreamUnavailableError):
            stream.resolve_stream_url("access-token", "somechannel")


def test_resolve_stream_url_lets_token_expired_error_propagate():
    with patch.object(gql, "get_playback_access_token", side_effect=api.TokenExpiredError()):
        with pytest.raises(api.TokenExpiredError):
            stream.resolve_stream_url("access-token", "somechannel")
