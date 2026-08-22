import base64
import hashlib
import threading
import time
from urllib.request import urlopen

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
