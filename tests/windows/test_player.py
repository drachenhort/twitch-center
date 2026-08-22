from unittest.mock import patch

from lib.twitch import eventsub as eventsub_module
from lib.twitch import irc as irc_module
from lib.twitch import stream
from lib.windows import player


class FakeSettings:
    def __init__(self, chat_display_mode, chat_engine="irc", chat_overlay_variable_height=False):
        self.chat_display_mode = chat_display_mode
        self.chat_engine = chat_engine
        self.chat_overlay_variable_height = chat_overlay_variable_height


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

    def __init__(self, xml_filename, script_path, default_skin, default_res, channel=None,
                 access_token=None, client_id=None, broadcaster_user_id=None, user_id=None,
                 chat_client_cls=None):
        self.channel = channel
        self.access_token = access_token
        self.client_id = client_id
        self.broadcaster_user_id = broadcaster_user_id
        self.user_id = user_id
        self._client_cls_used = chat_client_cls or FakeChatClient
        self._client = self._client_cls_used(channel)
        self.shown = False
        self.closed = False
        type(self).instances.append(self)

    def show(self):
        self.shown = True

    def close(self):
        if self._client is not None:
            self._client.disconnect()
        self.closed = True


class FakeWatchdog:
    def __init__(self, *args, **kwargs):
        pass

    def start(self):
        pass

    def stop(self):
        pass


def _patch_playable():
    return patch("lib.windows.player.Helper"), patch("lib.windows.player.xbmc.Player")


def test_play_stream_returns_true_and_plays_when_inputstream_available():
    with patch("lib.windows.player.Helper") as mock_helper_cls, patch(
        "lib.windows.player.xbmc.Player"
    ) as mock_player_cls, patch("lib.windows.player.PlaybackWatchdog", FakeWatchdog):
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
    ) as mock_player_cls, patch("lib.windows.player.PlaybackWatchdog", FakeWatchdog):
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
    ) as mock_player_cls, patch("lib.windows.player.PlaybackWatchdog", FakeWatchdog):
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
    ) as mock_player_cls, patch("lib.windows.player.PlaybackWatchdog", FakeWatchdog):
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
    ) as mock_player_cls, patch("lib.windows.player.PlaybackWatchdog", FakeWatchdog):
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
    ) as mock_player_cls, patch("lib.windows.player.PlaybackWatchdog", FakeWatchdog):
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
    ) as mock_player_cls, patch("lib.windows.player.xbmc.log") as mock_log, patch(
        "lib.windows.player.PlaybackWatchdog", FakeWatchdog
    ):
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
    watcher = player._ChatAwarePlayer(
        overlay, url="https://example.invalid/stream.m3u8", channel="c", enable_watchdog=False
    )

    watcher.onPlayBackStopped()

    assert overlay.closed is True
    assert overlay._client.disconnected is True


def test_chat_aware_player_teardown_closes_overlay_and_disconnects_client_on_end():
    FakeChatOverlay.instances.clear()
    overlay = FakeChatOverlay(
        "x.xml", "/tmp", "Default", "1080i", channel="c", chat_client_cls=FakeChatClient
    )
    watcher = player._ChatAwarePlayer(
        overlay, url="https://example.invalid/stream.m3u8", channel="c", enable_watchdog=False
    )

    watcher.onPlayBackEnded()

    assert overlay.closed is True
    assert overlay._client.disconnected is True


def test_chat_aware_player_teardown_closes_overlay_and_disconnects_client_on_error():
    FakeChatOverlay.instances.clear()
    overlay = FakeChatOverlay(
        "x.xml", "/tmp", "Default", "1080i", channel="c", chat_client_cls=FakeChatClient
    )
    watcher = player._ChatAwarePlayer(
        overlay, url="https://example.invalid/stream.m3u8", channel="c", enable_watchdog=False
    )

    watcher.onPlayBackError()

    assert overlay.closed is True
    assert overlay._client.disconnected is True


def test_chat_aware_player_teardown_works_even_if_overlay_client_not_yet_set():
    FakeChatOverlay.instances.clear()
    overlay = FakeChatOverlay(
        "x.xml", "/tmp", "Default", "1080i", channel="c", chat_client_cls=FakeChatClient
    )
    overlay._client = None  # simulates onInit not having run yet when show() returned
    watcher = player._ChatAwarePlayer(
        overlay, url="https://example.invalid/stream.m3u8", channel="c", enable_watchdog=False
    )

    watcher.onPlayBackStopped()  # must not raise

    assert overlay.closed is True


def test_play_stream_tears_down_previous_watcher_when_called_again():
    FakeChatOverlay.instances.clear()
    with patch("lib.windows.player.Helper") as mock_helper_cls, patch(
        "lib.windows.player.xbmc.Player"
    ) as mock_player_cls, patch("lib.windows.player.PlaybackWatchdog", FakeWatchdog):
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


def test_ad_break_state_tracks_event_and_clears():
    state = player.AdBreakState()
    assert state.active is False

    state.begin(
        {
            "duration_seconds": 60,
            "started_at": "2026-08-14T00:00:00Z",
            "is_automatic": True,
            "broadcaster_user_login": "streamer",
        }
    )
    assert state.active is True
    assert state.duration == 60
    assert state.channel == "streamer"
    assert state.is_automatic is True

    state.clear()
    assert state.active is False
    assert state.duration == 0


class FakePlayerForRecovery:
    def __init__(self):
        self.played = []

    def isPlaying(self):
        return True

    def play(self, url, list_item):
        self.played.append((url, list_item.getPath()))


def test_recovery_manager_resolves_fresh_url_and_restarts_player():
    with patch.object(stream, "resolve_stream_url", return_value="https://fresh.url/stream.m3u8") as mock_resolve, patch(
        "lib.windows.player.Helper"
    ) as mock_helper_cls:
        mock_helper_cls.return_value.check_inputstream.return_value = True
        mock_helper_cls.return_value.inputstream_addon = "inputstream.adaptive"

        fake_player = FakePlayerForRecovery()
        recovery = player.RecoveryManager(fake_player, "somechannel")
        recovery.recover()

    mock_resolve.assert_called_once_with("somechannel", None)
    assert len(fake_player.played) == 1
    assert fake_player.played[0][0] == "https://fresh.url/stream.m3u8"
    assert fake_player.played[0][1] == "https://fresh.url/stream.m3u8"


def test_recovery_manager_is_noop_when_already_recovering():
    with patch.object(stream, "resolve_stream_url") as mock_resolve, patch(
        "lib.windows.player.Helper"
    ) as mock_helper_cls:
        mock_helper_cls.return_value.check_inputstream.return_value = True

        fake_player = FakePlayerForRecovery()
        recovery = player.RecoveryManager(fake_player, "somechannel")

        # Hold the lock to simulate a concurrent recovery in progress.
        with recovery._lock:
            recovery.recover()

        mock_resolve.assert_not_called()


def test_playback_watchdog_triggers_recovery_after_stall():
    fake_player = FakePlayerForRecovery()
    fake_player.getTime = lambda: 5.0

    ad_state = player.AdBreakState()
    recovery = player.RecoveryManager(fake_player, "channel")
    watchdog = player.PlaybackWatchdog(fake_player, ad_state, recovery)

    with patch.object(recovery, "recover") as mock_recover, patch.object(
        player, "time"
    ) as mock_time:
        counter = [0]

        def monotonic():
            counter[0] += 1
            return counter[0] - 1

        mock_time.monotonic.side_effect = monotonic

        for _ in range(16):
            watchdog._check_once()

    mock_recover.assert_called_once()


def test_playback_watchdog_uses_longer_threshold_during_active_ad_break():
    fake_player = FakePlayerForRecovery()
    fake_player.getTime = lambda: 5.0

    ad_state = player.AdBreakState()
    ad_state.begin({"duration_seconds": 5, "broadcaster_user_login": "streamer"})
    recovery = player.RecoveryManager(fake_player, "channel")
    watchdog = player.PlaybackWatchdog(fake_player, ad_state, recovery)

    with patch.object(recovery, "recover") as mock_recover, patch.object(
        player, "time"
    ) as mock_time:
        counter = [0]

        def monotonic():
            counter[0] += 1
            return counter[0] - 1

        mock_time.monotonic.side_effect = monotonic

        # Threshold is duration (5) + grace (10) = 15, so 16 checks triggers it.
        for _ in range(16):
            watchdog._check_once()

    mock_recover.assert_called_once()


def test_playback_watchdog_does_not_recover_while_position_advances():
    fake_player = FakePlayerForRecovery()
    position = [0.0]

    def advance():
        position[0] += 1.0
        return position[0]

    fake_player.getTime = advance

    ad_state = player.AdBreakState()
    recovery = player.RecoveryManager(fake_player, "channel")
    watchdog = player.PlaybackWatchdog(fake_player, ad_state, recovery)

    with patch.object(recovery, "recover") as mock_recover:
        for _ in range(50):
            watchdog._check_once()

    mock_recover.assert_not_called()


def test_play_stream_uses_irc_engine_by_default():
    FakeChatOverlay.instances.clear()
    with patch("lib.windows.player.Helper") as mock_helper_cls, patch(
        "lib.windows.player.xbmc.Player"
    ), patch("lib.windows.player.PlaybackWatchdog", FakeWatchdog), patch(
        "lib.windows.player.api.get_user_by_login"
    ) as mock_get_user:
        mock_helper_cls.return_value.check_inputstream.return_value = True
        mock_helper_cls.return_value.inputstream_addon = "inputstream.adaptive"

        player.play_stream(
            "https://example.invalid/stream.m3u8",
            "somechannel",
            settings=FakeSettings("overlay", chat_engine="irc"),
            chat_overlay_cls=FakeChatOverlay,
        )

    mock_get_user.assert_not_called()
    overlay = FakeChatOverlay.instances[0]
    assert overlay._client_cls_used is irc_module.ChatClient


def test_play_stream_uses_eventsub_engine_and_resolves_broadcaster_id():
    FakeChatOverlay.instances.clear()
    with patch("lib.windows.player.Helper") as mock_helper_cls, patch(
        "lib.windows.player.xbmc.Player"
    ), patch("lib.windows.player.PlaybackWatchdog", FakeWatchdog), patch(
        "lib.windows.player.api.get_user_by_login",
        return_value={"id": "999", "login": "somechannel", "display_name": "SomeChannel"},
    ) as mock_get_user:
        mock_helper_cls.return_value.check_inputstream.return_value = True
        mock_helper_cls.return_value.inputstream_addon = "inputstream.adaptive"

        player.play_stream(
            "https://example.invalid/stream.m3u8",
            "somechannel",
            settings=FakeSettings("overlay", chat_engine="eventsub"),
            access_token="tok",
            client_id="cid",
            user_id="42",
            chat_overlay_cls=FakeChatOverlay,
        )

    mock_get_user.assert_called_once_with("tok", "cid", "somechannel")
    overlay = FakeChatOverlay.instances[0]
    assert overlay._client_cls_used is eventsub_module.ChatClient
    assert overlay.broadcaster_user_id == "999"
    assert overlay.access_token == "tok"
    assert overlay.client_id == "cid"
    assert overlay.user_id == "42"


def test_play_stream_falls_back_to_irc_when_broadcaster_id_resolution_fails():
    FakeChatOverlay.instances.clear()
    with patch("lib.windows.player.Helper") as mock_helper_cls, patch(
        "lib.windows.player.xbmc.Player"
    ), patch("lib.windows.player.PlaybackWatchdog", FakeWatchdog), patch(
        "lib.windows.player.api.get_user_by_login", return_value=None
    ), patch("lib.windows.player.xbmc.log") as mock_log:
        mock_helper_cls.return_value.check_inputstream.return_value = True
        mock_helper_cls.return_value.inputstream_addon = "inputstream.adaptive"

        result = player.play_stream(
            "https://example.invalid/stream.m3u8",
            "somechannel",
            settings=FakeSettings("overlay", chat_engine="eventsub"),
            access_token="tok",
            client_id="cid",
            user_id="42",
            chat_overlay_cls=FakeChatOverlay,
        )

    assert result is True
    overlay = FakeChatOverlay.instances[0]
    assert overlay._client_cls_used is irc_module.ChatClient
    mock_log.assert_called_once()


def test_play_stream_falls_back_to_irc_when_broadcaster_id_lookup_raises():
    # Covers e.g. Search-results playback (no access_token/client_id at all, so
    # api.get_user_by_login raises TypeError) or an expired/unscoped token
    # (api.TokenExpiredError) - either way chat must still fall back to IRC, not be skipped.
    FakeChatOverlay.instances.clear()
    with patch("lib.windows.player.Helper") as mock_helper_cls, patch(
        "lib.windows.player.xbmc.Player"
    ), patch("lib.windows.player.PlaybackWatchdog", FakeWatchdog), patch(
        "lib.windows.player.api.get_user_by_login", side_effect=TypeError("boom")
    ), patch("lib.windows.player.xbmc.log") as mock_log:
        mock_helper_cls.return_value.check_inputstream.return_value = True
        mock_helper_cls.return_value.inputstream_addon = "inputstream.adaptive"

        result = player.play_stream(
            "https://example.invalid/stream.m3u8",
            "somechannel",
            settings=FakeSettings("overlay", chat_engine="eventsub"),
            access_token=None,
            client_id=None,
            user_id=None,
            chat_overlay_cls=FakeChatOverlay,
        )

    assert result is True
    assert len(FakeChatOverlay.instances) == 1
    overlay = FakeChatOverlay.instances[0]
    assert overlay._client_cls_used is irc_module.ChatClient
    assert mock_log.call_count == 2  # lookup-failed warning, then broadcaster-id-unresolved warning


class FakeVariableChatOverlay(FakeChatOverlay):
    instances = []


def test_play_stream_uses_variable_overlay_when_enabled_and_eventsub():
    FakeChatOverlay.instances.clear()
    FakeVariableChatOverlay.instances.clear()
    with patch("lib.windows.player.Helper") as mock_helper_cls, patch(
        "lib.windows.player.xbmc.Player"
    ), patch("lib.windows.player.PlaybackWatchdog", FakeWatchdog), patch(
        "lib.windows.player.api.get_user_by_login",
        return_value={"id": "999", "login": "somechannel", "display_name": "SomeChannel"},
    ), patch(
        "lib.windows.player.VariableChatOverlay", FakeVariableChatOverlay
    ):
        mock_helper_cls.return_value.check_inputstream.return_value = True
        mock_helper_cls.return_value.inputstream_addon = "inputstream.adaptive"

        player.play_stream(
            "https://example.invalid/stream.m3u8",
            "somechannel",
            settings=FakeSettings(
                "overlay", chat_engine="eventsub", chat_overlay_variable_height=True
            ),
            access_token="tok",
            client_id="cid",
            user_id="42",
        )

    assert len(FakeVariableChatOverlay.instances) == 1


def test_play_stream_uses_default_overlay_when_variable_setting_disabled():
    FakeChatOverlay.instances.clear()
    FakeVariableChatOverlay.instances.clear()
    with patch("lib.windows.player.Helper") as mock_helper_cls, patch(
        "lib.windows.player.xbmc.Player"
    ), patch("lib.windows.player.PlaybackWatchdog", FakeWatchdog), patch(
        "lib.windows.player.api.get_user_by_login",
        return_value={"id": "999", "login": "somechannel", "display_name": "SomeChannel"},
    ), patch(
        "lib.windows.player.ChatOverlay", FakeChatOverlay
    ), patch(
        "lib.windows.player.VariableChatOverlay", FakeVariableChatOverlay
    ):
        mock_helper_cls.return_value.check_inputstream.return_value = True
        mock_helper_cls.return_value.inputstream_addon = "inputstream.adaptive"

        player.play_stream(
            "https://example.invalid/stream.m3u8",
            "somechannel",
            settings=FakeSettings(
                "overlay", chat_engine="eventsub", chat_overlay_variable_height=False
            ),
            access_token="tok",
            client_id="cid",
            user_id="42",
        )

    assert len(FakeChatOverlay.instances) == 1
    assert FakeVariableChatOverlay.instances == []


def test_play_stream_uses_default_overlay_when_variable_setting_enabled_but_irc_engine():
    FakeChatOverlay.instances.clear()
    FakeVariableChatOverlay.instances.clear()
    with patch("lib.windows.player.Helper") as mock_helper_cls, patch(
        "lib.windows.player.xbmc.Player"
    ), patch("lib.windows.player.PlaybackWatchdog", FakeWatchdog), patch(
        "lib.windows.player.ChatOverlay", FakeChatOverlay
    ), patch(
        "lib.windows.player.VariableChatOverlay", FakeVariableChatOverlay
    ):
        mock_helper_cls.return_value.check_inputstream.return_value = True
        mock_helper_cls.return_value.inputstream_addon = "inputstream.adaptive"

        player.play_stream(
            "https://example.invalid/stream.m3u8",
            "somechannel",
            settings=FakeSettings(
                "overlay", chat_engine="irc", chat_overlay_variable_height=True
            ),
        )

    assert len(FakeChatOverlay.instances) == 1
    assert FakeVariableChatOverlay.instances == []


def test_play_stream_uses_default_overlay_when_eventsub_falls_back_to_irc():
    FakeChatOverlay.instances.clear()
    FakeVariableChatOverlay.instances.clear()
    with patch("lib.windows.player.Helper") as mock_helper_cls, patch(
        "lib.windows.player.xbmc.Player"
    ), patch("lib.windows.player.PlaybackWatchdog", FakeWatchdog), patch(
        "lib.windows.player.api.get_user_by_login", return_value=None
    ), patch(
        "lib.windows.player.ChatOverlay", FakeChatOverlay
    ), patch(
        "lib.windows.player.VariableChatOverlay", FakeVariableChatOverlay
    ):
        mock_helper_cls.return_value.check_inputstream.return_value = True
        mock_helper_cls.return_value.inputstream_addon = "inputstream.adaptive"

        player.play_stream(
            "https://example.invalid/stream.m3u8",
            "somechannel",
            settings=FakeSettings(
                "overlay", chat_engine="eventsub", chat_overlay_variable_height=True
            ),
            access_token="tok",
            client_id="cid",
            user_id="42",
        )

    assert len(FakeChatOverlay.instances) == 1
    assert FakeVariableChatOverlay.instances == []


def test_playback_watchdog_does_not_recover_while_paused():
    fake_player = FakePlayerForRecovery()
    fake_player.getTime = lambda: 5.0

    ad_state = player.AdBreakState()
    recovery = player.RecoveryManager(fake_player, "channel")
    watchdog = player.PlaybackWatchdog(
        fake_player, ad_state, recovery, is_paused_fn=lambda: True
    )

    with patch.object(recovery, "recover") as mock_recover, patch.object(
        player, "time"
    ) as mock_time:
        mock_time.monotonic.return_value = 100.0

        for _ in range(50):
            watchdog._check_once()

    mock_recover.assert_not_called()
