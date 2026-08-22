from unittest.mock import patch

import pytest

from lib.kick import api, stream


def test_resolve_stream_url_returns_playback_url_when_live():
    channel = {"slug": "somechannel", "stream": {"is_live": True, "url": "https://stream.kick.com/somechannel.m3u8"}}
    with patch.object(api, "get_channel", return_value=channel) as mock_get_channel:
        url = stream.resolve_stream_url("token", "somechannel")
    mock_get_channel.assert_called_once_with("token", "somechannel")
    assert url == "https://stream.kick.com/somechannel.m3u8"


def test_resolve_stream_url_raises_when_channel_not_found():
    with patch.object(api, "get_channel", return_value=None):
        with pytest.raises(stream.StreamUnavailableError):
            stream.resolve_stream_url("token", "nosuchchannel")


def test_resolve_stream_url_raises_when_not_live():
    channel = {"slug": "somechannel", "stream": {"is_live": False, "url": None}}
    with patch.object(api, "get_channel", return_value=channel):
        with pytest.raises(stream.StreamUnavailableError):
            stream.resolve_stream_url("token", "somechannel")


def test_resolve_stream_url_raises_when_url_field_missing():
    channel = {"slug": "somechannel", "stream": {"is_live": True}}
    with patch.object(api, "get_channel", return_value=channel):
        with pytest.raises(stream.StreamUnavailableError):
            stream.resolve_stream_url("token", "somechannel")
