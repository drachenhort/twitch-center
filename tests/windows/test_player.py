from unittest.mock import patch

from lib.windows import player


class FakeSettings:
    def __init__(self, chat_display_mode):
        self.chat_display_mode = chat_display_mode


class FakeChatClient:
    instances = []

    def __init__(self, channel):
        self.channel = channel
        self.disconnected = False
        FakeChatClient.instances.append(self)

    def disconnect(self):
        self.disconnected = True


class FakeChatOverlay:
    instances = []

    def __init__(self, xml_filename, script_path, default_skin, default_res, channel=None, chat_client_cls=None):
        self.channel = channel
        self._client = (chat_client_cls or FakeChatClient)(channel)
        self.shown = False
        self.closed = False
        FakeChatOverlay.instances.append(self)

    def show(self):
        self.shown = True

    def close(self):
        if self._client is not None:
            self._client.disconnect()
        self.closed = True


def _patch_playable():
    return patch("lib.windows.player.Helper"), patch("lib.windows.player.xbmc.Player")


def test_play_stream_returns_true_and_plays_when_inputstream_available():
    with patch("lib.windows.player.Helper") as mock_helper_cls, patch(
        "lib.windows.player.xbmc.Player"
    ) as mock_player_cls:
        mock_helper_cls.return_value.check_inputstream.return_value = True
        mock_helper_cls.return_value.inputstream_addon = "inputstream.adaptive"

        result = player.play_stream(
            "https://example.invalid/stream.m3u8", "somechannel", settings=FakeSettings("standalone")
        )

    assert result is True
    mock_helper_cls.assert_called_once_with("hls")
    mock_player_cls.return_value.play.assert_called_once()
    call_args = mock_player_cls.return_value.play.call_args
    assert call_args[0][0] == "https://example.invalid/stream.m3u8"
    list_item = call_args[0][1]
    assert list_item.getProperty("inputstream") == "inputstream.adaptive"
    assert list_item.getProperty("inputstream.adaptive.manifest_type") == "hls"
    assert list_item.getMimeType() == "application/x-mpegURL"
    assert list_item.getContentLookup() is False
    assert list_item.getPath() == "https://example.invalid/stream.m3u8"


def test_play_stream_returns_false_when_inputstream_declined():
    with patch("lib.windows.player.Helper") as mock_helper_cls, patch(
        "lib.windows.player.xbmc.Player"
    ) as mock_player_cls:
        mock_helper_cls.return_value.check_inputstream.return_value = False

        result = player.play_stream(
            "https://example.invalid/stream.m3u8", "somechannel", settings=FakeSettings("standalone")
        )

    assert result is False
    mock_player_cls.return_value.play.assert_not_called()


def test_play_stream_creates_and_shows_overlay_when_mode_is_overlay():
    FakeChatOverlay.instances.clear()
    with patch("lib.windows.player.Helper") as mock_helper_cls, patch(
        "lib.windows.player.xbmc.Player"
    ) as mock_player_cls:
        mock_helper_cls.return_value.check_inputstream.return_value = True
        mock_helper_cls.return_value.inputstream_addon = "inputstream.adaptive"

        result = player.play_stream(
            "https://example.invalid/stream.m3u8",
            "somechannel",
            settings=FakeSettings("overlay"),
            chat_overlay_cls=FakeChatOverlay,
            chat_client_cls=FakeChatClient,
        )

    assert result is True
    assert len(FakeChatOverlay.instances) == 1
    overlay = FakeChatOverlay.instances[0]
    assert overlay.channel == "somechannel"
    assert overlay.shown is True


def test_play_stream_creates_overlay_when_mode_is_both():
    FakeChatOverlay.instances.clear()
    with patch("lib.windows.player.Helper") as mock_helper_cls, patch(
        "lib.windows.player.xbmc.Player"
    ) as mock_player_cls:
        mock_helper_cls.return_value.check_inputstream.return_value = True
        mock_helper_cls.return_value.inputstream_addon = "inputstream.adaptive"

        player.play_stream(
            "https://example.invalid/stream.m3u8",
            "somechannel",
            settings=FakeSettings("both"),
            chat_overlay_cls=FakeChatOverlay,
            chat_client_cls=FakeChatClient,
        )

    assert len(FakeChatOverlay.instances) == 1


def test_play_stream_skips_overlay_when_mode_is_standalone():
    FakeChatOverlay.instances.clear()
    with patch("lib.windows.player.Helper") as mock_helper_cls, patch(
        "lib.windows.player.xbmc.Player"
    ) as mock_player_cls:
        mock_helper_cls.return_value.check_inputstream.return_value = True
        mock_helper_cls.return_value.inputstream_addon = "inputstream.adaptive"

        player.play_stream(
            "https://example.invalid/stream.m3u8",
            "somechannel",
            settings=FakeSettings("standalone"),
            chat_overlay_cls=FakeChatOverlay,
            chat_client_cls=FakeChatClient,
        )

    assert len(FakeChatOverlay.instances) == 0


def test_play_stream_skips_overlay_when_inputstream_declined():
    FakeChatOverlay.instances.clear()
    with patch("lib.windows.player.Helper") as mock_helper_cls, patch(
        "lib.windows.player.xbmc.Player"
    ) as mock_player_cls:
        mock_helper_cls.return_value.check_inputstream.return_value = False

        result = player.play_stream(
            "https://example.invalid/stream.m3u8",
            "somechannel",
            settings=FakeSettings("overlay"),
            chat_overlay_cls=FakeChatOverlay,
            chat_client_cls=FakeChatClient,
        )

    assert result is False
    assert len(FakeChatOverlay.instances) == 0


def test_play_stream_returns_true_even_if_chat_overlay_construction_raises():
    def _raising_overlay_cls(*args, **kwargs):
        raise RuntimeError("boom")

    with patch("lib.windows.player.Helper") as mock_helper_cls, patch(
        "lib.windows.player.xbmc.Player"
    ) as mock_player_cls, patch("lib.windows.player.xbmc.log") as mock_log:
        mock_helper_cls.return_value.check_inputstream.return_value = True
        mock_helper_cls.return_value.inputstream_addon = "inputstream.adaptive"

        result = player.play_stream(
            "https://example.invalid/stream.m3u8",
            "somechannel",
            settings=FakeSettings("overlay"),
            chat_overlay_cls=_raising_overlay_cls,
            chat_client_cls=FakeChatClient,
        )

    assert result is True
    mock_log.assert_called_once()


def test_chat_aware_player_teardown_closes_overlay_and_disconnects_client_on_stop():
    FakeChatOverlay.instances.clear()
    overlay = FakeChatOverlay(
        "x.xml", "/tmp", "Default", "1080i", channel="c", chat_client_cls=FakeChatClient
    )
    watcher = player._ChatAwarePlayer(overlay)

    watcher.onPlaybackStopped()

    assert overlay.closed is True
    assert overlay._client.disconnected is True


def test_chat_aware_player_teardown_closes_overlay_and_disconnects_client_on_end():
    FakeChatOverlay.instances.clear()
    overlay = FakeChatOverlay(
        "x.xml", "/tmp", "Default", "1080i", channel="c", chat_client_cls=FakeChatClient
    )
    watcher = player._ChatAwarePlayer(overlay)

    watcher.onPlaybackEnded()

    assert overlay.closed is True
    assert overlay._client.disconnected is True


def test_chat_aware_player_teardown_works_even_if_overlay_client_not_yet_set():
    FakeChatOverlay.instances.clear()
    overlay = FakeChatOverlay(
        "x.xml", "/tmp", "Default", "1080i", channel="c", chat_client_cls=FakeChatClient
    )
    overlay._client = None  # simulates onInit not having run yet when show() returned
    watcher = player._ChatAwarePlayer(overlay)

    watcher.onPlaybackStopped()  # must not raise

    assert overlay.closed is True


def test_play_stream_tears_down_previous_watcher_when_called_again():
    FakeChatOverlay.instances.clear()
    with patch("lib.windows.player.Helper") as mock_helper_cls, patch(
        "lib.windows.player.xbmc.Player"
    ) as mock_player_cls:
        mock_helper_cls.return_value.check_inputstream.return_value = True
        mock_helper_cls.return_value.inputstream_addon = "inputstream.adaptive"

        player.play_stream(
            "https://example.invalid/stream1.m3u8",
            "channel1",
            settings=FakeSettings("overlay"),
            chat_overlay_cls=FakeChatOverlay,
            chat_client_cls=FakeChatClient,
        )
        first_overlay = FakeChatOverlay.instances[0]
        assert first_overlay.closed is False

        player.play_stream(
            "https://example.invalid/stream2.m3u8",
            "channel2",
            settings=FakeSettings("overlay"),
            chat_overlay_cls=FakeChatOverlay,
            chat_client_cls=FakeChatClient,
        )

    assert first_overlay.closed is True
    assert len(FakeChatOverlay.instances) == 2
    second_overlay = FakeChatOverlay.instances[1]
    assert second_overlay.closed is False
