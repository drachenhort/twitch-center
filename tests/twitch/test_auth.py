import threading
from unittest.mock import patch, MagicMock

import pytest
import requests

from lib.twitch import auth


class FakeAddon:
    def __init__(self):
        self._settings = {}

    def setSetting(self, id, value):
        self._settings[id] = value

    def getSetting(self, id):
        return self._settings.get(id, "")


def _fake_response(json_body, status_code=200):
    response = MagicMock()
    response.status_code = status_code
    response.json.return_value = json_body
    if status_code >= 400:
        response.raise_for_status.side_effect = requests.HTTPError(response=response)
    else:
        response.raise_for_status.side_effect = None
    return response


def test_request_device_code_returns_parsed_response():
    body = {
        "device_code": "abc123",
        "user_code": "ABCD-1234",
        "verification_uri": "https://www.twitch.tv/activate",
        "expires_in": 1800,
        "interval": 5,
    }
    with patch.object(auth.requests, "post", return_value=_fake_response(body)) as mock_post:
        result = auth.request_device_code("client-id", ["user:read:follows"])
    assert result == body
    called_data = mock_post.call_args.kwargs["data"]
    assert called_data["client_id"] == "client-id"
    assert called_data["scopes"] == "user:read:follows"


def test_request_device_code_raises_on_http_error():
    with patch.object(auth.requests, "post", return_value=_fake_response({}, status_code=500)):
        with pytest.raises(requests.RequestException):
            auth.request_device_code("client-id", ["user:read:follows"])


def test_poll_device_code_once_success():
    token_body = {"access_token": "tok", "refresh_token": "ref", "expires_in": 14400}
    with patch.object(auth.requests, "post", return_value=_fake_response(token_body)):
        result = auth.poll_device_code_once("client-id", "device-code")
    assert result == {"status": "success", "token": token_body}


def test_poll_device_code_once_authorization_pending():
    body = {"message": "authorization_pending"}
    with patch.object(auth.requests, "post", return_value=_fake_response(body, status_code=400)):
        result = auth.poll_device_code_once("client-id", "device-code")
    assert result == {"status": "pending"}


def test_poll_device_code_once_slow_down():
    body = {"message": "slow_down"}
    with patch.object(auth.requests, "post", return_value=_fake_response(body, status_code=400)):
        result = auth.poll_device_code_once("client-id", "device-code")
    assert result == {"status": "slow_down"}


def test_poll_device_code_once_expired():
    body = {"message": "expired_token"}
    with patch.object(auth.requests, "post", return_value=_fake_response(body, status_code=400)):
        result = auth.poll_device_code_once("client-id", "device-code")
    assert result == {"status": "expired"}


def test_poll_device_code_once_success_with_bad_json_treated_as_pending():
    response = _fake_response({})
    response.json.side_effect = ValueError("bad json")
    with patch.object(auth.requests, "post", return_value=response):
        result = auth.poll_device_code_once("client-id", "device-code")
    assert result == {"status": "pending"}


def test_poll_device_code_once_network_error_treated_as_pending():
    with patch.object(auth.requests, "post", side_effect=requests.ConnectionError("boom")):
        result = auth.poll_device_code_once("client-id", "device-code")
    assert result == {"status": "pending"}


def test_save_and_load_token_round_trip():
    addon = FakeAddon()
    token = {"access_token": "tok", "refresh_token": "ref"}
    auth.save_token(token, addon)
    assert auth.load_token(addon) == token


def test_load_token_returns_none_when_unset():
    addon = FakeAddon()
    assert auth.load_token(addon) is None


def test_load_token_returns_none_when_garbage():
    addon = FakeAddon()
    addon.setSetting("twitch_token", "not json")
    assert auth.load_token(addon) is None


def test_run_device_code_login_success_flow():
    addon = FakeAddon()
    codes = []
    statuses = []
    device_info = {
        "device_code": "dc1",
        "user_code": "ABCD-1234",
        "verification_uri": "https://www.twitch.tv/activate",
        "expires_in": 1800,
        "interval": 5,
    }
    token = {"access_token": "tok"}
    poll_results = iter([{"status": "pending"}, {"status": "success", "token": token}])

    result = auth.run_device_code_login(
        "client-id",
        ["user:read:follows"],
        addon,
        on_code=lambda code, uri: codes.append((code, uri)),
        on_status=lambda status: statuses.append(status),
        cancel_event=threading.Event(),
        sleep_fn=lambda seconds: None,
        request_fn=lambda client_id, scopes: device_info,
        poll_fn=lambda client_id, device_code: next(poll_results),
    )

    assert result is True
    assert codes == [("ABCD-1234", "https://www.twitch.tv/activate")]
    assert statuses[-1] == "success"
    assert auth.load_token(addon) == token


def test_run_device_code_login_cancel_stops_before_saving_token():
    addon = FakeAddon()
    cancel_event = threading.Event()
    cancel_event.set()
    device_info = {
        "device_code": "dc1",
        "user_code": "ABCD-1234",
        "verification_uri": "https://www.twitch.tv/activate",
        "expires_in": 1800,
        "interval": 5,
    }

    result = auth.run_device_code_login(
        "client-id",
        ["user:read:follows"],
        addon,
        on_code=lambda code, uri: None,
        on_status=lambda status: None,
        cancel_event=cancel_event,
        sleep_fn=lambda seconds: None,
        request_fn=lambda client_id, scopes: device_info,
        poll_fn=lambda client_id, device_code: {"status": "success", "token": {"access_token": "x"}},
    )

    assert result is False
    assert auth.load_token(addon) is None


def test_run_device_code_login_expired_stops_and_reports():
    addon = FakeAddon()
    statuses = []
    device_info = {
        "device_code": "dc1",
        "user_code": "ABCD-1234",
        "verification_uri": "https://www.twitch.tv/activate",
        "expires_in": 5,
        "interval": 5,
    }

    result = auth.run_device_code_login(
        "client-id",
        ["user:read:follows"],
        addon,
        on_code=lambda code, uri: None,
        on_status=lambda status: statuses.append(status),
        cancel_event=threading.Event(),
        sleep_fn=lambda seconds: None,
        request_fn=lambda client_id, scopes: device_info,
        poll_fn=lambda client_id, device_code: {"status": "expired"},
    )

    assert result is False
    assert "expired" in statuses


def test_run_device_code_login_request_failure_reports_error():
    addon = FakeAddon()
    statuses = []

    def failing_request(client_id, scopes):
        raise requests.ConnectionError("boom")

    result = auth.run_device_code_login(
        "client-id",
        ["user:read:follows"],
        addon,
        on_code=lambda code, uri: None,
        on_status=lambda status: statuses.append(status),
        cancel_event=threading.Event(),
        sleep_fn=lambda seconds: None,
        request_fn=failing_request,
        poll_fn=lambda client_id, device_code: {"status": "pending"},
    )

    assert result is False
    assert statuses == ["error"]
