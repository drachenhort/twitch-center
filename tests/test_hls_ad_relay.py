import socket
import time
from unittest.mock import Mock

from lib.hls_ad_relay import AdSkipRelay, parse_media_playlist, select_variant_url

_MASTER_PLAYLIST = """#EXTM3U
#EXT-X-STREAM-INF:BANDWIDTH=3000000,RESOLUTION=1280x720
720p60/index-dvr.m3u8?token=abc
#EXT-X-STREAM-INF:BANDWIDTH=6000000,RESOLUTION=1920x1080
chunked/index-dvr.m3u8?token=abc
"""

_MEDIA_PLAYLIST_WITH_AD = """#EXTM3U
#EXT-X-TARGETDURATION:4
#EXT-X-MEDIA-SEQUENCE:100
#EXT-X-DATERANGE:ID="stitched-ad-1",CLASS="twitch-stitched-ad",START-DATE="2026-08-25T12:00:04.000Z",DURATION=4.0
#EXT-X-PROGRAM-DATE-TIME:2026-08-25T12:00:00.000Z
#EXTINF:4.000,live
seg100.ts
#EXT-X-PROGRAM-DATE-TIME:2026-08-25T12:00:04.000Z
#EXTINF:4.000,Amazon
seg101.ts
#EXT-X-PROGRAM-DATE-TIME:2026-08-25T12:00:08.000Z
#EXTINF:4.000,live
seg102.ts
"""


def test_select_variant_url_picks_highest_bandwidth():
    url = select_variant_url(_MASTER_PLAYLIST, "https://example.invalid/master.m3u8")
    assert url == "https://example.invalid/chunked/index-dvr.m3u8?token=abc"


def test_select_variant_url_falls_back_to_base_url_when_no_variants():
    url = select_variant_url("#EXTM3U\n", "https://example.invalid/master.m3u8")
    assert url == "https://example.invalid/master.m3u8"


def test_parse_media_playlist_flags_ad_by_daterange_and_title():
    segments, target_duration = parse_media_playlist(
        _MEDIA_PLAYLIST_WITH_AD, "https://example.invalid/chunked/"
    )
    assert target_duration == 4.0
    assert [(s.sequence, s.ad) for s in segments] == [(100, False), (101, True), (102, False)]
    assert segments[0].url == "https://example.invalid/chunked/seg100.ts"


def test_parse_media_playlist_returns_empty_for_playlist_with_no_segments():
    segments, _ = parse_media_playlist("#EXTM3U\n#EXT-X-TARGETDURATION:4\n", "https://example.invalid/")
    assert segments == []


def _free_port_probe_ok(url):
    # AdSkipRelay.start() binds to an OS-assigned port - just sanity check
    # the returned URL is well-formed and points at localhost.
    assert url.startswith("http://127.0.0.1:")
    assert url.endswith("/stream.ts")


def test_relay_serves_only_non_ad_segment_bytes_over_http():
    responses = {
        "https://example.invalid/master.m3u8": (_MASTER_PLAYLIST, None),
        "https://example.invalid/chunked/index-dvr.m3u8?token=abc": (_MEDIA_PLAYLIST_WITH_AD, None),
        "https://example.invalid/chunked/seg100.ts": (None, b"CONTENT-100"),
        "https://example.invalid/chunked/seg101.ts": (None, b"AD-101"),
        "https://example.invalid/chunked/seg102.ts": (None, b"CONTENT-102"),
    }

    def fake_fetch(url, timeout=10):
        text, content = responses[url]
        response = Mock()
        response.raise_for_status = Mock()
        response.text = text
        response.content = content
        return response

    log_messages = []
    relay = AdSkipRelay(
        "https://example.invalid/master.m3u8",
        fetch_fn=fake_fetch,
        poll_interval=1000,
        log_fn=log_messages.append,
    )
    local_url = relay.start()
    _free_port_probe_ok(local_url)

    port = int(local_url.split(":")[2].split("/")[0])
    try:
        sock = socket.create_connection(("127.0.0.1", port), timeout=2)
        sock.sendall(b"GET /stream.ts HTTP/1.1\r\nHost: localhost\r\n\r\n")
        sock.settimeout(0.5)
        raw = b""
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            try:
                chunk = sock.recv(4096)
            except socket.timeout:
                chunk = b""
            if chunk:
                raw += chunk
            if b"CONTENT-102" in raw:
                break
        sock.close()

        body = raw.split(b"\r\n\r\n", 1)[1] if b"\r\n\r\n" in raw else b""
        assert body == b"CONTENT-100CONTENT-102"
        assert any("skipped ad segment" in message for message in log_messages)
    finally:
        relay.stop()
