from unittest.mock import patch

import requests

from lib.hls_playlist import Quality, fetch_qualities, parse_qualities

_TWITCH_STYLE_PLAYLIST = """#EXTM3U
#EXT-X-MEDIA:TYPE=VIDEO,GROUP-ID="chunked",NAME="1080p60 (Source)",AUTOSELECT=YES,DEFAULT=YES
#EXT-X-STREAM-INF:BANDWIDTH=6000000,CODECS="avc1.64002A",RESOLUTION=1920x1080,VIDEO="chunked",FRAME-RATE=60.000
https://example.invalid/chunked/index-dvr.m3u8?token=abc
#EXT-X-MEDIA:TYPE=VIDEO,GROUP-ID="720p60",NAME="720p60",AUTOSELECT=YES,DEFAULT=YES
#EXT-X-STREAM-INF:BANDWIDTH=3000000,CODECS="avc1.4D401F",RESOLUTION=1280x720,VIDEO="720p60",FRAME-RATE=60.000
720p60/index-dvr.m3u8?token=abc
#EXT-X-MEDIA:TYPE=AUDIO,GROUP-ID="audio_only",NAME="Audio Only",AUTOSELECT=NO,DEFAULT=NO
#EXT-X-STREAM-INF:BANDWIDTH=200000,CODECS="mp4a.40.2",VIDEO="audio_only"
audio_only/index-dvr.m3u8?token=abc
"""


def test_parse_qualities_orders_by_bandwidth_highest_first():
    qualities = parse_qualities(_TWITCH_STYLE_PLAYLIST, "https://example.invalid/master.m3u8")
    assert [q.name for q in qualities] == ["1080p60 (Source)", "720p60", "200000"]


def test_parse_qualities_resolves_relative_uris_against_base_url():
    qualities = parse_qualities(_TWITCH_STYLE_PLAYLIST, "https://example.invalid/master.m3u8")
    by_name = {q.name: q.url for q in qualities}
    assert by_name["1080p60 (Source)"] == "https://example.invalid/chunked/index-dvr.m3u8?token=abc"
    assert by_name["720p60"] == "https://example.invalid/720p60/index-dvr.m3u8?token=abc"


def test_parse_qualities_returns_empty_list_for_playlist_with_no_variants():
    assert parse_qualities("#EXTM3U\n", "https://example.invalid/master.m3u8") == []


def test_quality_equality():
    assert Quality("Source", "u") == Quality("Source", "u")
    assert Quality("Source", "u") != Quality("720p", "u")


def test_fetch_qualities_returns_empty_list_on_request_failure():
    with patch("lib.hls_playlist.requests.get", side_effect=requests.RequestException("boom")):
        assert fetch_qualities("https://example.invalid/master.m3u8") == []


def test_fetch_qualities_parses_successful_response():
    class FakeResponse:
        text = _TWITCH_STYLE_PLAYLIST

        def raise_for_status(self):
            pass

    with patch("lib.hls_playlist.requests.get", return_value=FakeResponse()):
        qualities = fetch_qualities("https://example.invalid/master.m3u8")
    assert [q.name for q in qualities] == ["1080p60 (Source)", "720p60", "200000"]
