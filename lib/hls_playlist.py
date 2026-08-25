"""Parses an HLS master playlist into a list of playable quality variants.
No xbmc* imports - pure Python, pytest-testable. Shared between Twitch and
Kick since both serve standard HLS master playlists."""
import re
from urllib.parse import urljoin

import requests

_MEDIA_RE = re.compile(r'#EXT-X-MEDIA:(?P<attrs>.*)')
_STREAM_INF_RE = re.compile(r'#EXT-X-STREAM-INF:(?P<attrs>.*)')
_ATTR_RE = re.compile(r'([A-Z0-9-]+)=("(?:[^"\\]|\\.)*"|[^,]*)')


class Quality:
    def __init__(self, name, url):
        self.name = name
        self.url = url

    def __repr__(self):
        return "Quality(name=%r, url=%r)" % (self.name, self.url)

    def __eq__(self, other):
        return isinstance(other, Quality) and self.name == other.name and self.url == other.url


def _parse_attrs(raw):
    attrs = {}
    for match in _ATTR_RE.finditer(raw):
        key, value = match.group(1), match.group(2)
        if value.startswith('"') and value.endswith('"'):
            value = value[1:-1]
        attrs[key] = value
    return attrs


def parse_qualities(playlist_text, base_url):
    """Return the master playlist's variants as a list of Quality(name, url),
    highest bandwidth first. `name` prefers the human-readable EXT-X-MEDIA
    NAME (e.g. Twitch's "1080p60 (Source)") associated with a variant's
    VIDEO group, falling back to its RESOLUTION or BANDWIDTH when no such
    group exists. base_url resolves the playlist's (usually relative) URIs
    to absolute ones."""
    group_names = {}
    for match in _MEDIA_RE.finditer(playlist_text):
        attrs = _parse_attrs(match.group("attrs"))
        if attrs.get("TYPE") == "VIDEO" and "GROUP-ID" in attrs and "NAME" in attrs:
            group_names[attrs["GROUP-ID"]] = attrs["NAME"]

    variants = []
    lines = playlist_text.splitlines()
    for i, line in enumerate(lines):
        match = _STREAM_INF_RE.match(line)
        if not match:
            continue
        attrs = _parse_attrs(match.group("attrs"))
        uri = None
        for next_line in lines[i + 1:]:
            next_line = next_line.strip()
            if next_line and not next_line.startswith("#"):
                uri = next_line
                break
        if uri is None:
            continue

        name = group_names.get(attrs.get("VIDEO"))
        if not name:
            name = attrs.get("RESOLUTION") or attrs.get("BANDWIDTH") or "Unknown"

        try:
            bandwidth = int(attrs.get("BANDWIDTH", 0))
        except ValueError:
            bandwidth = 0

        variants.append((bandwidth, Quality(name, urljoin(base_url, uri))))

    variants.sort(key=lambda pair: pair[0], reverse=True)
    return [quality for _bandwidth, quality in variants]


def fetch_qualities(master_url, timeout=10):
    """Fetches and parses master_url's variants. Returns [] on any network
    failure or if the playlist has no parseable variants - best-effort, same
    discipline as lib/twitch/gql.py."""
    try:
        response = requests.get(master_url, timeout=timeout)
        response.raise_for_status()
    except requests.RequestException:
        return []
    return parse_qualities(response.text, master_url)
