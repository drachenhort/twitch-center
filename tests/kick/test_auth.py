import base64
import hashlib
import json
import threading
import time
from unittest.mock import MagicMock, patch
from urllib.request import urlopen

import pytest
import requests

from lib.kick import auth


def test_scopes_include_chat_write():
    assert "chat:write" in auth.SCOPES


def test_generate_pkce_pair_challenge_matches_verifier():
    verifier, challenge = auth.generate_pkce_pair()
    assert 43 <= len(verifier) <= 128
    expected_challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest())
        .rstrip(b"=")
        .decode("ascii")
    )
    assert challenge == expected_challenge


def test_generate_pkce_pair_is_random_each_call():
    verifier_a, _ = auth.generate_pkce_pair()
    verifier_b, _ = auth.generate_pkce_pair()
    assert verifier_a != verifier_b


def test_build_authorize_url_contains_required_params():
    url = auth.build_authorize_url(
        client_id="client-123",
        redirect_uri="http://127.0.0.1:8919/callback",
        code_challenge="challenge-abc",
        scopes=["user:read", "chat:write"],
        state="state-xyz",
    )
    assert url.startswith(auth.AUTHORIZE_URL + "?")
    assert "client_id=client-123" in url
    assert "redirect_uri=http%3A%2F%2F127.0.0.1%3A8919%2Fcallback" in url
    assert "code_challenge=challenge-abc" in url
    assert "code_challenge_method=S256" in url
    assert "response_type=code" in url
    assert "scope=user%3Aread+chat%3Awrite" in url
    assert "state=state-xyz" in url


def test_await_callback_captures_code_and_state():
    port = 18919
    result_holder = {}

    def run():
        result_holder["result"] = auth.await_callback(port, timeout_seconds=5)

    thread = threading.Thread(target=run)
    thread.start()
    time.sleep(0.2)  # let the server bind before we hit it
    urlopen(f"http://127.0.0.1:{port}/callback?code=abc123&state=xyz")
    thread.join(timeout=5)

    assert result_holder["result"] == {"status": "success", "code": "abc123", "state": "xyz"}


def test_await_callback_captures_error_param():
    port = 18920
    result_holder = {}

    def run():
        result_holder["result"] = auth.await_callback(port, timeout_seconds=5)

    thread = threading.Thread(target=run)
    thread.start()
    time.sleep(0.2)
    urlopen(f"http://127.0.0.1:{port}/callback?error=access_denied")
    thread.join(timeout=5)

    assert result_holder["result"] == {"status": "error", "error": "access_denied"}


def test_await_callback_times_out_when_nothing_arrives():
    port = 18921
    result = auth.await_callback(port, timeout_seconds=0.5)
    assert result == {"status": "timeout"}


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


def test_exchange_code_for_token_returns_parsed_response():
    body = {"access_token": "tok", "refresh_token": "ref", "expires_in": 3600}
    with patch.object(auth.requests, "post", return_value=_fake_response(body)) as mock_post:
        result = auth.exchange_code_for_token("client-id", "http://127.0.0.1:8919/callback", "code123", "verifier123")
    assert result == body
    data = mock_post.call_args.kwargs["data"]
    assert data == {
        "grant_type": "authorization_code",
        "client_id": "client-id",
        "redirect_uri": "http://127.0.0.1:8919/callback",
        "code": "code123",
        "code_verifier": "verifier123",
    }


def test_exchange_code_for_token_raises_on_http_error():
    with patch.object(auth.requests, "post", return_value=_fake_response({}, status_code=400)):
        with pytest.raises(requests.RequestException):
            auth.exchange_code_for_token("client-id", "redirect", "code", "verifier")


def test_refresh_access_token_returns_new_token_on_success():
    body = {"access_token": "new-tok", "refresh_token": "new-ref", "expires_in": 3600}
    with patch.object(auth.requests, "post", return_value=_fake_response(body)):
        result = auth.refresh_access_token("client-id", "old-ref")
    assert result == body


def test_refresh_access_token_returns_none_and_calls_on_error_on_network_failure():
    errors = []
    with patch.object(auth.requests, "post", side_effect=requests.RequestException("boom")):
        result = auth.refresh_access_token("client-id", "old-ref", on_error=errors.append)
    assert result is None
    assert "network error" in errors[0]


def test_refresh_access_token_returns_none_on_non_200():
    with patch.object(auth.requests, "post", return_value=_fake_response({}, status_code=401)):
        result = auth.refresh_access_token("client-id", "old-ref")
    assert result is None


def test_save_load_clear_token_round_trip():
    addon = FakeAddon()
    token = {"access_token": "tok", "refresh_token": "ref"}
    auth.save_token(token, addon)
    assert auth.load_token(addon) == token
    auth.clear_token(addon)
    assert auth.load_token(addon) is None


def test_load_token_returns_none_for_invalid_json():
    addon = FakeAddon()
    addon.setSetting("kick_token", "not-json")
    assert auth.load_token(addon) is None
