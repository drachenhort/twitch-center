"""IRC chat client for irc.chat.twitch.tv. No xbmc* imports - pure Python, pytest-testable."""


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
