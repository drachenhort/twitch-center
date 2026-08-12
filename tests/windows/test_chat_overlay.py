from unittest.mock import patch

from lib.windows.chat_overlay import ChatOverlay


class FakeChatClient:
    instances = []

    def __init__(self, channel):
        self.channel = channel
        self.connected = False
        self.disconnected = False
        self._events = []
        FakeChatClient.instances.append(self)

    def connect(self):
        self.connected = True

    def read_messages(self):
        return iter(self._events)

    def disconnect(self):
        self.disconnected = True


def _message_event(username, text, index=0):
    return {
        "type": "message",
        "username": username,
        "display_name": username.capitalize(),
        "text": text,
        "timestamp": index,
    }


def test_oninit_constructs_client_lazily_and_connects_it():
    FakeChatClient.instances.clear()
    win = ChatOverlay(
        "script-twitch-center-chat-overlay.xml",
        "/tmp",
        "Default",
        "1080i",
        channel="somechannel",
        chat_client_cls=FakeChatClient,
    )
    # The client isn't constructed until onInit runs (matches every other
    # window in this codebase - construction happens in onInit, not __init__).
    assert FakeChatClient.instances == []

    win.onInit()
    win._thread.join(timeout=1)
    assert not win._thread.is_alive()

    assert len(FakeChatClient.instances) == 1
    client = FakeChatClient.instances[0]
    assert client.channel == "somechannel"
    assert client.connected is True


def test_pump_renders_messages_and_ignores_status_and_raid_events():
    FakeChatClient.instances.clear()

    class ClientWithMessages(FakeChatClient):
        def __init__(self, channel):
            super().__init__(channel)
            self._events = [
                _message_event("bob", "hello", 1),
                {"type": "status", "state": "connected"},
                _message_event("carol", "hi there", 2),
                {"type": "raid", "from_channel": "x", "display_name": "X", "viewer_count": 5, "timestamp": 3},
            ]

    win = ChatOverlay(
        "script-twitch-center-chat-overlay.xml",
        "/tmp",
        "Default",
        "1080i",
        channel="somechannel",
        chat_client_cls=ClientWithMessages,
    )
    win.onInit()
    win._thread.join(timeout=1)
    assert not win._thread.is_alive()

    control = win.getControl(ChatOverlay.MESSAGE_LIST_ID)
    assert control.size() == 2
    assert control._items[0].getLabel() == "Bob"
    assert control._items[0].getLabel2() == "hello"
    assert control._items[1].getLabel() == "Carol"
    assert control._items[1].getLabel2() == "hi there"


def test_pump_caps_message_list_at_fifty_dropping_oldest():
    FakeChatClient.instances.clear()

    class ClientWithManyMessages(FakeChatClient):
        def __init__(self, channel):
            super().__init__(channel)
            self._events = [_message_event("user", "msg%d" % i, i) for i in range(60)]

    win = ChatOverlay(
        "script-twitch-center-chat-overlay.xml",
        "/tmp",
        "Default",
        "1080i",
        channel="somechannel",
        chat_client_cls=ClientWithManyMessages,
    )
    win.onInit()
    win._thread.join(timeout=1)
    assert not win._thread.is_alive()

    control = win.getControl(ChatOverlay.MESSAGE_LIST_ID)
    assert control.size() == 50
    assert control._items[0].getLabel2() == "msg10"
    assert control._items[-1].getLabel2() == "msg59"


def test_pump_selects_last_item_so_new_messages_are_visible_past_the_fold():
    FakeChatClient.instances.clear()

    class ClientWithManyMessages(FakeChatClient):
        def __init__(self, channel):
            super().__init__(channel)
            self._events = [_message_event("user", "msg%d" % i, i) for i in range(20)]

    win = ChatOverlay(
        "script-twitch-center-chat-overlay.xml",
        "/tmp",
        "Default",
        "1080i",
        channel="somechannel",
        chat_client_cls=ClientWithManyMessages,
    )
    win.onInit()
    win._thread.join(timeout=1)
    assert not win._thread.is_alive()

    control = win.getControl(ChatOverlay.MESSAGE_LIST_ID)
    assert control.getSelectedItem().getLabel2() == "msg19"


def test_pump_thread_logs_and_exits_cleanly_on_unexpected_exception():
    FakeChatClient.instances.clear()

    class ExplodingClient(FakeChatClient):
        def read_messages(self):
            def _gen():
                yield _message_event("bob", "hi", 1)
                raise RuntimeError("boom")
            return _gen()

    with patch("lib.windows.chat_overlay.xbmc.log") as mock_log:
        win = ChatOverlay(
            "script-twitch-center-chat-overlay.xml",
            "/tmp",
            "Default",
            "1080i",
            channel="somechannel",
            chat_client_cls=ExplodingClient,
        )
        win.onInit()
        win._thread.join(timeout=1)

    assert not win._thread.is_alive()
    mock_log.assert_called_once()


def test_close_disconnects_client_and_is_idempotent():
    FakeChatClient.instances.clear()
    win = ChatOverlay(
        "script-twitch-center-chat-overlay.xml",
        "/tmp",
        "Default",
        "1080i",
        channel="somechannel",
        chat_client_cls=FakeChatClient,
    )
    win.onInit()
    win._thread.join(timeout=1)
    assert not win._thread.is_alive()

    win.close()
    win.close()  # must not raise

    client = FakeChatClient.instances[0]
    assert client.disconnected is True
