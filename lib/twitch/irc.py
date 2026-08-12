"""IRC chat client for irc.chat.twitch.tv. No xbmc* imports - pure Python, pytest-testable."""
import time


def _parse_tags(tag_str):
    tags = {}
    for pair in tag_str.split(";"):
        if not pair:
            continue
        key, _, value = pair.partition("=")
        tags[key] = value
    return tags


def parse_line(line, now_ms=None):
    """Parse one raw Twitch IRC line into an event dict.

    Returns one of:
      {"type": "message", "username", "display_name", "text", "timestamp"}
      {"type": "raid", "from_channel", "display_name", "viewer_count", "timestamp"}
      {"type": "raw", "line"}
    PING is deliberately not handled here - the caller must check for it
    before calling parse_line, since it requires a direct socket reply
    rather than a queue event."""
    if now_ms is None:
        now_ms = int(time.time() * 1000)

    rest = line
    tags = {}
    if rest.startswith("@"):
        tag_part, _, rest = rest.partition(" ")
        tags = _parse_tags(tag_part[1:])

    prefix = ""
    if rest.startswith(":"):
        prefix_part, _, rest = rest.partition(" ")
        prefix = prefix_part[1:]

    if " :" in rest:
        head, _, trailing = rest.partition(" :")
    else:
        head, trailing = rest, ""

    command = head.split()[0] if head.split() else ""
    timestamp = int(tags["tmi-sent-ts"]) if "tmi-sent-ts" in tags else now_ms

    if command == "PRIVMSG":
        username = prefix.split("!")[0] if "!" in prefix else prefix
        return {
            "type": "message",
            "username": username,
            "display_name": tags.get("display-name", username),
            "text": trailing,
            "timestamp": timestamp,
        }

    if command == "USERNOTICE" and tags.get("msg-id") == "raid":
        try:
            viewer_count = int(tags.get("msg-param-viewerCount", "0"))
        except ValueError:
            viewer_count = 0
        return {
            "type": "raid",
            "from_channel": tags.get("msg-param-login", ""),
            "display_name": tags.get("msg-param-displayName", ""),
            "viewer_count": viewer_count,
            "timestamp": timestamp,
        }

    return {"type": "raw", "line": line}


class ChatClient:
    def __init__(self, channel):
        self.channel = channel

    def connect(self):
        """Open the IRC socket connection and authenticate."""
        raise NotImplementedError

    def read_messages(self):
        """Yield chat message dicts (at least: username, message, timestamp) as they arrive."""
        raise NotImplementedError

    def disconnect(self):
        """Close the IRC socket connection."""
        raise NotImplementedError
