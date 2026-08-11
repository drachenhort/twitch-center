from lib.windows.home import HomeWindow
from lib.windows.discover import DiscoverWindow
from lib.windows.player import play_stream
from lib.windows.chat_overlay import ChatOverlay
from lib.windows.chat_window import ChatWindow


def test_home_window_constructs():
    win = HomeWindow("home.xml", "/tmp")
    win.onInit()


def test_discover_window_constructs():
    win = DiscoverWindow("discover.xml", "/tmp")
    win.onInit()


def test_chat_overlay_constructs():
    overlay = ChatOverlay("chat_overlay.xml", "/tmp")
    overlay.onInit()


def test_chat_window_constructs():
    win = ChatWindow("chat_window.xml", "/tmp")
    win.onInit()


def test_play_stream_is_stubbed():
    import pytest
    with pytest.raises(NotImplementedError):
        play_stream("https://example.invalid/stream.m3u8")
