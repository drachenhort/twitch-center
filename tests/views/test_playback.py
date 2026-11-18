from unittest.mock import MagicMock, patch

from lib import providers
from lib.views import playback

URL = "https://example.invalid/stream.m3u8"
TOKEN = {"access_token": "tok", "refresh_token": "ref", "user_id": "u1"}


def test_play_channel_twitch_passes_token_fields():
    show_error = MagicMock()
    with patch.object(playback.providers, "resolve_stream_url", return_value=URL), patch.object(
        playback.player, "play_stream", return_value=True
    ) as mock_play:
        result = playback.play_channel("twitch", "alice", show_error, token=TOKEN, client_id="cid")
    assert result is True
    mock_play.assert_called_once_with(
        URL, "alice", platform="twitch", access_token="tok", client_id="cid", user_id="u1"
    )
    show_error.assert_not_called()


def test_play_channel_kick_passes_platform_only():
    with patch.object(playback.providers, "resolve_stream_url", return_value=URL), patch.object(
        playback.player, "play_stream", return_value=True
    ) as mock_play:
        result = playback.play_channel("kick", "bob", MagicMock())
    assert result is True
    mock_play.assert_called_once_with(URL, "bob", platform="kick")


def test_play_channel_stream_start_error_shows_dialog_and_error():
    show_error = MagicMock()
    with patch.object(
        playback.providers, "resolve_stream_url", side_effect=providers.StreamStartError("why")
    ), patch.object(playback.xbmcgui.Dialog, "ok") as mock_ok:
        result = playback.play_channel("twitch", "alice", show_error, token=TOKEN, client_id="cid")
    assert result is False
    mock_ok.assert_called_once_with("Couldn't start stream", "why")
    show_error.assert_called_once_with(playback.PLAYBACK_ERROR_MESSAGE)


def test_play_channel_unavailable_and_unexpected_errors_show_error():
    for exc in (providers.StreamUnavailableError("alice"), RuntimeError("boom")):
        show_error = MagicMock()
        with patch.object(playback.providers, "resolve_stream_url", side_effect=exc):
            result = playback.play_channel("twitch", "alice", show_error, token=TOKEN, client_id="cid")
        assert result is False
        show_error.assert_called_once_with(playback.PLAYBACK_ERROR_MESSAGE)


def test_play_channel_play_stream_false_shows_error():
    show_error = MagicMock()
    with patch.object(playback.providers, "resolve_stream_url", return_value=URL), patch.object(
        playback.player, "play_stream", return_value=False
    ):
        result = playback.play_channel("kick", "bob", show_error)
    assert result is False
    show_error.assert_called_once_with(playback.PLAYBACK_ERROR_MESSAGE)
