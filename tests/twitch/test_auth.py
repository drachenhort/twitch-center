import pytest
from lib.twitch import auth


def test_request_device_code_not_implemented():
    with pytest.raises(NotImplementedError):
        auth.request_device_code("client-id")


def test_poll_for_token_not_implemented():
    with pytest.raises(NotImplementedError):
        auth.poll_for_token("client-id", "device-code", 5)


def test_load_token_returns_none_when_no_token_saved():
    assert auth.load_token() is None
