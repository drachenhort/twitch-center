import pytest
from lib.twitch import irc
from lib.twitch.irc import parse_line


def test_chat_client_connect_not_implemented():
    client = irc.ChatClient("some_channel")
    with pytest.raises(NotImplementedError):
        client.connect()


def test_chat_client_read_messages_not_implemented():
    client = irc.ChatClient("some_channel")
    with pytest.raises(NotImplementedError):
        next(client.read_messages())


def test_chat_client_disconnect_not_implemented():
    client = irc.ChatClient("some_channel")
    with pytest.raises(NotImplementedError):
        client.disconnect()


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
