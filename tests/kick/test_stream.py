from unittest.mock import patch

import pytest

from lib.kick import api, stream


def test_resolve_stream_url_returns_playback_url_when_live():
    channel = {
        "slug": "somechannel",
        "playback_url": "https://stream.kick.com/somechannel.m3u8",
        "livestream": {"is_live": True},
    }
    with patch.object(api, "get_unofficial_channel", return_value=channel) as mock_get_channel:
        url = stream.resolve_stream_url("token", "somechannel")
    mock_get_channel.assert_called_once_with("somechannel")
    assert url == "https://stream.kick.com/somechannel.m3u8"


def test_resolve_stream_url_raises_when_channel_not_found():
    with patch.object(api, "get_unofficial_channel", return_value=None):
        with pytest.raises(stream.StreamUnavailableError):
            stream.resolve_stream_url("token", "nosuchchannel")


def test_resolve_stream_url_raises_when_not_live():
    channel = {"slug": "somechannel", "playback_url": "https://x.m3u8", "livestream": {"is_live": False}}
    with patch.object(api, "get_unofficial_channel", return_value=channel):
        with pytest.raises(stream.StreamUnavailableError):
            stream.resolve_stream_url("token", "somechannel")


def test_resolve_stream_url_raises_when_livestream_missing():
    # Kick's unofficial endpoint returns "livestream": null for an offline
    # channel, not an empty/absent is_live flag.
    channel = {"slug": "somechannel", "playback_url": "https://x.m3u8", "livestream": None}
    with patch.object(api, "get_unofficial_channel", return_value=channel):
        with pytest.raises(stream.StreamUnavailableError):
            stream.resolve_stream_url("token", "somechannel")


def test_resolve_stream_url_raises_when_playback_url_missing():
    channel = {"slug": "somechannel", "livestream": {"is_live": True}}
    with patch.object(api, "get_unofficial_channel", return_value=channel):
        with pytest.raises(stream.StreamUnavailableError):
            stream.resolve_stream_url("token", "somechannel")
