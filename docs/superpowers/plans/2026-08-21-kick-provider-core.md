# Kick Provider Core Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `lib/kick/` package (auth via OAuth 2.1 PKCE, REST API client, stream URL resolution) with the same architectural shape as `lib/twitch/`, fully unit-tested, unused by the rest of the app until later sub-projects wire it in.

**Architecture:** Three pure-Python modules (`auth.py`, `api.py`, `stream.py`) mirroring `lib/twitch/auth.py` / `api.py` / `stream.py` function-for-function where Kick's API allows, plus new hidden addon settings for the Kick client id, PKCE redirect port, and saved token. No `xbmc*` imports anywhere in `lib/kick/` — enforced by extending the existing architecture test.

**Tech Stack:** Python 3, `requests`, stdlib `http.server`/`threading`/`queue`/`secrets`/`hashlib`/`base64` for PKCE + loopback callback capture, `pytest` + `unittest.mock`.

**Spec:** `docs/superpowers/specs/2026-08-21-kick-provider-core-design.md`

## Global Constraints

- No `xbmc*` imports in `lib/kick/*.py` — this package must be importable and testable outside Kodi (spec: "Package layout").
- Kick Public API base URL: `https://api.kick.com/public/v1` (spec: "Background: Kick Public API").
- User Access Tokens only (Authorization Code + PKCE), not App Access Tokens (spec: "Background: Kick Public API").
- Best-effort calls (token refresh) never raise — return `None` and optionally call `on_error`; calls the caller must react to (token exchange, direct API/stream calls) raise (spec: "Error handling").
- Returned user/channel dicts use Twitch's field names (`id`, `login`, `display_name`) even though Kick's API uses different names natively, so later cross-platform code doesn't need to branch (spec: "`api.py`").
- No live network calls in tests (spec: "Testing").

---

### Task 1: Package scaffold + architecture boundary test

**Files:**
- Create: `lib/kick/__init__.py`
- Modify: `tests/test_architecture.py`

**Interfaces:**
- Produces: `lib/kick/` package (empty `__init__.py`) that Tasks 2-4 add modules to.

- [ ] **Step 1: Create the empty package**

```python
# lib/kick/__init__.py
```

(Empty file, matching `lib/twitch/__init__.py`.)

- [ ] **Step 2: Generalize the architecture test to cover both provider packages**

Replace the whole file `tests/test_architecture.py` with:

```python
"""Statically enforces the project's core architectural boundary: lib/twitch/*
and lib/kick/* must never import xbmc-family modules, since they're meant to
run outside Kodi."""
import ast
from pathlib import Path

LIB_DIR = Path(__file__).resolve().parent.parent / "lib"
PROVIDER_DIRS = [LIB_DIR / "twitch", LIB_DIR / "kick"]


def _imported_module_names(py_file):
    tree = ast.parse(py_file.read_text(), filename=str(py_file))
    names = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.append(node.module)
    return names


def test_provider_packages_have_no_xbmc_imports():
    offenders = []
    for provider_dir in PROVIDER_DIRS:
        for py_file in provider_dir.glob("*.py"):
            for name in _imported_module_names(py_file):
                if name == "xbmc" or name.startswith("xbmc."):
                    offenders.append(f"{py_file.relative_to(LIB_DIR)}: imports {name!r}")
    assert not offenders, "lib/twitch/* and lib/kick/* must not import xbmc-family modules:\n" + "\n".join(offenders)
```

- [ ] **Step 3: Run it**

Run: `pytest tests/test_architecture.py -v`
Expected: PASS (the `kick` dir exists with only `__init__.py`, so the glob finds no offenders; the old Twitch-only test name no longer exists so there's no duplicate).

- [ ] **Step 4: Commit**

```bash
git add lib/kick/__init__.py tests/test_architecture.py
git commit -m "chore: scaffold lib/kick package, generalize architecture boundary test"
```

---

### Task 2: PKCE pair generation + authorize URL builder

**Files:**
- Create: `lib/kick/auth.py`
- Test: `tests/kick/test_auth.py`
- Create: `tests/kick/__init__.py`

**Interfaces:**
- Produces: `auth.generate_pkce_pair() -> (code_verifier: str, code_challenge: str)`, `auth.build_authorize_url(client_id, redirect_uri, code_challenge, scopes, state) -> str`, `auth.AUTHORIZE_URL`, `auth.TOKEN_URL`, `auth.SCOPES`.

- [ ] **Step 1: Create the test package init**

```python
# tests/kick/__init__.py
```

- [ ] **Step 2: Write the failing tests**

```python
# tests/kick/test_auth.py
import base64
import hashlib

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
```

- [ ] **Step 3: Run to verify it fails**

Run: `pytest tests/kick/test_auth.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'lib.kick.auth'`

- [ ] **Step 4: Implement**

```python
# lib/kick/auth.py
"""Kick OAuth 2.1 Authorization Code + PKCE flow. No xbmc* imports - pure
Python, pytest-testable."""
import base64
import hashlib
import secrets
from urllib.parse import urlencode

AUTHORIZE_URL = "https://id.kick.com/oauth/authorize"
TOKEN_URL = "https://id.kick.com/oauth/token"
SCOPES = ["user:read", "channel:read", "chat:write"]


def generate_pkce_pair():
    """Return (code_verifier, code_challenge) per RFC 7636 (S256)."""
    verifier = base64.urlsafe_b64encode(secrets.token_bytes(64)).rstrip(b"=").decode("ascii")
    challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest())
        .rstrip(b"=")
        .decode("ascii")
    )
    return verifier, challenge


def build_authorize_url(client_id, redirect_uri, code_challenge, scopes, state):
    """Build the URL the user opens in a browser to approve the app."""
    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": " ".join(scopes),
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
        "state": state,
    }
    return AUTHORIZE_URL + "?" + urlencode(params)
```

- [ ] **Step 5: Run to verify it passes**

Run: `pytest tests/kick/test_auth.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add lib/kick/auth.py tests/kick/__init__.py tests/kick/test_auth.py
git commit -m "feat: add Kick PKCE pair generation and authorize URL builder"
```

---

### Task 3: Loopback callback server

**Files:**
- Modify: `lib/kick/auth.py`
- Modify: `tests/kick/test_auth.py`

**Interfaces:**
- Consumes: nothing new.
- Produces: `auth.await_callback(port, timeout_seconds) -> dict` — starts a loopback HTTP server on `127.0.0.1:port`, blocks until either a request with `code`/`state`/`error` query params arrives or `timeout_seconds` elapses, then returns one of `{"status": "success", "code": ..., "state": ...}`, `{"status": "error", "error": ...}`, `{"status": "timeout"}`. Used by Task 5's orchestrator, which runs it on a background thread so it can be raced against `cancel_event`.

- [ ] **Step 1: Write the failing tests**

```python
# append to tests/kick/test_auth.py
import threading
import time
from urllib.request import urlopen

from lib.kick import auth


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
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest tests/kick/test_auth.py -v -k await_callback`
Expected: FAIL with `AttributeError: module 'lib.kick.auth' has no attribute 'await_callback'`

- [ ] **Step 3: Implement**

```python
# add to lib/kick/auth.py
import queue
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlparse

_CALLBACK_HTML = b"<html><body>You can close this tab and return to Kodi.</body></html>"


class _CallbackHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        params = parse_qs(urlparse(self.path).query)
        if "code" in params:
            self.server.result_queue.put(
                {"status": "success", "code": params["code"][0], "state": params.get("state", [None])[0]}
            )
        elif "error" in params:
            self.server.result_queue.put({"status": "error", "error": params["error"][0]})
        else:
            self.server.result_queue.put({"status": "error", "error": "missing_code"})
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.end_headers()
        self.wfile.write(_CALLBACK_HTML)

    def log_message(self, format, *args):
        pass  # silence BaseHTTPRequestHandler's default stderr logging


def await_callback(port, timeout_seconds):
    """Run a one-shot loopback HTTP server on 127.0.0.1:port, blocking until it
    receives a request carrying `code`/`state` or `error`, or timeout_seconds
    elapses. Returns {"status": "success", "code", "state"} |
    {"status": "error", "error"} | {"status": "timeout"}."""
    server = HTTPServer(("127.0.0.1", port), _CallbackHandler)
    server.result_queue = queue.Queue(maxsize=1)
    server.timeout = timeout_seconds
    try:
        server.handle_request()
        return server.result_queue.get_nowait()
    except queue.Empty:
        return {"status": "timeout"}
    finally:
        server.server_close()
```

- [ ] **Step 4: Run to verify it passes**

Run: `pytest tests/kick/test_auth.py -v -k await_callback`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add lib/kick/auth.py tests/kick/test_auth.py
git commit -m "feat: add Kick OAuth loopback callback server"
```

---

### Task 4: Token exchange, refresh, save/load/clear

**Files:**
- Modify: `lib/kick/auth.py`
- Modify: `tests/kick/test_auth.py`

**Interfaces:**
- Consumes: `auth.TOKEN_URL` (Task 2).
- Produces: `auth.exchange_code_for_token(client_id, redirect_uri, code, code_verifier) -> dict` (raises `requests.RequestException` on failure), `auth.refresh_access_token(client_id, refresh_token, on_error=None) -> dict | None`, `auth.save_token(token, addon)`, `auth.load_token(addon) -> dict | None`, `auth.clear_token(addon)` — all using addon setting id `kick_token`.

- [ ] **Step 1: Write the failing tests**

```python
# append to tests/kick/test_auth.py
import json
from unittest.mock import MagicMock, patch

import pytest
import requests


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
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest tests/kick/test_auth.py -v -k "exchange_code or refresh_access_token or save_load or load_token"`
Expected: FAIL with `AttributeError` for each missing function

- [ ] **Step 3: Implement**

```python
# add to lib/kick/auth.py
import requests


def exchange_code_for_token(client_id, redirect_uri, code, code_verifier):
    """Exchange an authorization code for a token dict. Raises
    requests.RequestException on network/HTTP failure."""
    response = requests.post(
        TOKEN_URL,
        data={
            "grant_type": "authorization_code",
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "code": code,
            "code_verifier": code_verifier,
        },
        timeout=10,
    )
    response.raise_for_status()
    return response.json()


def refresh_access_token(client_id, refresh_token, on_error=None):
    """Exchange a refresh_token for a new token dict. Returns None on any
    failure (network error, non-200, unparseable body) rather than raising -
    mirrors lib.twitch.auth.refresh_access_token's contract."""
    try:
        response = requests.post(
            TOKEN_URL,
            data={
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
                "client_id": client_id,
            },
            timeout=10,
        )
    except requests.RequestException as exc:
        if on_error:
            on_error("network error: " + repr(exc))
        return None
    if response.status_code != 200:
        if on_error:
            on_error("HTTP " + str(response.status_code) + ": " + response.text[:200])
        return None
    try:
        return response.json()
    except ValueError as exc:
        if on_error:
            on_error("unparseable response body: " + repr(exc))
        return None


def save_token(token, addon):
    """Persist a token dict to the addon's hidden kick_token setting."""
    addon.setSetting("kick_token", json.dumps(token))


def load_token(addon):
    """Load a previously saved token dict, or None if none saved / invalid JSON."""
    raw = addon.getSetting("kick_token")
    if not raw:
        return None
    try:
        return json.loads(raw)
    except ValueError:
        return None


def clear_token(addon):
    """Remove the saved token, e.g. after a failed refresh forces re-login."""
    addon.setSetting("kick_token", "")
```

Add `import json` to the top of `lib/kick/auth.py` alongside the other stdlib imports.

- [ ] **Step 4: Run to verify it passes**

Run: `pytest tests/kick/test_auth.py -v`
Expected: PASS (all tests in the file so far)

- [ ] **Step 5: Commit**

```bash
git add lib/kick/auth.py tests/kick/test_auth.py
git commit -m "feat: add Kick token exchange, refresh, and save/load/clear"
```

---

### Task 5: `get_current_user` seam + PKCE login orchestrator

**Files:**
- Create: `lib/kick/api.py` (only `get_current_user`, extended in Task 6)
- Modify: `lib/kick/auth.py`
- Modify: `tests/kick/test_auth.py`
- Create: `tests/kick/test_api.py`

**Interfaces:**
- Consumes: `api.get_current_user(access_token)` (this task, minimal version); `auth.generate_pkce_pair`, `auth.build_authorize_url`, `auth.await_callback`, `auth.exchange_code_for_token`, `auth.save_token` (Tasks 2-4).
- Produces: `auth.run_pkce_login(client_id, redirect_port, addon, on_code, on_status, cancel_event, scopes=SCOPES, await_callback_fn=await_callback, exchange_fn=exchange_code_for_token, get_current_user_fn=None) -> bool`. Callback contract: `on_code(authorize_url)` called once; `on_status(status)` called with one of `"pending"`, `"success"`, `"denied"`, `"error"`. Returns `True` iff login succeeded (token saved).

`lib/kick/api.py` is created here (not deferred to Task 6) because `run_pkce_login` needs `get_current_user` to cache the logged-in user's info onto the token before saving, exactly like `twitch.auth.run_device_code_login` does — the two modules are mutually dependent on this one call, so it can't wait.

- [ ] **Step 1: Write the failing `api.get_current_user` test**

```python
# tests/kick/test_api.py
from unittest.mock import MagicMock, patch

import pytest
import requests

from lib.kick import api


def _response(json_body, status_code=200):
    response = MagicMock()
    response.status_code = status_code
    response.json.return_value = json_body
    if status_code >= 400 and status_code != 401:
        response.raise_for_status.side_effect = requests.HTTPError(response=response)
    else:
        response.raise_for_status.side_effect = None
    return response


def test_get_current_user_normalizes_field_names():
    body = {"data": [{"user_id": 42, "name": "SomeUser"}]}
    with patch.object(api.requests, "get", return_value=_response(body)) as mock_get:
        result = api.get_current_user("token")
    assert result == {"id": "42", "login": "someuser", "display_name": "SomeUser"}
    assert mock_get.call_args.kwargs["headers"]["Authorization"] == "Bearer token"


def test_get_current_user_raises_token_expired_on_401():
    with patch.object(api.requests, "get", return_value=_response({}, status_code=401)):
        with pytest.raises(api.TokenExpiredError):
            api.get_current_user("token")
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest tests/kick/test_api.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'lib.kick.api'`

- [ ] **Step 3: Implement `lib/kick/api.py`**

```python
# lib/kick/api.py
"""Kick Public API calls. No xbmc* imports - pure Python, pytest-testable."""
import requests

API_BASE = "https://api.kick.com/public/v1"


class TokenExpiredError(Exception):
    """Raised when a Kick API call gets HTTP 401 - the access token no longer
    works. Callers decide what to do next (refresh, re-login, etc.)."""


def _headers(access_token):
    return {"Authorization": "Bearer " + access_token}


def _get(url, access_token, params=None):
    response = requests.get(url, headers=_headers(access_token), params=params, timeout=10)
    if response.status_code == 401:
        raise TokenExpiredError()
    response.raise_for_status()
    return response.json()


def get_current_user(access_token):
    """Return the token owner's info as {id, login, display_name}, normalized
    to Twitch's field-naming so downstream code doesn't need to branch on
    platform for basic display."""
    body = _get(API_BASE + "/users", access_token)
    user = body["data"][0]
    return {
        "id": str(user["user_id"]),
        "login": user["name"].lower(),
        "display_name": user["name"],
    }
```

- [ ] **Step 4: Run to verify it passes**

Run: `pytest tests/kick/test_api.py -v`
Expected: PASS

- [ ] **Step 5: Write the failing orchestrator tests**

```python
# append to tests/kick/test_auth.py
import threading


def test_run_pkce_login_success_flow():
    addon = FakeAddon()
    codes_shown = []
    statuses = []

    def fake_await_callback(port, timeout_seconds):
        return {"status": "success", "code": "auth-code", "state": codes_shown[-1][1]}

    def fake_exchange(client_id, redirect_uri, code, code_verifier):
        assert code == "auth-code"
        return {"access_token": "tok", "refresh_token": "ref", "expires_in": 3600}

    def fake_get_current_user(access_token):
        return {"id": "42", "login": "someuser", "display_name": "SomeUser"}

    def on_code(url):
        # state is embedded in the URL as a query param; capture it so the
        # fake callback can "echo" the right one back.
        from urllib.parse import urlparse, parse_qs
        state = parse_qs(urlparse(url).query)["state"][0]
        codes_shown.append((url, state))

    result = auth.run_pkce_login(
        client_id="client-id",
        redirect_port=18922,
        addon=addon,
        on_code=on_code,
        on_status=statuses.append,
        cancel_event=threading.Event(),
        await_callback_fn=fake_await_callback,
        exchange_fn=fake_exchange,
        get_current_user_fn=fake_get_current_user,
    )

    assert result is True
    assert statuses == ["pending", "success"]
    assert len(codes_shown) == 1
    saved = auth.load_token(addon)
    assert saved["access_token"] == "tok"
    assert saved["user_id"] == "42"
    assert saved["login"] == "someuser"
    assert saved["display_name"] == "SomeUser"


def test_run_pkce_login_reports_denied_and_saves_nothing():
    addon = FakeAddon()
    statuses = []

    def fake_await_callback(port, timeout_seconds):
        return {"status": "error", "error": "access_denied"}

    result = auth.run_pkce_login(
        client_id="client-id",
        redirect_port=18923,
        addon=addon,
        on_code=lambda url: None,
        on_status=statuses.append,
        cancel_event=threading.Event(),
        await_callback_fn=fake_await_callback,
        exchange_fn=lambda *a, **k: (_ for _ in ()).throw(AssertionError("should not exchange")),
        get_current_user_fn=lambda token: (_ for _ in ()).throw(AssertionError("should not fetch user")),
    )

    assert result is False
    assert statuses == ["pending", "denied"]
    assert auth.load_token(addon) is None


def test_run_pkce_login_reports_expired_on_timeout():
    addon = FakeAddon()
    statuses = []

    result = auth.run_pkce_login(
        client_id="client-id",
        redirect_port=18924,
        addon=addon,
        on_code=lambda url: None,
        on_status=statuses.append,
        cancel_event=threading.Event(),
        await_callback_fn=lambda port, timeout_seconds: {"status": "timeout"},
        exchange_fn=lambda *a, **k: (_ for _ in ()).throw(AssertionError("should not exchange")),
        get_current_user_fn=lambda token: (_ for _ in ()).throw(AssertionError("should not fetch user")),
    )

    assert result is False
    assert statuses == ["pending", "expired"]


def test_run_pkce_login_reports_error_when_user_fetch_raises():
    addon = FakeAddon()
    statuses = []

    result = auth.run_pkce_login(
        client_id="client-id",
        redirect_port=18925,
        addon=addon,
        on_code=lambda url: None,
        on_status=statuses.append,
        cancel_event=threading.Event(),
        await_callback_fn=lambda port, timeout_seconds: {"status": "success", "code": "c", "state": "s"},
        exchange_fn=lambda *a, **k: {"access_token": "tok", "refresh_token": "ref"},
        get_current_user_fn=lambda token: (_ for _ in ()).throw(RuntimeError("boom")),
    )

    assert result is False
    assert statuses == ["pending", "error"]
    assert auth.load_token(addon) is None


def test_run_pkce_login_returns_false_immediately_if_cancelled_before_start():
    addon = FakeAddon()
    statuses = []
    cancel_event = threading.Event()
    cancel_event.set()

    result = auth.run_pkce_login(
        client_id="client-id",
        redirect_port=18926,
        addon=addon,
        on_code=lambda url: None,
        on_status=statuses.append,
        cancel_event=cancel_event,
        await_callback_fn=lambda port, timeout_seconds: (_ for _ in ()).throw(AssertionError("should not await")),
        exchange_fn=lambda *a, **k: (_ for _ in ()).throw(AssertionError("should not exchange")),
        get_current_user_fn=lambda token: (_ for _ in ()).throw(AssertionError("should not fetch user")),
    )

    assert result is False
```

- [ ] **Step 6: Run to verify it fails**

Run: `pytest tests/kick/test_auth.py -v -k run_pkce_login`
Expected: FAIL with `AttributeError: module 'lib.kick.auth' has no attribute 'run_pkce_login'`

- [ ] **Step 7: Implement `run_pkce_login`**

```python
# add to lib/kick/auth.py
def run_pkce_login(
    client_id,
    redirect_port,
    addon,
    on_code,
    on_status,
    cancel_event,
    scopes=None,
    callback_timeout_seconds=300,
    await_callback_fn=await_callback,
    exchange_fn=exchange_code_for_token,
    get_current_user_fn=None,
):
    """Orchestrates the full PKCE login flow: build the authorize URL, report
    it via on_code, wait for the loopback callback, exchange the code for a
    token, cache the current user onto it, and save. Returns True on success,
    False otherwise. Mirrors lib.twitch.auth.run_device_code_login's
    callback/cancellation contract so login_view.py can drive both flows
    uniformly.

    Unlike the device-code flow there's no polling loop - await_callback_fn
    blocks (with its own timeout) waiting for the loopback server to receive
    the redirect, so cancellation is checked before starting and after the
    callback returns, rather than on every poll tick."""
    if scopes is None:
        scopes = SCOPES
    if get_current_user_fn is None:
        from lib.kick import api

        get_current_user_fn = api.get_current_user

    if cancel_event.is_set():
        return False

    try:
        redirect_uri = f"http://127.0.0.1:{redirect_port}/callback"
        verifier, challenge = generate_pkce_pair()
        state = secrets.token_urlsafe(16)
        url = build_authorize_url(client_id, redirect_uri, challenge, scopes, state)

        on_code(url)
        on_status("pending")

        result = await_callback_fn(redirect_port, callback_timeout_seconds)

        if cancel_event.is_set():
            return False

        status = result["status"]
        if status == "timeout":
            on_status("expired")
            return False
        if status == "error":
            on_status("denied")
            return False

        if result.get("state") != state:
            on_status("error")
            return False

        try:
            token = exchange_fn(client_id, redirect_uri, result["code"], verifier)
        except requests.RequestException:
            on_status("error")
            return False

        if cancel_event.is_set():
            return False

        try:
            user_info = get_current_user_fn(token["access_token"])
        except Exception:
            on_status("error")
            return False

        token["user_id"] = user_info["id"]
        token["login"] = user_info["login"]
        token["display_name"] = user_info["display_name"]

        if cancel_event.is_set():
            return False

        save_token(token, addon)
        on_status("success")
        return True
    except Exception:
        on_status("error")
        return False
```

- [ ] **Step 8: Run to verify it passes**

Run: `pytest tests/kick/test_auth.py -v`
Expected: PASS (all tests in the file)

- [ ] **Step 9: Commit**

```bash
git add lib/kick/auth.py lib/kick/api.py tests/kick/test_auth.py tests/kick/test_api.py
git commit -m "feat: add Kick PKCE login orchestrator and get_current_user"
```

---

### Task 6: `api.py` — channel, live streams, top categories, user lookup

**Files:**
- Modify: `lib/kick/api.py`
- Modify: `tests/kick/test_api.py`

**Interfaces:**
- Consumes: `_get`, `_headers`, `API_BASE`, `TokenExpiredError` (Task 5).
- Produces: `api.get_channel(access_token, slug) -> dict | None`, `api.get_live_streams(access_token, category_id=None, first=20) -> list[dict]`, `api.get_top_categories(access_token, first=20) -> list[{"id","name"}]`, `api.get_user_by_login(access_token, slug) -> {"id","login","display_name"} | None`.

- [ ] **Step 1: Write the failing tests**

```python
# append to tests/kick/test_api.py
def test_get_channel_returns_first_match():
    body = {"data": [{"broadcaster_user_id": 42, "slug": "somechannel", "stream": {"is_live": True, "url": "https://x/stream.m3u8"}}]}
    with patch.object(api.requests, "get", return_value=_response(body)) as mock_get:
        result = api.get_channel("token", "somechannel")
    assert result == body["data"][0]
    assert mock_get.call_args.kwargs["params"] == {"slug": "somechannel"}


def test_get_channel_returns_none_when_not_found():
    with patch.object(api.requests, "get", return_value=_response({"data": []})):
        result = api.get_channel("token", "nosuchchannel")
    assert result is None


def test_get_live_streams_returns_data():
    body = {"data": [{"broadcaster_user_id": 1}, {"broadcaster_user_id": 2}]}
    with patch.object(api.requests, "get", return_value=_response(body)) as mock_get:
        result = api.get_live_streams("token", category_id=5, first=10)
    assert result == body["data"]
    assert mock_get.call_args.kwargs["params"] == {"category_id": 5, "limit": 10}


def test_get_live_streams_omits_category_id_when_none():
    body = {"data": []}
    with patch.object(api.requests, "get", return_value=_response(body)) as mock_get:
        api.get_live_streams("token")
    assert mock_get.call_args.kwargs["params"] == {"limit": 20}


def test_get_top_categories_returns_id_and_name():
    body = {"data": [{"id": 7, "name": "Just Chatting"}, {"id": 8, "name": "Games"}]}
    with patch.object(api.requests, "get", return_value=_response(body)):
        result = api.get_top_categories("token", first=2)
    assert result == [{"id": 7, "name": "Just Chatting"}, {"id": 8, "name": "Games"}]


def test_get_user_by_login_returns_normalized_dict():
    body = {"data": [{"user_id": 9, "name": "SomeUser"}]}
    with patch.object(api.requests, "get", return_value=_response(body)) as mock_get:
        result = api.get_user_by_login("token", "someuser")
    assert result == {"id": "9", "login": "someuser", "display_name": "SomeUser"}
    assert mock_get.call_args.kwargs["params"] == {"slug": "someuser"}


def test_get_user_by_login_returns_none_when_not_found():
    with patch.object(api.requests, "get", return_value=_response({"data": []})):
        result = api.get_user_by_login("token", "nosuchuser")
    assert result is None
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest tests/kick/test_api.py -v -k "get_channel or get_live_streams or get_top_categories or get_user_by_login"`
Expected: FAIL with `AttributeError` for each missing function

- [ ] **Step 3: Implement**

```python
# add to lib/kick/api.py
def get_channel(access_token, slug):
    """Return the channel dict (including live status/stream url under
    "stream") for the given slug, or None if no such channel."""
    body = _get(API_BASE + "/channels", access_token, params={"slug": slug})
    channels = body["data"]
    if not channels:
        return None
    return channels[0]


def get_live_streams(access_token, category_id=None, first=20):
    """Return currently-live streams (GET /livestreams), optionally filtered
    to one category_id."""
    params = {"limit": first}
    if category_id is not None:
        params["category_id"] = category_id
    body = _get(API_BASE + "/livestreams", access_token, params=params)
    return body["data"]


def get_top_categories(access_token, first=20):
    """Return Kick's current top categories as a list of {"id", "name"} dicts."""
    body = _get(API_BASE + "/categories", access_token, params={"limit": first})
    return [{"id": category["id"], "name": category["name"]} for category in body["data"][:first]]


def get_user_by_login(access_token, slug):
    """Return {"id", "login", "display_name"} for the given channel slug, or
    None if no such user."""
    body = _get(API_BASE + "/channels", access_token, params={"slug": slug})
    channels = body["data"]
    if not channels:
        return None
    user = channels[0]
    return {"id": str(user["user_id"]), "login": slug, "display_name": user.get("name", slug)}
```

Note on `get_user_by_login`: reuses `/channels?slug=` since Kick's `/users` endpoint (per `docs.kick.com`, to confirm at coding time) may only support lookup by numeric id, not slug. Revisit field extraction against the real response shape during implementation; the test above pins the expected normalized output regardless of which raw fields it comes from.

- [ ] **Step 4: Run to verify it passes**

Run: `pytest tests/kick/test_api.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add lib/kick/api.py tests/kick/test_api.py
git commit -m "feat: add Kick channel, live streams, categories, and user-lookup calls"
```

---

### Task 7: `api.search_channels` (unofficial fallback, isolated)

**Files:**
- Modify: `lib/kick/api.py`
- Modify: `tests/kick/test_api.py`

**Interfaces:**
- Consumes: nothing beyond `requests`.
- Produces: `api.search_channels(access_token, query, first=20) -> list[dict]`.

- [ ] **Step 1: Write the failing tests**

```python
# append to tests/kick/test_api.py
def test_search_channels_returns_data():
    body = {"data": [{"slug": "somechannel"}, {"slug": "otherchannel"}]}
    with patch.object(api.requests, "get", return_value=_response(body)) as mock_get:
        result = api.search_channels("token", "some", first=5)
    assert result == body["data"]
    assert mock_get.call_args.kwargs["params"] == {"searchQuery": "some", "limit": 5}


def test_search_channels_uses_search_base_not_api_base():
    body = {"data": []}
    with patch.object(api.requests, "get", return_value=_response(body)) as mock_get:
        api.search_channels("token", "query")
    called_url = mock_get.call_args.args[0]
    assert called_url == api.SEARCH_BASE + "/search/channels"
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest tests/kick/test_api.py -v -k search_channels`
Expected: FAIL with `AttributeError: module 'lib.kick.api' has no attribute 'search_channels'`

- [ ] **Step 3: Implement**

```python
# add to lib/kick/api.py
# Kick's official Public API (API_BASE, above) has no confirmed free-text
# channel search endpoint as of this writing. This function is isolated
# specifically so a future correction (confirmed official endpoint, or a
# different unofficial one) only touches this one function - no caller
# needs to change. SEARCH_BASE targets Kick's unauthenticated web search
# endpoint (kick.com), not the Public API host - same precedent as
# lib.twitch.gql's unofficial playback-token lookup.
SEARCH_BASE = "https://kick.com/api/v2"


def search_channels(access_token, query, first=20):
    """Free-text channel search. Unofficial endpoint - confirm against
    docs.kick.com / kick.com's own web client at implementation time and
    adjust the URL/params here if it has changed; callers are unaffected."""
    body = _get(SEARCH_BASE + "/search/channels", access_token, params={"searchQuery": query, "limit": first})
    return body["data"]
```

- [ ] **Step 4: Run to verify it passes**

Run: `pytest tests/kick/test_api.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add lib/kick/api.py tests/kick/test_api.py
git commit -m "feat: add Kick channel search (isolated unofficial-endpoint fallback)"
```

---

### Task 8: `stream.py` — resolve playable URL

**Files:**
- Create: `lib/kick/stream.py`
- Create: `tests/kick/test_stream.py`

**Interfaces:**
- Consumes: `api.get_channel(access_token, slug)` (Task 6).
- Produces: `stream.resolve_stream_url(access_token, channel_slug) -> str` (raises `stream.StreamUnavailableError`).

- [ ] **Step 1: Write the failing tests**

```python
# tests/kick/test_stream.py
from unittest.mock import patch

import pytest

from lib.kick import api, stream


def test_resolve_stream_url_returns_playback_url_when_live():
    channel = {"slug": "somechannel", "stream": {"is_live": True, "url": "https://stream.kick.com/somechannel.m3u8"}}
    with patch.object(api, "get_channel", return_value=channel) as mock_get_channel:
        url = stream.resolve_stream_url("token", "somechannel")
    mock_get_channel.assert_called_once_with("token", "somechannel")
    assert url == "https://stream.kick.com/somechannel.m3u8"


def test_resolve_stream_url_raises_when_channel_not_found():
    with patch.object(api, "get_channel", return_value=None):
        with pytest.raises(stream.StreamUnavailableError):
            stream.resolve_stream_url("token", "nosuchchannel")


def test_resolve_stream_url_raises_when_not_live():
    channel = {"slug": "somechannel", "stream": {"is_live": False, "url": None}}
    with patch.object(api, "get_channel", return_value=channel):
        with pytest.raises(stream.StreamUnavailableError):
            stream.resolve_stream_url("token", "somechannel")


def test_resolve_stream_url_raises_when_url_field_missing():
    channel = {"slug": "somechannel", "stream": {"is_live": True}}
    with patch.object(api, "get_channel", return_value=channel):
        with pytest.raises(stream.StreamUnavailableError):
            stream.resolve_stream_url("token", "somechannel")
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest tests/kick/test_stream.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'lib.kick.stream'`

- [ ] **Step 3: Implement**

```python
# lib/kick/stream.py
"""Resolves a Kick channel slug to a playable HLS URL. No xbmc* imports -
pure Python, pytest-testable."""
from lib.kick import api


class StreamUnavailableError(Exception):
    """Raised when a channel's stream can't be resolved to a playable URL -
    the channel isn't live, doesn't exist, or the API response is missing
    the playback URL."""


def resolve_stream_url(access_token, channel_slug):
    """Return the direct HLS (.m3u8) URL for the given live channel slug.
    Unlike Twitch, Kick's channel API response includes the playback URL
    directly - no separate signed-access-token exchange needed. Raises
    StreamUnavailableError if the channel doesn't exist, isn't live, or the
    response is missing the URL field."""
    channel = api.get_channel(access_token, channel_slug)
    if channel is None:
        raise StreamUnavailableError(channel_slug)
    stream_info = channel.get("stream") or {}
    if not stream_info.get("is_live"):
        raise StreamUnavailableError(channel_slug)
    url = stream_info.get("url")
    if not url:
        raise StreamUnavailableError(channel_slug)
    return url
```

- [ ] **Step 4: Run to verify it passes**

Run: `pytest tests/kick/test_stream.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add lib/kick/stream.py tests/kick/test_stream.py
git commit -m "feat: add Kick stream URL resolution"
```

---

### Task 9: Settings — Kick client id, redirect port, hidden token

**Files:**
- Modify: `resources/settings.xml`
- Modify: `resources/language/resource.language.en_gb/strings.po`
- Modify: `tests/test_settings.py`

**Interfaces:**
- Produces: three new addon settings readable via `addon.getSetting(...)`, matching how `client_id` and `twitch_token` are already read directly in `lib/views/*.py` (no `Settings` class wrapper needed - those two aren't wrapped either).

- [ ] **Step 1: Find the current strings.po path and confirm the next free id**

Run: `grep -n "msgctxt" resources/language/resource.language.en_gb/strings.po | tail -5`
Expected: last id is `#30017` (confirmed during spec research) - new ids start at `#30018`.

- [ ] **Step 2: Add settings to `resources/settings.xml`**

Insert after the existing `<setting id="audio_cycle_remote" ...>` block, before `</group>`:

```xml
        <setting id="kick_client_id" type="string" label="30018" help="">
          <level>2</level>
          <default></default>
          <constraints>
            <allowempty>true</allowempty>
          </constraints>
          <control type="edit" format="string"/>
        </setting>
        <setting id="kick_redirect_port" type="integer" label="30019" help="30021">
          <level>2</level>
          <default>8919</default>
          <control type="edit" format="integer"/>
        </setting>
        <setting id="kick_token" type="string" label="30020" help="">
          <level>2</level>
          <default></default>
          <constraints>
            <allowempty>true</allowempty>
          </constraints>
          <control type="edit" format="string"/>
          <visible>false</visible>
        </setting>
```

- [ ] **Step 3: Add matching strings to `resources/language/resource.language.en_gb/strings.po`**

Append at the end of the file:

```
msgctxt "#30018"
msgid "Kick Client ID"
msgstr ""

msgctxt "#30019"
msgid "Kick OAuth redirect port"
msgstr ""

msgctxt "#30020"
msgid "Kick Token"
msgstr ""

msgctxt "#30021"
msgid "Local port used to receive the OAuth redirect during Kick login. Must match the redirect URI registered with your Kick app (http://127.0.0.1:<port>/callback)."
msgstr ""
```

- [ ] **Step 4: Write a failing test confirming both settings are addon-readable**

```python
# append to tests/test_settings.py
import xbmcaddon


def test_kick_client_id_setting_is_readable_and_defaults_empty():
    addon = xbmcaddon.Addon()
    assert addon.getSetting("kick_client_id") == ""
    addon.setSetting("kick_client_id", "my-kick-client-id")
    assert addon.getSetting("kick_client_id") == "my-kick-client-id"


def test_kick_redirect_port_setting_is_readable():
    addon = xbmcaddon.Addon()
    addon.setSetting("kick_redirect_port", "9000")
    assert addon.getSetting("kick_redirect_port") == "9000"


def test_kick_token_setting_round_trips():
    addon = xbmcaddon.Addon()
    addon.setSetting("kick_token", '{"access_token": "tok"}')
    assert addon.getSetting("kick_token") == '{"access_token": "tok"}'
```

(These exercise the `xbmcaddon` test stub in `tests/kodi_stubs/xbmcaddon.py`, which stores settings in memory by id regardless of what's declared in `settings.xml` - so this test passes even before Step 2/3, but is placed here to document the new setting ids alongside the XML/PO changes and catch future id typos.)

- [ ] **Step 5: Run it**

Run: `pytest tests/test_settings.py -v`
Expected: PASS

- [ ] **Step 6: Run the full addon-manifest test to confirm settings.xml is still well-formed**

Run: `pytest tests/test_addon_manifest.py -v`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add resources/settings.xml resources/language/resource.language.en_gb/strings.po tests/test_settings.py
git commit -m "feat: add Kick client id, redirect port, and token settings"
```

---

### Task 10: Full suite check

**Files:** none (verification only)

- [ ] **Step 1: Run the entire test suite**

Run: `pytest`
Expected: all tests pass, including the pre-existing Twitch/views/windows suites (unaffected by this plan) and every `tests/kick/*` and modified `tests/test_architecture.py` / `tests/test_settings.py` test added above.

- [ ] **Step 2: Confirm no stray xbmc import crept into lib/kick**

Run: `pytest tests/test_architecture.py -v`
Expected: PASS

No commit for this task - it's a verification checkpoint, not a code change.
