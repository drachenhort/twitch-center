from unittest.mock import patch

from lib.windows.chat_overlay import ChatOverlay


class FakeChatClient:
    instances = []

    def __init__(self, channel, access_token=None, client_id=None, broadcaster_user_id=None,
                 user_id=None):
        self.channel = channel
        self.access_token = access_token
        self.client_id = client_id
        self.broadcaster_user_id = broadcaster_user_id
        self.user_id = user_id
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


def test_oninit_forwards_engine_credentials_to_chat_client_cls():
    FakeChatClient.instances.clear()
    win = ChatOverlay(
        "script-twitch-center-chat-overlay.xml",
        "/tmp",
        "Default",
        "1080i",
        channel="somechannel",
        access_token="tok",
        client_id="cid",
        broadcaster_user_id="123",
        user_id="456",
        chat_client_cls=FakeChatClient,
    )
    win.onInit()
    win._thread.join(timeout=1)

    client = FakeChatClient.instances[0]
    assert client.access_token == "tok"
    assert client.client_id == "cid"
    assert client.broadcaster_user_id == "123"
    assert client.user_id == "456"


def test_pump_renders_messages_and_ignores_status_and_raid_events():
    FakeChatClient.instances.clear()

    class ClientWithMessages(FakeChatClient):
        def __init__(self, channel, **kwargs):
            super().__init__(channel, **kwargs)
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


def test_pump_wraps_long_messages_onto_multiple_lines():
    FakeChatClient.instances.clear()

    long_text = "or just download grimstash and make the item LOLW seriously it works great"

    class ClientWithLongMessage(FakeChatClient):
        def __init__(self, channel, **kwargs):
            super().__init__(channel, **kwargs)
            self._events = [_message_event("user", long_text, 1)]

    win = ChatOverlay(
        "script-twitch-center-chat-overlay.xml",
        "/tmp",
        "Default",
        "1080i",
        channel="somechannel",
        chat_client_cls=ClientWithLongMessage,
    )
    win.onInit()
    win._thread.join(timeout=1)
    assert not win._thread.is_alive()

    control = win.getControl(ChatOverlay.MESSAGE_LIST_ID)
    rendered = control._items[0].getLabel2()
    assert "\n" in rendered
    assert all(len(line) <= 26 for line in rendered.split("\n"))
    assert len(rendered.split("\n")) <= 5


def test_pump_truncates_messages_that_would_wrap_past_the_label_height():
    FakeChatClient.instances.clear()

    # Long enough to wrap to more than 5 lines at the 26-char wrap width.
    long_text = (
        "which upcoming games are you looking forward to for the rest of this year, "
        "modz? asking because I want to plan my backlog around the big releases"
    )

    class ClientWithVeryLongMessage(FakeChatClient):
        def __init__(self, channel, **kwargs):
            super().__init__(channel, **kwargs)
            self._events = [_message_event("user", long_text, 1)]

    win = ChatOverlay(
        "script-twitch-center-chat-overlay.xml",
        "/tmp",
        "Default",
        "1080i",
        channel="somechannel",
        chat_client_cls=ClientWithVeryLongMessage,
    )
    win.onInit()
    win._thread.join(timeout=1)
    assert not win._thread.is_alive()

    control = win.getControl(ChatOverlay.MESSAGE_LIST_ID)
    rendered = control._items[0].getLabel2()
    lines = rendered.split("\n")
    assert len(lines) == 5
    assert lines[-1].endswith("...")


def test_pump_caps_message_list_at_fifty_dropping_oldest():
    FakeChatClient.instances.clear()

    class ClientWithManyMessages(FakeChatClient):
        def __init__(self, channel, **kwargs):
            super().__init__(channel, **kwargs)
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
        def __init__(self, channel, **kwargs):
            super().__init__(channel, **kwargs)
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


def test_pump_throttles_rendering_under_rapid_messages_but_flushes_final_state():
    # A busy channel (thousands of chatters) can deliver several messages a
    # second - rendering (control.reset()+addItems()) on every single one
    # floods the GUI thread. This proves the throttle actually skips
    # mid-burst renders while still ending up with the fully correct final
    # state (nothing lost, just coalesced).
    FakeChatClient.instances.clear()

    class ClientWithManyMessages(FakeChatClient):
        def __init__(self, channel, **kwargs):
            super().__init__(channel, **kwargs)
            self._events = [_message_event("user", "msg%d" % i, i) for i in range(5)]

    # All 5 messages arrive well within one throttle window (0.25s apart is
    # the real threshold; these are all 0.01s apart), so only the first
    # should render immediately - the rest should be coalesced into the
    # final flush after the loop ends.
    fake_times = iter([0.00, 0.01, 0.02, 0.03, 0.04])

    win = ChatOverlay(
        "script-twitch-center-chat-overlay.xml",
        "/tmp",
        "Default",
        "1080i",
        channel="somechannel",
        chat_client_cls=ClientWithManyMessages,
        time_fn=lambda: next(fake_times),
    )
    render_call_sizes = []
    real_render = win._render

    def counting_render():
        render_call_sizes.append(len(win._messages))
        real_render()

    win._render = counting_render
    win.onInit()
    win._thread.join(timeout=1)
    assert not win._thread.is_alive()

    # Only the first message's immediate render, plus the final flush -
    # not one render per message.
    assert render_call_sizes == [1, 5]

    control = win.getControl(ChatOverlay.MESSAGE_LIST_ID)
    assert control.size() == 5
    assert control._items[-1].getLabel2() == "msg4"


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
