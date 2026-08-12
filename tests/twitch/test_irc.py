import threading

from lib.twitch.irc import ChatClient, parse_line


class FakeSocket:
    """Records sent bytes, replays queued recv() results. A queued item that
    is an Exception instance is raised instead of returned."""

    def __init__(self, recv_queue=None):
        self._recv_queue = list(recv_queue or [])
        self.sent = []
        self.closed = False

    def sendall(self, data):
        self.sent.append(data.decode("utf-8"))

    def recv(self, bufsize):
        if not self._recv_queue:
            return b""
        item = self._recv_queue.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    def close(self):
        self.closed = True


def test_connect_sends_anonymous_login_and_join():
    fake = FakeSocket()
    client = ChatClient("somechannel", socket_factory=lambda: fake, sleep_fn=lambda s: None)
    client.connect()
    try:
        # Handshake happens synchronously at the start of the background
        # thread, before it blocks on recv() - give it a moment to run.
        for _ in range(100):
            if len(fake.sent) >= 4:
                break
            threading.Event().wait(0.01)
    finally:
        client.disconnect()

    assert "CAP REQ :twitch.tv/tags twitch.tv/commands\r\n" in fake.sent
    assert "PASS SCHMOOPIIE\r\n" in fake.sent
    assert any(s.startswith("NICK justinfan") for s in fake.sent)
    assert "JOIN #somechannel\r\n" in fake.sent


def test_disconnect_is_safe_to_call_twice():
    fake = FakeSocket()
    client = ChatClient("somechannel", socket_factory=lambda: fake, sleep_fn=lambda s: None)
    client.connect()
    client.disconnect()
    client.disconnect()  # must not raise


def test_parse_line_privmsg_with_tags():
    line = (
        "@display-name=Bob;tmi-sent-ts=1000 "
        ":bob!bob@bob.tmi.twitch.tv PRIVMSG #somechannel :hello there"
    )
    event = parse_line(line)
    assert event == {
        "type": "message",
        "username": "bob",
        "display_name": "Bob",
        "text": "hello there",
        "timestamp": 1000,
    }


def test_parse_line_privmsg_without_display_name_tag_falls_back_to_username():
    line = ":carol!carol@carol.tmi.twitch.tv PRIVMSG #somechannel :hi"
    event = parse_line(line, now_ms=5000)
    assert event["username"] == "carol"
    assert event["display_name"] == "carol"
    assert event["timestamp"] == 5000


def test_parse_line_unrecognized_command_is_raw_passthrough():
    line = ":tmi.twitch.tv 001 justinfan12345 :Welcome, GLHF!"
    event = parse_line(line)
    assert event == {"type": "raw", "line": line}


def test_parse_line_join_is_raw_passthrough():
    line = ":justinfan12345!justinfan12345@justinfan12345.tmi.twitch.tv JOIN #somechannel"
    event = parse_line(line)
    assert event == {"type": "raw", "line": line}


def test_parse_line_usernotice_raid():
    line = (
        "@msg-id=raid;msg-param-displayName=CoolRaider;msg-param-login=coolraider;"
        "msg-param-viewerCount=42;tmi-sent-ts=2000 "
        ":tmi.twitch.tv USERNOTICE #somechannel :CoolRaider is raiding with 42 viewers!"
    )
    event = parse_line(line)
    assert event == {
        "type": "raid",
        "from_channel": "coolraider",
        "display_name": "CoolRaider",
        "viewer_count": 42,
        "timestamp": 2000,
    }


def test_parse_line_usernotice_non_raid_is_raw_passthrough():
    line = "@msg-id=sub;tmi-sent-ts=3000 :tmi.twitch.tv USERNOTICE #somechannel :Dave subscribed!"
    event = parse_line(line)
    assert event == {"type": "raw", "line": line}


def test_parse_line_raid_with_non_numeric_viewer_count_defaults_to_zero():
    line = (
        "@msg-id=raid;msg-param-displayName=CoolRaider;msg-param-login=coolraider;"
        "msg-param-viewerCount=not-a-number "
        ":tmi.twitch.tv USERNOTICE #somechannel :raiding!"
    )
    event = parse_line(line, now_ms=9000)
    assert event["type"] == "raid"
    assert event["viewer_count"] == 0
    assert event["timestamp"] == 9000


def test_parse_line_privmsg_with_non_numeric_timestamp_tag_falls_back_to_now_ms():
    line = (
        "@display-name=Bob;tmi-sent-ts=not-a-number "
        ":bob!bob@bob.tmi.twitch.tv PRIVMSG #somechannel :hello there"
    )
    event = parse_line(line, now_ms=7000)
    assert event["type"] == "message"
    assert event["timestamp"] == 7000


def test_read_messages_yields_connected_status_then_privmsg():
    line = "@display-name=Bob;tmi-sent-ts=1000 :bob!bob@bob.tmi.twitch.tv PRIVMSG #chan :hello\r\n"
    fake = FakeSocket(recv_queue=[line.encode("utf-8")])
    client = ChatClient("chan", socket_factory=lambda: fake, sleep_fn=lambda s: None)
    client.connect()

    events = []
    for event in client.read_messages():
        events.append(event)
        if event["type"] == "message":
            break
    client.disconnect()

    assert events[0] == {"type": "status", "state": "connected"}
    assert events[1] == {
        "type": "message",
        "username": "bob",
        "display_name": "Bob",
        "text": "hello",
        "timestamp": 1000,
    }


def test_reconnects_with_backoff_after_socket_error():
    good_line = ":a!a@a PRIVMSG #chan :hi\r\n".encode("utf-8")
    sockets = [
        FakeSocket(recv_queue=[ConnectionError("boom")]),
        FakeSocket(recv_queue=[good_line]),
    ]
    factory_calls = iter(sockets)
    sleeps = []
    client = ChatClient(
        "chan",
        socket_factory=lambda: next(factory_calls),
        sleep_fn=lambda seconds: sleeps.append(seconds),
    )
    client.connect()

    events = []
    for event in client.read_messages():
        events.append(event)
        if event["type"] == "message":
            break
    client.disconnect()

    states = [e["state"] for e in events if e["type"] == "status"]
    assert states == ["connected", "disconnected", "connected"]
    assert events[-1]["type"] == "message"
    assert sleeps == [1]


def test_backoff_doubles_on_consecutive_failures():
    sockets = [
        FakeSocket(recv_queue=[ConnectionError("boom")]),
        FakeSocket(recv_queue=[ConnectionError("boom again")]),
        FakeSocket(recv_queue=[":a!a@a PRIVMSG #chan :hi\r\n".encode("utf-8")]),
    ]
    factory_calls = iter(sockets)
    sleeps = []
    client = ChatClient(
        "chan",
        socket_factory=lambda: next(factory_calls),
        sleep_fn=lambda seconds: sleeps.append(seconds),
    )
    client.connect()

    for event in client.read_messages():
        if event["type"] == "message":
            break
    client.disconnect()

    assert sleeps == [1, 2]


def test_ping_is_answered_with_pong_and_not_queued():
    # Follow the PING with a real PRIVMSG so the test has a deterministic
    # stopping point after confirming PING was handled.
    privmsg = ":a!a@a PRIVMSG #chan :after ping\r\n"
    fake = FakeSocket(recv_queue=[b"PING :tmi.twitch.tv\r\n", privmsg.encode("utf-8")])
    client = ChatClient("chan", socket_factory=lambda: fake, sleep_fn=lambda s: None)
    client.connect()

    events = []
    for event in client.read_messages():
        events.append(event)
        if event["type"] == "message":
            break
    client.disconnect()

    assert [e["type"] for e in events] == ["status", "message"]
    assert "PONG :tmi.twitch.tv\r\n" in fake.sent
