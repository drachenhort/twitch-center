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
