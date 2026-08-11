# Home Screen Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace `lib/windows/home.py`'s no-op stub with a real Home screen showing the user's
followed Twitch channels (live ones first), implement `lib/twitch/api.py`'s Helix calls for real,
and add token refresh to `lib/twitch/auth.py` so a session survives past the ~4-hour access-token
expiry without forcing re-login.

**Architecture:** `lib/twitch/api.py` gets real Helix HTTP calls (pure Python, `client_id` +
bearer-token headers on every call, raises `TokenExpiredError` on 401, nothing else special-cased —
other failures propagate as ordinary `requests` exceptions for the caller to handle).
`lib/twitch/auth.py` gets `refresh_access_token`/`clear_token`, and `run_device_code_login` is
extended to cache the logged-in user's id/login/display_name onto the token right after login.
`lib/windows/home.py` owns the refresh-then-reprompt retry policy and all UI rendering; `api.py`
and `auth.py` stay ignorant of each other's retry/UI concerns.

**Tech Stack:** Python 3, `requests`, `pytest` + `unittest.mock`, existing `tests/kodi_stubs/`
harness (extended with list-control support).

## Global Constraints

- `lib/twitch/*` must have zero `xbmc*` imports — enforced by `tests/test_architecture.py`; this
  plan does not touch that test, and none of `api.py`/`auth.py`'s new code should need to.
- `lib/windows/*` and `lib/settings.py` remain the only modules allowed to import
  `xbmc`/`xbmcgui`/`xbmcaddon`.
- Every Helix call needs both `Authorization: Bearer <access_token>` and a `Client-Id` header —
  this is why `api.py`'s functions all take `client_id` as an explicit parameter (a signature
  addition over the original scaffold's guessed signatures).
- `get_live_status` must not silently truncate beyond Twitch's 100-`user_id`-per-request cap —
  split into chunks of 100, concatenate results.
- `api.py` raises `TokenExpiredError` only on HTTP 401; all other failures (network errors,
  non-401 HTTP errors, malformed responses) propagate as ordinary exceptions for the caller.
- Token refresh (`refresh_access_token`) returns `None` on any failure rather than raising —
  matches `poll_device_code_once`'s "expected failure modes don't raise" style.
- `pip install -r requirements-dev.txt && pytest` must pass after every task.
- No test makes a real network call to Twitch.

---

## File Structure

```
lib/
  twitch/
    api.py                    # modify: real implementation
    auth.py                   # modify: add refresh_access_token, clear_token; extend run_device_code_login
  windows/
    home.py                   # modify: real implementation
resources/
  skins/Default/1080i/
    script-twitch-center-home.xml   # modify: real list layout + empty/error/re-login states
tests/
  kodi_stubs/
    xbmcgui.py                 # modify: add list-control (addItems/reset/size/getSelectedItem) and ListItem support
  twitch/
    test_api.py                # modify: rewritten with mocks
    test_auth.py                # modify: add tests for new/extended functions
  windows/
    test_home_window.py         # create
```

---

### Task 1: Extend Kodi stubs with list-control support

**Files:**
- Modify: `tests/kodi_stubs/xbmcgui.py`
- Test: `tests/test_kodi_stubs.py`

**Interfaces:**
- Produces: `xbmcgui.ControlLabel` gains `addItems(items) -> None`, `reset() -> None`,
  `size() -> int`, `getSelectedItem() -> ListItem | None` (returns the item at index 0 if any
  exist, else `None` — no real selection/focus tracking needed for this plan since nothing reads
  clicks yet). `xbmcgui.ListItem(label="") -> ListItem` with `.setLabel(text)`, `.getLabel()`,
  `.setLabel2(text)`, `.getLabel2()`, `.setArt(art_dict)`, `.getArt(key) -> str`,
  `.setProperty(key, value)`, `.getProperty(key) -> str`.
- Consumed by: Task 4's `lib/windows/home.py`.

- [ ] **Step 1: Write the failing test**

```python
# Append to tests/test_kodi_stubs.py

def test_xbmcgui_stub_listitem_label_and_label2():
    import xbmcgui
    item = xbmcgui.ListItem("Channel Name")
    assert item.getLabel() == "Channel Name"
    item.setLabel2("playing Foo")
    assert item.getLabel2() == "playing Foo"


def test_xbmcgui_stub_listitem_art_and_properties():
    import xbmcgui
    item = xbmcgui.ListItem("Channel Name")
    item.setArt({"thumb": "https://example.invalid/thumb.jpg"})
    assert item.getArt("thumb") == "https://example.invalid/thumb.jpg"
    assert item.getArt("missing") == ""
    item.setProperty("broadcaster_id", "12345")
    assert item.getProperty("broadcaster_id") == "12345"
    assert item.getProperty("missing") == ""


def test_xbmcgui_stub_control_additems_reset_size_and_selection():
    import xbmcgui
    win = xbmcgui.WindowXML("dummy.xml", "/tmp")
    control = win.getControl(101)
    assert control.size() == 0
    assert control.getSelectedItem() is None
    item1 = xbmcgui.ListItem("First")
    item2 = xbmcgui.ListItem("Second")
    control.addItems([item1, item2])
    assert control.size() == 2
    assert control.getSelectedItem() is item1
    control.reset()
    assert control.size() == 0
    assert control.getSelectedItem() is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_kodi_stubs.py -v`
Expected: FAIL — `xbmcgui.ListItem` doesn't exist yet, and `ControlLabel` has no `addItems`.

- [ ] **Step 3: Update `tests/kodi_stubs/xbmcgui.py`** (add to the existing file; keep `Action`,
`WindowXML`, `WindowXMLDialog` unchanged)

```python
class ListItem:
    def __init__(self, label=""):
        self._label = label
        self._label2 = ""
        self._art = {}
        self._properties = {}

    def setLabel(self, text):
        self._label = text

    def getLabel(self):
        return self._label

    def setLabel2(self, text):
        self._label2 = text

    def getLabel2(self):
        return self._label2

    def setArt(self, art):
        self._art.update(art)

    def getArt(self, key):
        return self._art.get(key, "")

    def setProperty(self, key, value):
        self._properties[key] = value

    def getProperty(self, key):
        return self._properties.get(key, "")


class ControlLabel:
    def __init__(self):
        self._label = ""
        self._items = []

    def setLabel(self, text):
        self._label = text

    def getLabel(self):
        return self._label

    def addItems(self, items):
        self._items.extend(items)

    def reset(self):
        self._items = []

    def size(self):
        return len(self._items)

    def getSelectedItem(self):
        return self._items[0] if self._items else None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_kodi_stubs.py -v`
Expected: PASS (10 tests: 7 existing + 3 new).

- [ ] **Step 5: Run the full suite**

Run: `.venv/bin/pytest -v`
Expected: PASS (all existing tests still green — purely additive).

- [ ] **Step 6: Commit**

```bash
git add tests/kodi_stubs/xbmcgui.py tests/test_kodi_stubs.py
git commit -m "test: add list-control and ListItem support to xbmcgui stub"
```

---

### Task 2: Implement `lib/twitch/api.py`

**Files:**
- Modify: `lib/twitch/api.py`
- Modify: `tests/twitch/test_api.py`

**Interfaces:**
- Produces:
  - `api.TokenExpiredError(Exception)` — raised by any Helix call below on HTTP 401.
  - `api.get_current_user(access_token, client_id) -> dict` — `{"id": ..., "login": ...,
    "display_name": ...}` from Helix `/users`' first `data` element.
  - `api.get_followed_channels(access_token, client_id, user_id) -> list[dict]` — Helix
    `/channels/followed`, follows pagination to completion, returns the concatenated `data` list.
  - `api.get_live_status(access_token, client_id, user_ids) -> list[dict]` — Helix `/streams`,
    chunks `user_ids` into groups of 100, concatenates results.
  - `get_games_for_channels`, `get_live_streams_by_game`, `search_channels` are **not** touched by
    this task — they stay `NotImplementedError` stubs (Discover screen is out of scope).
- Consumed by: Task 3's `auth.py` (`get_current_user`), Task 4's `home.py` (all three).

- [ ] **Step 1: Write the failing tests**

```python
# tests/twitch/test_api.py (full replacement)
from unittest.mock import MagicMock, patch

import pytest
import requests

from lib.twitch import api


def _response(json_body, status_code=200):
    response = MagicMock()
    response.status_code = status_code
    response.json.return_value = json_body
    if status_code >= 400 and status_code != 401:
        response.raise_for_status.side_effect = requests.HTTPError(response=response)
    else:
        response.raise_for_status.side_effect = None
    return response


def test_get_current_user_returns_first_data_element():
    body = {"data": [{"id": "123", "login": "someuser", "display_name": "SomeUser"}]}
    with patch.object(api.requests, "get", return_value=_response(body)) as mock_get:
        result = api.get_current_user("token", "client-id")
    assert result == {"id": "123", "login": "someuser", "display_name": "SomeUser"}
    assert mock_get.call_args.kwargs["headers"]["Authorization"] == "Bearer token"
    assert mock_get.call_args.kwargs["headers"]["Client-Id"] == "client-id"


def test_get_current_user_raises_token_expired_on_401():
    with patch.object(api.requests, "get", return_value=_response({}, status_code=401)):
        with pytest.raises(api.TokenExpiredError):
            api.get_current_user("token", "client-id")


def test_get_current_user_propagates_other_http_errors():
    with patch.object(api.requests, "get", return_value=_response({}, status_code=500)):
        with pytest.raises(requests.RequestException):
            api.get_current_user("token", "client-id")


def test_get_followed_channels_returns_data():
    body = {
        "data": [
            {"broadcaster_id": "1", "broadcaster_login": "a", "broadcaster_name": "A"},
            {"broadcaster_id": "2", "broadcaster_login": "b", "broadcaster_name": "B"},
        ],
        "pagination": {},
    }
    with patch.object(api.requests, "get", return_value=_response(body)) as mock_get:
        result = api.get_followed_channels("token", "client-id", "user-id")
    assert result == body["data"]
    assert mock_get.call_args.kwargs["params"]["user_id"] == "user-id"


def test_get_followed_channels_follows_pagination():
    page1 = {
        "data": [{"broadcaster_id": "1", "broadcaster_login": "a", "broadcaster_name": "A"}],
        "pagination": {"cursor": "abc"},
    }
    page2 = {
        "data": [{"broadcaster_id": "2", "broadcaster_login": "b", "broadcaster_name": "B"}],
        "pagination": {},
    }
    with patch.object(api.requests, "get", side_effect=[_response(page1), _response(page2)]) as mock_get:
        result = api.get_followed_channels("token", "client-id", "user-id")
    assert result == page1["data"] + page2["data"]
    assert mock_get.call_count == 2
    assert mock_get.call_args_list[1].kwargs["params"]["after"] == "abc"


def test_get_followed_channels_raises_token_expired_on_401():
    with patch.object(api.requests, "get", return_value=_response({}, status_code=401)):
        with pytest.raises(api.TokenExpiredError):
            api.get_followed_channels("token", "client-id", "user-id")


def test_get_live_status_returns_data_for_small_list():
    body = {"data": [{"user_id": "1", "user_login": "a", "viewer_count": 10}]}
    with patch.object(api.requests, "get", return_value=_response(body)) as mock_get:
        result = api.get_live_status("token", "client-id", ["1", "2"])
    assert result == body["data"]
    assert mock_get.call_count == 1


def test_get_live_status_batches_over_100_ids():
    ids = [str(i) for i in range(150)]
    body1 = {"data": [{"user_id": "1"}]}
    body2 = {"data": [{"user_id": "101"}]}
    with patch.object(api.requests, "get", side_effect=[_response(body1), _response(body2)]) as mock_get:
        result = api.get_live_status("token", "client-id", ids)
    assert result == body1["data"] + body2["data"]
    assert mock_get.call_count == 2
    first_params = mock_get.call_args_list[0].kwargs["params"]
    second_params = mock_get.call_args_list[1].kwargs["params"]
    assert len(first_params) == 100
    assert len(second_params) == 50


def test_get_live_status_raises_token_expired_on_401():
    with patch.object(api.requests, "get", return_value=_response({}, status_code=401)):
        with pytest.raises(api.TokenExpiredError):
            api.get_live_status("token", "client-id", ["1"])


def test_get_live_status_empty_ids_makes_no_request():
    with patch.object(api.requests, "get") as mock_get:
        result = api.get_live_status("token", "client-id", [])
    assert result == []
    mock_get.assert_not_called()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/twitch/test_api.py -v`
Expected: FAIL — `api.TokenExpiredError` doesn't exist, `get_current_user` doesn't exist,
`get_followed_channels`/`get_live_status` raise `NotImplementedError`.

- [ ] **Step 3: Write `lib/twitch/api.py`** (full replacement)

```python
"""Twitch Helix API calls. No xbmc* imports - pure Python, pytest-testable."""
import requests

HELIX_BASE = "https://api.twitch.tv/helix"
_MAX_USER_IDS_PER_REQUEST = 100


class TokenExpiredError(Exception):
    """Raised when a Helix call gets HTTP 401 - the access token no longer works.
    Callers decide what to do next (refresh, re-login, etc.) - this module has
    no knowledge of tokens beyond the one it was handed for this call."""


def _headers(access_token, client_id):
    return {"Authorization": "Bearer " + access_token, "Client-Id": client_id}


def _get(url, access_token, client_id, params=None):
    response = requests.get(
        url, headers=_headers(access_token, client_id), params=params, timeout=10
    )
    if response.status_code == 401:
        raise TokenExpiredError()
    response.raise_for_status()
    return response.json()


def get_current_user(access_token, client_id):
    """Return the token owner's Twitch user info: {id, login, display_name}."""
    body = _get(HELIX_BASE + "/users", access_token, client_id)
    user = body["data"][0]
    return {"id": user["id"], "login": user["login"], "display_name": user["display_name"]}


def get_followed_channels(access_token, client_id, user_id):
    """Return the user's followed channels as a list of dicts (Helix
    /channels/followed), each with at least broadcaster_id, broadcaster_login,
    broadcaster_name. Follows Twitch's pagination cursor to completion."""
    channels = []
    cursor = None
    while True:
        params = {"user_id": user_id, "first": 100}
        if cursor:
            params["after"] = cursor
        body = _get(HELIX_BASE + "/channels/followed", access_token, client_id, params=params)
        channels.extend(body["data"])
        cursor = body.get("pagination", {}).get("cursor")
        if not cursor:
            break
    return channels


def get_live_status(access_token, client_id, user_ids):
    """Return live-stream info (Helix /streams) for the given broadcaster user_ids -
    only entries for currently-live channels are returned. Twitch caps this endpoint
    at 100 user_id params per request, so user_ids is split into chunks of 100 and
    the results concatenated."""
    if not user_ids:
        return []
    results = []
    for i in range(0, len(user_ids), _MAX_USER_IDS_PER_REQUEST):
        chunk = user_ids[i : i + _MAX_USER_IDS_PER_REQUEST]
        params = [("user_id", uid) for uid in chunk]
        body = _get(HELIX_BASE + "/streams", access_token, client_id, params=params)
        results.extend(body["data"])
    return results


def get_games_for_channels(access_token, user_ids):
    """Return a dict mapping user_id -> game_id for the given broadcaster user_ids,
    derived from their current/most recent live stream."""
    raise NotImplementedError


def get_live_streams_by_game(access_token, game_id):
    """Return currently-live streams (Helix /streams?game_id=) for the given game_id."""
    raise NotImplementedError


def search_channels(access_token, query):
    """Free-text channel search (Helix /search/channels) for the given query string."""
    raise NotImplementedError
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/twitch/test_api.py -v`
Expected: PASS (10 tests).

- [ ] **Step 5: Run the full suite**

Run: `.venv/bin/pytest -v`
Expected: PASS. `tests/test_architecture.py` must still pass — `api.py` imports only `requests`.

- [ ] **Step 6: Commit**

```bash
git add lib/twitch/api.py tests/twitch/test_api.py
git commit -m "feat: implement Twitch Helix API calls in lib.twitch.api"
```

---

### Task 3: Extend `lib/twitch/auth.py` with user-info caching and token refresh

**Files:**
- Modify: `lib/twitch/auth.py`
- Modify: `tests/twitch/test_auth.py`

**Interfaces:**
- Produces:
  - `run_device_code_login(..., get_current_user_fn=None, ...)` — new optional parameter
    (defaults to `api.get_current_user`). After a `"success"` poll result and before `save_token`,
    calls `get_current_user_fn(token["access_token"], client_id)` and merges the returned
    `id`/`login`/`display_name` into the token dict as `user_id`/`login`/`display_name` (renaming
    `id` to `user_id` to avoid colliding with the token's own `token_type` field naming style and
    to be unambiguous for `home.py`'s later use). If that call raises anything, treated as a login
    failure: `on_status("error")`, return `False`, nothing saved. Cancellation is still checked
    before the final `save_token` call, consistent with the existing cancel-race fix.
  - `auth.refresh_access_token(client_id, refresh_token) -> dict | None` — `POST` to `TOKEN_URL`
    with `grant_type=refresh_token`. Returns the parsed token dict on HTTP 200, `None` on any
    other outcome (network error, non-200, unparseable body). Never raises.
  - `auth.clear_token(addon) -> None` — `addon.setSetting("twitch_token", "")`.
- Consumed by: Task 4's `lib/windows/home.py` (`refresh_access_token`, `clear_token`, and the
  cached `user_id`/`login`/`display_name` fields on the loaded token).

- [ ] **Step 1: Fix the one existing test that will break, then write the new failing tests**

`test_run_device_code_login_success_flow` (already in `tests/twitch/test_auth.py`, from the
device-code-login plan) reaches the `"success"` branch without passing `get_current_user_fn`. Once
this task's code change lands, that would call the real `api.get_current_user` — a live network
call inside a unit test. Fix this existing test **first**, in the same commit as the new tests
below, replacing its body with:

```python
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
```

(The other 6 pre-existing `test_run_device_code_login_*` tests all return `False` before ever
reaching the `"success"` branch — cancellation checked before it, expiry, or an exception in
`request_fn`/`poll_fn` — so none of them call `get_current_user_fn` and none need changes. Verify
this by reading each one rather than assuming; if any other pre-existing test unexpectedly reaches
the success branch, apply the same fix pattern: inject `get_current_user_fn`.)

Then append the new tests:

```python
# Append to tests/twitch/test_auth.py

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


def test_clear_token_removes_saved_token():
    addon = FakeAddon()
    auth.save_token({"access_token": "tok"}, addon)
    assert auth.load_token(addon) is not None
    auth.clear_token(addon)
    assert auth.load_token(addon) is None
```

Also add `from unittest.mock import patch` to this file's imports if not already present (it is,
from the existing `poll_device_code_once` tests), and confirm `_fake_response` (already defined in
this file) is reused as-is — no changes needed to it.

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/twitch/test_auth.py -v`
Expected: FAIL — `run_device_code_login` doesn't accept `get_current_user_fn`, `refresh_access_token`
and `clear_token` don't exist.

- [ ] **Step 3: Modify `lib/twitch/auth.py`**

Add the import and two new functions, and extend `run_device_code_login`:

```python
"""Twitch OAuth device-code flow. No xbmc* imports - pure Python, pytest-testable."""
import json

import requests

from lib.twitch import api

DEVICE_CODE_URL = "https://id.twitch.tv/oauth2/device"
TOKEN_URL = "https://id.twitch.tv/oauth2/token"
SCOPES = ["user:read:follows"]

_EXPIRED_MESSAGES = {"expired_token", "expired"}
```

(The rest of the top of the file — `request_device_code`, `poll_device_code_once`, `save_token`,
`load_token` — stays exactly as-is; only the import block above and `run_device_code_login` below
change.)

Add after `load_token`:

```python
def refresh_access_token(client_id, refresh_token):
    """Exchange a refresh_token for a new token dict. Returns None on any failure
    (network error, non-200 response, unparseable body) rather than raising -
    "refresh didn't work" is an expected outcome the caller must handle either way."""
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
    except requests.RequestException:
        return None
    if response.status_code != 200:
        return None
    try:
        return response.json()
    except ValueError:
        return None


def clear_token(addon):
    """Remove the saved token, e.g. after a refresh attempt fails and the user
    must log in again from scratch."""
    addon.setSetting("twitch_token", "")
```

Replace the `run_device_code_login` signature and the `"success"` branch inside its loop:

```python
def run_device_code_login(
    client_id,
    scopes,
    addon,
    on_code,
    on_status,
    cancel_event,
    sleep_fn=None,
    wait_fn=None,
    request_fn=request_device_code,
    poll_fn=poll_device_code_once,
    get_current_user_fn=None,
):
    """... (existing docstring, plus:)

    get_current_user_fn(access_token, client_id) is called once, right after a
    successful token exchange and before the token is saved, to cache the
    logged-in user's id/login/display_name onto the token dict (defaults to
    api.get_current_user). If it raises, the whole login is treated as failed -
    on_status("error"), nothing saved - rather than saving a token with no
    cached user info."""
    if wait_fn is None:
        if sleep_fn is not None:
            wait_fn = lambda seconds: sleep_fn(seconds)
        else:
            wait_fn = lambda seconds: cancel_event.wait(seconds)
    if get_current_user_fn is None:
        get_current_user_fn = api.get_current_user

    try:
        try:
            device_info = request_fn(client_id, scopes)
        except requests.RequestException:
            on_status("error")
            return False

        on_code(device_info["user_code"], device_info["verification_uri"])
        on_status("pending")

        interval = device_info.get("interval", 5)
        expires_in = device_info.get("expires_in", 1800)
        elapsed = 0

        while elapsed < expires_in:
            if cancel_event.is_set():
                return False
            wait_fn(interval)
            elapsed += interval

            if cancel_event.is_set():
                return False

            result = poll_fn(client_id, device_info["device_code"])

            if cancel_event.is_set():
                return False

            status = result["status"]

            if status == "success":
                token = result["token"]
                try:
                    user_info = get_current_user_fn(token["access_token"], client_id)
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
            if status == "slow_down":
                interval += 5
                on_status("pending")
                continue
            if status == "expired":
                on_status("expired")
                return False
            on_status("pending")

        on_status("expired")
        return False
    except Exception:
        on_status("error")
        return False
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/twitch/test_auth.py -v`
Expected: PASS (all existing tests plus the 6 new ones above).

- [ ] **Step 5: Run the full suite**

Run: `.venv/bin/pytest -v`
Expected: PASS. `tests/test_architecture.py` must still pass — `auth.py` now imports `lib.twitch.api`
in addition to `json`/`requests`; `api.py` itself has zero `xbmc*` imports, so the transitive
import chain stays clean.

- [ ] **Step 6: Commit**

```bash
git add lib/twitch/auth.py tests/twitch/test_auth.py
git commit -m "feat: cache user info on login and add token refresh to lib.twitch.auth"
```

---

### Task 4: Home screen skin layout and `lib/windows/home.py`

**Files:**
- Modify: `resources/skins/Default/1080i/script-twitch-center-home.xml`
- Modify: `lib/windows/home.py`
- Create: `tests/windows/test_home_window.py`

**Interfaces:**
- Consumes: `api.get_followed_channels`, `api.get_live_status`, `api.TokenExpiredError` (Task 2);
  `auth.load_token`, `auth.refresh_access_token`, `auth.clear_token`, `auth.save_token` (Task 3);
  `xbmcgui.WindowXML`, `ListItem`, list-control methods (Task 1); `xbmcaddon.Addon`.
- Produces: `home.HomeWindow` (extends the existing stub, keeping its `closed_event`/`onAction`
  from the device-code-login plan's fix wave unchanged) with control-id constants
  `CHANNEL_LIST_ID = 101`, `EMPTY_LABEL_ID = 102`, `ERROR_LABEL_ID = 103`,
  `RELOGIN_BUTTON_ID = 104`; module-level helper functions `_merge_channels(followed, live_list) ->
  (list[tuple], list[dict])` and `_build_list_item(channel, stream=None) -> ListItem`, both plain
  functions (not methods) so they're directly unit-testable without constructing a window.

- [ ] **Step 1: Write the failing tests**

```python
# tests/windows/test_home_window.py
from unittest.mock import patch

import xbmcaddon

from lib.twitch import api
from lib.twitch.auth import save_token
from lib.windows.home import HomeWindow, _build_list_item, _merge_channels

FakeAddon = xbmcaddon.Addon


FOLLOWED = [
    {"broadcaster_id": "1", "broadcaster_login": "alice", "broadcaster_name": "Alice"},
    {"broadcaster_id": "2", "broadcaster_login": "bob", "broadcaster_name": "Bob"},
    {"broadcaster_id": "3", "broadcaster_login": "carol", "broadcaster_name": "Carol"},
]

LIVE = [
    {
        "user_id": "2",
        "game_name": "Just Chatting",
        "title": "hello",
        "viewer_count": 50,
        "thumbnail_url": "https://example.invalid/{width}x{height}.jpg",
    },
    {
        "user_id": "3",
        "game_name": "Programming",
        "title": "code",
        "viewer_count": 200,
        "thumbnail_url": "https://example.invalid/{width}x{height}.jpg",
    },
]


def test_merge_channels_sorts_live_by_viewers_desc_then_offline_alpha():
    live, offline = _merge_channels(FOLLOWED, LIVE)
    assert [c["broadcaster_name"] for c, _ in live] == ["Carol", "Bob"]
    assert [c["broadcaster_name"] for c in offline] == ["Alice"]


def test_merge_channels_all_offline():
    live, offline = _merge_channels(FOLLOWED, [])
    assert live == []
    assert [c["broadcaster_name"] for c in offline] == ["Alice", "Bob", "Carol"]


def test_build_list_item_live_sets_label2_and_thumbnail():
    channel = FOLLOWED[1]
    stream = LIVE[0]
    item = _build_list_item(channel, stream)
    assert item.getLabel() == "Bob"
    assert "Just Chatting" in item.getLabel2()
    assert "50" in item.getLabel2()
    assert item.getArt("thumb") == "https://example.invalid/320x180.jpg"
    assert item.getProperty("broadcaster_id") == "2"


def test_build_list_item_offline_has_no_thumbnail():
    channel = FOLLOWED[0]
    item = _build_list_item(channel, None)
    assert item.getLabel() == "Alice"
    assert item.getLabel2() == "Offline"
    assert item.getArt("thumb") == ""


def _addon_with_token(token):
    addon = FakeAddon()
    if token is not None:
        save_token(token, addon)
    return addon


def test_oninit_populates_list_on_success():
    addon = _addon_with_token({"access_token": "tok", "refresh_token": "ref", "user_id": "u1"})
    with patch("xbmcaddon.Addon", return_value=addon), patch.object(
        api, "get_followed_channels", return_value=FOLLOWED
    ), patch.object(api, "get_live_status", return_value=LIVE):
        win = HomeWindow("script-twitch-center-home.xml", "/tmp")
        win.onInit()
    control = win.getControl(HomeWindow.CHANNEL_LIST_ID)
    assert control.size() == 3


def test_oninit_shows_empty_state_when_no_followed_channels():
    addon = _addon_with_token({"access_token": "tok", "refresh_token": "ref", "user_id": "u1"})
    with patch("xbmcaddon.Addon", return_value=addon), patch.object(
        api, "get_followed_channels", return_value=[]
    ), patch.object(api, "get_live_status", return_value=[]):
        win = HomeWindow("script-twitch-center-home.xml", "/tmp")
        win.onInit()
    assert win.getControl(HomeWindow.EMPTY_LABEL_ID).getLabel() != ""
    assert win.getControl(HomeWindow.CHANNEL_LIST_ID).size() == 0


def test_oninit_refreshes_token_and_retries_on_expiry():
    old_token = {"access_token": "old", "refresh_token": "ref", "user_id": "u1", "login": "x", "display_name": "X"}
    new_token = {"access_token": "new", "refresh_token": "ref2"}
    addon = _addon_with_token(old_token)

    call_count = {"n": 0}

    def fake_get_followed(access_token, client_id, user_id):
        call_count["n"] += 1
        if access_token == "old":
            raise api.TokenExpiredError()
        return FOLLOWED

    with patch("xbmcaddon.Addon", return_value=addon), patch.object(
        api, "get_followed_channels", side_effect=fake_get_followed
    ), patch.object(api, "get_live_status", return_value=[]), patch(
        "lib.windows.home.auth.refresh_access_token", return_value=new_token
    ):
        win = HomeWindow("script-twitch-center-home.xml", "/tmp")
        win.onInit()

    assert call_count["n"] == 2
    assert win.getControl(HomeWindow.CHANNEL_LIST_ID).size() == 3
    from lib.twitch.auth import load_token

    saved = load_token(addon)
    assert saved["access_token"] == "new"
    assert saved["user_id"] == "u1"  # preserved from the old token


def test_oninit_shows_relogin_prompt_when_refresh_fails():
    old_token = {"access_token": "old", "refresh_token": "ref", "user_id": "u1"}
    addon = _addon_with_token(old_token)

    with patch("xbmcaddon.Addon", return_value=addon), patch.object(
        api, "get_followed_channels", side_effect=api.TokenExpiredError()
    ), patch("lib.windows.home.auth.refresh_access_token", return_value=None):
        win = HomeWindow("script-twitch-center-home.xml", "/tmp")
        win.onInit()

    from lib.twitch.auth import load_token

    assert load_token(addon) is None
    assert win.getControl(HomeWindow.ERROR_LABEL_ID).getLabel() != ""


def test_oninit_shows_error_state_on_network_failure():
    import requests

    addon = _addon_with_token({"access_token": "tok", "refresh_token": "ref", "user_id": "u1"})
    with patch("xbmcaddon.Addon", return_value=addon), patch.object(
        api, "get_followed_channels", side_effect=requests.ConnectionError("boom")
    ):
        win = HomeWindow("script-twitch-center-home.xml", "/tmp")
        win.onInit()
    assert win.getControl(HomeWindow.ERROR_LABEL_ID).getLabel() != ""
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/windows/test_home_window.py -v`
Expected: FAIL — `_merge_channels`/`_build_list_item` don't exist, `onInit` is a no-op.

- [ ] **Step 3: Update `resources/skins/Default/1080i/script-twitch-center-home.xml`**

```xml
<?xml version="1.0" encoding="UTF-8"?>
<window>
  <defaultcontrol always="true">101</defaultcontrol>
  <controls>
    <control type="label">
      <description>Title</description>
      <posx>60</posx>
      <posy>60</posy>
      <width>800</width>
      <height>50</height>
      <font>font32</font>
      <label>Twitch Center</label>
    </control>
    <control type="list" id="101">
      <description>Followed channels</description>
      <posx>60</posx>
      <posy>140</posy>
      <width>1800</width>
      <height>850</height>
      <onup>101</onup>
      <ondown>101</ondown>
      <itemlayout width="1800" height="120">
        <control type="label">
          <posx>10</posx>
          <width>1780</width>
          <height>60</height>
          <font>font20</font>
          <label>$INFO[ListItem.Label]</label>
        </control>
        <control type="label">
          <posx>10</posx>
          <posy>65</posy>
          <width>1780</width>
          <height>40</height>
          <font>font13</font>
          <label>$INFO[ListItem.Label2]</label>
        </control>
      </itemlayout>
      <focusedlayout width="1800" height="120">
        <control type="label">
          <posx>10</posx>
          <width>1780</width>
          <height>60</height>
          <font>font20</font>
          <textcolor>ff9146ff</textcolor>
          <label>$INFO[ListItem.Label]</label>
        </control>
        <control type="label">
          <posx>10</posx>
          <posy>65</posy>
          <width>1780</width>
          <height>40</height>
          <font>font13</font>
          <label>$INFO[ListItem.Label2]</label>
        </control>
      </focusedlayout>
    </control>
    <control type="label" id="102">
      <description>Empty followed list message</description>
      <posx>560</posx>
      <posy>460</posy>
      <width>800</width>
      <height>60</height>
      <font>font20</font>
      <align>center</align>
      <label></label>
    </control>
    <control type="label" id="103">
      <description>Error / re-login message</description>
      <posx>560</posx>
      <posy>460</posy>
      <width>800</width>
      <height>60</height>
      <font>font20</font>
      <align>center</align>
      <label></label>
    </control>
    <control type="button" id="104">
      <description>Log in again</description>
      <posx>760</posx>
      <posy>540</posy>
      <width>400</width>
      <height>60</height>
      <font>font13</font>
      <align>center</align>
      <label>Log in again</label>
    </control>
  </controls>
</window>
```

- [ ] **Step 4: Write `lib/windows/home.py`** (full replacement)

```python
"""Home screen: the user's followed channels, live ones surfaced first."""
import threading

import xbmc
import xbmcaddon
import xbmcgui

from lib.twitch import api, auth

CHANNEL_LIST_ID = 101
EMPTY_LABEL_ID = 102
ERROR_LABEL_ID = 103
RELOGIN_BUTTON_ID = 104

_MISSING_TOKEN_MESSAGE = "You're not logged in. Reopen the addon to log in."
_EMPTY_FOLLOWED_MESSAGE = "You're not following anyone yet."
_NETWORK_ERROR_MESSAGE = "Couldn't reach Twitch. Check your connection and reopen the addon."
_RELOGIN_MESSAGE = "Your session expired. Log in again to continue."


def _thumbnail_url(raw_url, width=320, height=180):
    return raw_url.replace("{width}", str(width)).replace("{height}", str(height))


def _merge_channels(followed, live_list):
    """Split followed channels into (live, offline). live is a list of
    (channel, stream) tuples sorted by viewer_count descending; offline is a
    list of channel dicts sorted alphabetically by broadcaster_name."""
    live_by_id = {stream["user_id"]: stream for stream in live_list}
    live = []
    offline = []
    for channel in followed:
        stream = live_by_id.get(channel["broadcaster_id"])
        if stream:
            live.append((channel, stream))
        else:
            offline.append(channel)
    live.sort(key=lambda pair: pair[1]["viewer_count"], reverse=True)
    offline.sort(key=lambda c: c["broadcaster_name"].lower())
    return live, offline


def _build_list_item(channel, stream=None):
    item = xbmcgui.ListItem(channel["broadcaster_name"])
    if stream:
        item.setLabel2(stream["game_name"] + " - " + str(stream["viewer_count"]) + " viewers")
        item.setArt({"thumb": _thumbnail_url(stream["thumbnail_url"])})
    else:
        item.setLabel2("Offline")
    item.setProperty("broadcaster_id", channel["broadcaster_id"])
    return item


class HomeWindow(xbmcgui.WindowXML):
    CHANNEL_LIST_ID = CHANNEL_LIST_ID
    EMPTY_LABEL_ID = EMPTY_LABEL_ID
    ERROR_LABEL_ID = ERROR_LABEL_ID
    RELOGIN_BUTTON_ID = RELOGIN_BUTTON_ID

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.closed_event = threading.Event()

    def onInit(self):
        addon = xbmcaddon.Addon()
        client_id = addon.getSetting("client_id")
        token = auth.load_token(addon)
        if token is None:
            self._show_error(_MISSING_TOKEN_MESSAGE)
            return

        try:
            self._load_and_populate(addon, client_id, token)
        except api.TokenExpiredError:
            self._handle_expired_token(addon, client_id, token)
        except Exception as exc:
            xbmc.log(
                "script.twitch.center: Home screen failed to load: " + repr(exc), xbmc.LOGERROR
            )
            self._show_error(_NETWORK_ERROR_MESSAGE)

    def _load_and_populate(self, addon, client_id, token):
        followed = api.get_followed_channels(token["access_token"], client_id, token["user_id"])
        broadcaster_ids = [c["broadcaster_id"] for c in followed]
        live_list = api.get_live_status(token["access_token"], client_id, broadcaster_ids)
        self._populate(followed, live_list)

    def _handle_expired_token(self, addon, client_id, token):
        new_token = auth.refresh_access_token(client_id, token["refresh_token"])
        if new_token is None:
            auth.clear_token(addon)
            self._show_error(_RELOGIN_MESSAGE)
            return

        new_token["user_id"] = token.get("user_id")
        new_token["login"] = token.get("login")
        new_token["display_name"] = token.get("display_name")

        try:
            self._load_and_populate(addon, client_id, new_token)
        except api.TokenExpiredError:
            auth.clear_token(addon)
            self._show_error(_RELOGIN_MESSAGE)
            return
        except Exception as exc:
            xbmc.log(
                "script.twitch.center: Home screen failed after token refresh: " + repr(exc),
                xbmc.LOGERROR,
            )
            self._show_error(_NETWORK_ERROR_MESSAGE)
            return

        auth.save_token(new_token, addon)

    def _populate(self, followed, live_list):
        control = self.getControl(self.CHANNEL_LIST_ID)
        control.reset()
        if not followed:
            self.getControl(self.EMPTY_LABEL_ID).setLabel(_EMPTY_FOLLOWED_MESSAGE)
            return
        live, offline = _merge_channels(followed, live_list)
        items = [_build_list_item(channel, stream) for channel, stream in live]
        items += [_build_list_item(channel) for channel in offline]
        control.addItems(items)

    def _show_error(self, message):
        self.getControl(self.ERROR_LABEL_ID).setLabel(message)

    def onAction(self, action):
        if action.getId() in (xbmcgui.ACTION_PREVIOUS_MENU, xbmcgui.ACTION_NAV_BACK):
            self.close()
            self.closed_event.set()
```

Note: `test_oninit_populates_list_on_success` and its siblings patch `"xbmcaddon.Addon"` (the
`xbmcaddon` stub module's own `Addon` attribute), not `"lib.windows.home.xbmcaddon.Addon"`. This
works because `home.py` does `import xbmcaddon` (a module import) and calls `xbmcaddon.Addon()` —
`xbmcaddon` is one shared module object across every importer, so patching its `Addon` attribute
directly affects the call inside `home.py` too, with no need to patch through `home.py`'s own
namespace.

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/windows/test_home_window.py -v`
Expected: PASS (9 tests).

- [ ] **Step 6: Run the full suite**

Run: `.venv/bin/pytest -v`
Expected: PASS, full suite green (all 4 tasks combined).

- [ ] **Step 7: Commit**

```bash
git add resources/skins/Default/1080i/script-twitch-center-home.xml lib/windows/home.py tests/windows/test_home_window.py
git commit -m "feat: implement Home screen with followed-channel list and token refresh"
```

---

## Post-plan state

After Task 4, launching the addon with a saved token loads Home, shows followed channels with live
ones first (thumbnail, game, viewer count), refreshes an expired access token transparently and
retries once, and falls back to a re-login prompt only if refresh itself fails. Manually verify in
real Kodi (symlink into `~/.kodi/addons/`, launch, drive via JSON-RPC/log inspection, as done for
the login screen) before considering this done — the automated suite covers logic correctness but
not real Twitch API responses or actual skin rendering.

Out of scope, still deferred: clicking a channel to play it, the Discover/search screen, periodic
live-status refresh while Home stays open — per this plan's design spec.
