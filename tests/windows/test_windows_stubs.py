from lib.windows.home import HomeWindow
from lib.windows.discover import DiscoverWindow
from lib.windows.chat_overlay import ChatOverlay
from lib.windows.chat_window import ChatWindow


def test_home_window_constructs():
    win = HomeWindow("home.xml", "/tmp")
    win.onInit()


def test_discover_window_constructs():
    win = DiscoverWindow("discover.xml", "/tmp")
    win.onInit()


class _FakeChatClient:
    def __init__(self, channel):
        self.channel = channel

    def connect(self):
        pass

    def read_messages(self):
        return iter([])

    def disconnect(self):
        pass


def test_chat_overlay_constructs():
    overlay = ChatOverlay("chat_overlay.xml", "/tmp", channel="somechannel", chat_client_cls=_FakeChatClient)
    overlay.onInit()
    overlay._thread.join(timeout=1)


def test_chat_window_constructs():
    win = ChatWindow("chat_window.xml", "/tmp")
    win.onInit()
