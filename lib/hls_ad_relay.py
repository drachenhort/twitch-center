"""Local HTTP relay that strips Twitch's stitched ad segments out of a live
HLS stream before handing it to Kodi's player. No xbmc* imports - pure
Python, pytest-testable, modeled on how streamlink's Twitch plugin detects
and drops ad segments (see docs/superpowers plans/memory for the research).

Kodi's native player can't do this itself: inputstream.adaptive/Kodi fetch
HLS segments internally with no per-segment hook for us to filter on. This
relay instead does its own segment-fetch loop against Twitch's live media
playlist, skips segments flagged as ads, and re-serves the rest as one
continuous raw MPEG-TS byte stream over localhost - Kodi just plays that
plain HTTP URL like any IPTV channel, no HLS parsing involved on its end.

Two ad-detection signals, same as streamlink: an EXT-X-DATERANGE tag with
CLASS="twitch-stitched-ad" (or an ID starting with "stitched-ad-") marks a
time range as an ad break - segments whose EXT-X-PROGRAM-DATE-TIME falls in
that range are skipped; independently, any segment whose EXTINF title
contains "Amazon" is also treated as an ad, since Twitch often tags ad
segments that way regardless of date-range coverage."""
import queue
import re
import socketserver
import threading
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler
from urllib.parse import urljoin

import requests

_STREAM_INF_RE = re.compile(r"#EXT-X-STREAM-INF:(?P<attrs>.*)")
_DATERANGE_RE = re.compile(r"#EXT-X-DATERANGE:(?P<attrs>.*)")
_EXTINF_RE = re.compile(r"#EXTINF:(?P<duration>[^,]*),?(?P<title>.*)")
_ATTR_RE = re.compile(r'([A-Z0-9-]+)=("(?:[^"\\]|\\.)*"|[^,]*)')

_DEFAULT_POLL_INTERVAL = 2.0
_QUEUE_MAXSIZE = 30


def _parse_attrs(raw):
    attrs = {}
    for match in _ATTR_RE.finditer(raw):
        key, value = match.group(1), match.group(2)
        if value.startswith('"') and value.endswith('"'):
            value = value[1:-1]
        attrs[key] = value
    return attrs


def _parse_iso8601(value):
    # datetime.fromisoformat (even pre-3.11) handles Twitch's
    # EXT-X-PROGRAM-DATE-TIME/DATERANGE timestamps once a trailing "Z" is
    # swapped for an explicit zero UTC offset - Kodi's bundled Python version
    # varies by release, so don't rely on 3.11+'s looser "Z" handling.
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    return datetime.fromisoformat(value)


def select_variant_url(master_playlist_text, base_url):
    """Returns the highest-bandwidth variant's media playlist URL from a
    master playlist, or base_url itself if no EXT-X-STREAM-INF variants are
    found (already a media playlist, or unparseable - fail open rather than
    block playback)."""
    best_bandwidth = -1
    best_uri = None
    lines = master_playlist_text.splitlines()
    for i, line in enumerate(lines):
        match = _STREAM_INF_RE.match(line)
        if not match:
            continue
        attrs = _parse_attrs(match.group("attrs"))
        try:
            bandwidth = int(attrs.get("BANDWIDTH", 0))
        except ValueError:
            bandwidth = 0
        uri = None
        for next_line in lines[i + 1:]:
            next_line = next_line.strip()
            if next_line and not next_line.startswith("#"):
                uri = next_line
                break
        if uri is not None and bandwidth > best_bandwidth:
            best_bandwidth = bandwidth
            best_uri = uri
    if best_uri is None:
        return base_url
    return urljoin(base_url, best_uri)


class Segment:
    def __init__(self, sequence, url, ad):
        self.sequence = sequence
        self.url = url
        self.ad = ad

    def __repr__(self):
        return "Segment(sequence=%r, ad=%r)" % (self.sequence, self.ad)

    def __eq__(self, other):
        return (
            isinstance(other, Segment)
            and self.sequence == other.sequence
            and self.url == other.url
            and self.ad == other.ad
        )


def parse_media_playlist(playlist_text, base_url):
    """Returns (segments, target_duration) for a Twitch media playlist.
    segments is a list of Segment, in playlist order, each flagged .ad based
    on the two signals described in this module's docstring."""
    ad_ranges = []  # list of (start, end) datetimes
    target_duration = _DEFAULT_POLL_INTERVAL
    media_sequence = 0
    current_date = None
    current_title = ""
    segments = []
    index = 0

    for line in playlist_text.splitlines():
        line = line.strip()
        if not line:
            continue

        if line.startswith("#EXT-X-TARGETDURATION:"):
            try:
                target_duration = float(line.split(":", 1)[1])
            except ValueError:
                pass
            continue

        if line.startswith("#EXT-X-MEDIA-SEQUENCE:"):
            try:
                media_sequence = int(line.split(":", 1)[1])
            except ValueError:
                pass
            continue

        if line.startswith("#EXT-X-PROGRAM-DATE-TIME:"):
            try:
                current_date = _parse_iso8601(line.split(":", 1)[1])
            except ValueError:
                current_date = None
            continue

        match = _DATERANGE_RE.match(line)
        if match:
            attrs = _parse_attrs(match.group("attrs"))
            class_name = attrs.get("CLASS", "")
            range_id = attrs.get("ID", "")
            if class_name == "twitch-stitched-ad" or range_id.startswith("stitched-ad-"):
                try:
                    start = _parse_iso8601(attrs["START-DATE"])
                    duration = float(attrs.get("DURATION", 0))
                    ad_ranges.append((start, start + timedelta(seconds=duration)))
                except (KeyError, ValueError):
                    pass
            continue

        match = _EXTINF_RE.match(line)
        if match:
            current_title = match.group("title") or ""
            continue

        if line.startswith("#"):
            continue

        # A non-comment, non-empty line at this point is a segment URI.
        is_ad = "amazon" in current_title.lower()
        if not is_ad and current_date is not None:
            is_ad = any(start <= current_date < end for start, end in ad_ranges)
        segments.append(Segment(media_sequence + index, urljoin(base_url, line), is_ad))
        index += 1
        current_title = ""

    return segments, target_duration


class _RelayHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass

    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "video/mp2t")
        self.end_headers()
        try:
            self.server.relay.stream_to(self.wfile)
        except (BrokenPipeError, ConnectionResetError):
            pass


class _RelayServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
    daemon_threads = True
    allow_reuse_address = True


class AdSkipRelay:
    """Owns the fetch loop and local HTTP server for one playback session.
    Not reusable - construct a fresh instance per play_stream() call."""

    def __init__(self, master_url, fetch_fn=None, poll_interval=None, log_fn=None):
        self._master_url = master_url
        self._fetch = fetch_fn or requests.get
        self._poll_interval = poll_interval
        self._log = log_fn or (lambda message: None)
        self._stop_event = threading.Event()
        self._queue = queue.Queue(maxsize=_QUEUE_MAXSIZE)
        self._fetch_thread = None
        self._server = None
        self._server_thread = None

    def start(self):
        """Starts the fetch loop and local HTTP server, returning the local
        URL Kodi's player should be pointed at."""
        self._server = _RelayServer(("127.0.0.1", 0), _RelayHandler)
        self._server.relay = self
        self._server_thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._server_thread.start()

        self._fetch_thread = threading.Thread(target=self._run, daemon=True)
        self._fetch_thread.start()

        port = self._server.server_address[1]
        return "http://127.0.0.1:%d/stream.ts" % port

    def stop(self):
        self._stop_event.set()
        if self._fetch_thread is not None:
            self._fetch_thread.join(timeout=5)
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()

    def stream_to(self, wfile):
        """Drains the segment-bytes queue to wfile until stop() is called or
        the client disconnects. Called from the HTTP handler thread."""
        while not self._stop_event.is_set():
            try:
                chunk = self._queue.get(timeout=1)
            except queue.Empty:
                continue
            wfile.write(chunk)
            wfile.flush()

    def _run(self):
        try:
            master_response = self._fetch(self._master_url, timeout=10)
            master_response.raise_for_status()
            variant_url = select_variant_url(master_response.text, self._master_url)
        except requests.RequestException as exc:
            self._log("master playlist fetch failed (%r), using master URL directly" % exc)
            variant_url = self._master_url

        last_sequence_seen = -1
        skipped_count = 0
        while not self._stop_event.is_set():
            try:
                response = self._fetch(variant_url, timeout=10)
                response.raise_for_status()
                segments, target_duration = parse_media_playlist(response.text, variant_url)
            except requests.RequestException as exc:
                self._log("playlist reload failed (%r), retrying" % exc)
                self._stop_event.wait(_DEFAULT_POLL_INTERVAL)
                continue

            for segment in segments:
                if segment.sequence <= last_sequence_seen:
                    continue
                last_sequence_seen = segment.sequence
                if segment.ad:
                    skipped_count += 1
                    self._log(
                        "skipped ad segment #%d (sequence %d)" % (skipped_count, segment.sequence)
                    )
                    continue
                try:
                    segment_response = self._fetch(segment.url, timeout=10)
                    segment_response.raise_for_status()
                except requests.RequestException as exc:
                    self._log("segment fetch failed (%r), dropping it" % exc)
                    continue
                try:
                    self._queue.put(segment_response.content, timeout=1)
                except queue.Full:
                    self._log("output queue full, dropping segment %d" % segment.sequence)

            self._stop_event.wait(self._poll_interval or target_duration)
