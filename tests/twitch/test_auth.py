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
    user_info = {"id": "999", "login": "someuser", "display_name": "SomeUser"}

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
        get_current_user_fn=lambda access_token, client_id: user_info,
    )

    assert result is True
    assert codes == [("ABCD-1234", "https://www.twitch.tv/activate")]
    assert statuses[-1] == "success"
    saved = auth.load_token(addon)
    assert saved["access_token"] == "tok"
    assert saved["user_id"] == "999"
    assert saved["login"] == "someuser"
    assert saved["display_name"] == "SomeUser"


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


def test_run_device_code_login_cancelled_during_poll_does_not_save_token():
    addon = FakeAddon()
    cancel_event = threading.Event()
    device_info = {
        "device_code": "dc1",
        "user_code": "ABCD-1234",
        "verification_uri": "https://www.twitch.tv/activate",
        "expires_in": 1800,
        "interval": 5,
    }

    def poll_fn(client_id, device_code):
        # Simulate cancellation happening while the network call was in flight.
        cancel_event.set()
        return {"status": "success", "token": {"access_token": "x"}}

    result = auth.run_device_code_login(
        "client-id",
        ["user:read:follows"],
        addon,
        on_code=lambda code, uri: None,
        on_status=lambda status: None,
        cancel_event=cancel_event,
        sleep_fn=lambda seconds: None,
        request_fn=lambda client_id, scopes: device_info,
        poll_fn=poll_fn,
    )

    assert result is False
    assert auth.load_token(addon) is None


def test_run_device_code_login_default_wait_uses_cancel_event_and_is_instant():
    """With no sleep_fn/wait_fn override, the production default (cancel_event.wait)
    must be used - proven here by pre-setting cancel_event so the wait returns
    immediately instead of blocking for the real interval, keeping the test fast."""
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
        request_fn=lambda client_id, scopes: device_info,
        poll_fn=lambda client_id, device_code: {"status": "pending"},
    )

    assert result is False


def test_run_device_code_login_unexpected_exception_reports_error():
    addon = FakeAddon()
    statuses = []
    device_info = {
        "device_code": "dc1",
        "user_code": "ABCD-1234",
        "verification_uri": "https://www.twitch.tv/activate",
        "expires_in": 1800,
        "interval": 5,
    }

    def bad_poll_fn(client_id, device_code):
        raise KeyError("malformed response")

    result = auth.run_device_code_login(
        "client-id",
        ["user:read:follows"],
        addon,
        on_code=lambda code, uri: None,
        on_status=lambda status: statuses.append(status),
        cancel_event=threading.Event(),
        sleep_fn=lambda seconds: None,
        request_fn=lambda client_id, scopes: device_info,
        poll_fn=bad_poll_fn,
    )

    assert result is False
    assert statuses[-1] == "error"


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


def test_run_device_code_login_caches_user_info_on_success():
    addon = FakeAddon()
    device_info = {
        "device_code": "dc1",
        "user_code": "ABCD-1234",
        "verification_uri": "https://www.twitch.tv/activate",
        "expires_in": 1800,
        "interval": 5,
    }
    token = {"access_token": "tok", "refresh_token": "ref"}
    user_info = {"id": "999", "login": "someuser", "display_name": "SomeUser"}

    result = auth.run_device_code_login(
        "client-id",
        ["user:read:follows"],
        addon,
        on_code=lambda code, uri: None,
        on_status=lambda status: None,
        cancel_event=threading.Event(),
        sleep_fn=lambda seconds: None,
        request_fn=lambda client_id, scopes: device_info,
        poll_fn=lambda client_id, device_code: {"status": "success", "token": dict(token)},
        get_current_user_fn=lambda access_token, client_id: user_info,
    )

    assert result is True
    saved = auth.load_token(addon)
    assert saved["access_token"] == "tok"
    assert saved["user_id"] == "999"
    assert saved["login"] == "someuser"
    assert saved["display_name"] == "SomeUser"


def test_run_device_code_login_reports_error_when_user_info_fetch_fails():
    addon = FakeAddon()
    statuses = []
    device_info = {
        "device_code": "dc1",
        "user_code": "ABCD-1234",
        "verification_uri": "https://www.twitch.tv/activate",
        "expires_in": 1800,
        "interval": 5,
    }

    def failing_get_current_user(access_token, client_id):
        raise requests.ConnectionError("boom")

    result = auth.run_device_code_login(
        "client-id",
        ["user:read:follows"],
        addon,
        on_code=lambda code, uri: None,
        on_status=lambda status: statuses.append(status),
        cancel_event=threading.Event(),
        sleep_fn=lambda seconds: None,
        request_fn=lambda client_id, scopes: device_info,
        poll_fn=lambda client_id, device_code: {
            "status": "success",
            "token": {"access_token": "tok"},
        },
        get_current_user_fn=failing_get_current_user,
    )

    assert result is False
    assert statuses[-1] == "error"
    assert auth.load_token(addon) is None


def test_refresh_access_token_success():
    new_token = {"access_token": "new-tok", "refresh_token": "new-ref", "expires_in": 14400}
    with patch.object(auth.requests, "post", return_value=_fake_response(new_token)):
        result = auth.refresh_access_token("client-id", "old-ref")
    assert result == new_token


def test_refresh_access_token_returns_none_on_http_error():
    with patch.object(auth.requests, "post", return_value=_fake_response({}, status_code=400)):
        result = auth.refresh_access_token("client-id", "old-ref")
    assert result is None


def test_refresh_access_token_returns_none_on_network_error():
    with patch.object(auth.requests, "post", side_effect=requests.ConnectionError("boom")):
        result = auth.refresh_access_token("client-id", "old-ref")
    assert result is None


def test_refresh_access_token_reports_http_error_reason_via_on_error():
    response = _fake_response({}, status_code=401)
    response.text = "invalid refresh token"
    reasons = []
    with patch.object(auth.requests, "post", return_value=response):
        result = auth.refresh_access_token("client-id", "old-ref", on_error=reasons.append)
    assert result is None
    assert len(reasons) == 1
    assert "401" in reasons[0]
    assert "invalid refresh token" in reasons[0]


def test_refresh_access_token_reports_network_error_reason_via_on_error():
    reasons = []
    with patch.object(auth.requests, "post", side_effect=requests.ConnectionError("boom")):
        result = auth.refresh_access_token("client-id", "old-ref", on_error=reasons.append)
    assert result is None
    assert len(reasons) == 1
    assert "network error" in reasons[0]
    assert "boom" in reasons[0]


def test_clear_token_removes_saved_token():
    addon = FakeAddon()
    auth.save_token({"access_token": "tok"}, addon)
    assert auth.load_token(addon) is not None
    auth.clear_token(addon)
    assert auth.load_token(addon) is None
