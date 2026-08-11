import pytest
from lib.twitch import irc


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
