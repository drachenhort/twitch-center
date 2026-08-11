# Device-Code Login Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the scaffold's stubbed `lib/twitch/auth.py` and `lib/windows/login.py` with a
working Twitch OAuth device-code login flow, and wire `lib/main.py` to route to `LoginWindow` or
`HomeWindow` based on whether a token is saved.

**Architecture:** All polling/orchestration logic lives in `lib/twitch/auth.py` (pure Python, zero
`xbmc*` imports, fully unit-testable with mocked `requests` and an injectable sleep function).
`lib/windows/login.py` is a thin GUI shim: it spawns a background thread running
`auth.run_device_code_login(...)`, passing it two callbacks that update on-screen labels, so the
Kodi UI thread never blocks on network calls or `time.sleep`. `lib/main.py` reads the saved token
(via a param-injected `addon` object, not a direct `xbmcaddon` import, to keep the boundary and
stay testable) and opens the appropriate window.

**Tech Stack:** Python 3, `requests` (already a dependency), `threading` (stdlib), `pytest` +
`unittest.mock` for tests.

## Global Constraints

- `lib/twitch/*` must have zero `xbmc*` imports — enforced by the existing
  `tests/test_architecture.py` AST check; nothing in this plan should need to touch that test.
- `lib/windows/*` and `lib/settings.py` remain the only modules allowed to import
  `xbmc`/`xbmcgui`/`xbmcaddon`.
- Twitch Client ID is `f6exkvelsf4gmy83b8zat5i10t3gy6`, stored as the default value of a new hidden
  `client_id` setting in `resources/settings.xml`.
- Requested OAuth scopes are exactly `["user:read:follows"]` (spec: "Scopes section").
- Token storage: a hidden `twitch_token` addon setting (JSON-serialized token dict), not a separate
  file.
- `save_token(token, addon)` / `load_token(addon)` take the addon/settings object as a parameter
  rather than importing `xbmcaddon` directly, so `lib/twitch/auth.py` keeps zero `xbmc*` imports.
- `pip install -r requirements-dev.txt && pytest` must pass after every task.
- No test makes a real network call to Twitch, and no test sleeps in real time or spins a real
  background thread waiting on real I/O.

---

## File Structure

```
resources/
  settings.xml               # modify: add client_id, twitch_token hidden settings
  language/resource.language.en_gb/strings.po   # modify: add label strings for new settings
  skins/Default/1080i/
    script-twitch-center-login.xml              # create: login screen layout
lib/
  twitch/
    auth.py                  # modify: real implementation
  windows/
    login.py                 # modify: real implementation
  main.py                    # modify: real routing
tests/
  kodi_stubs/
    xbmcgui.py                # modify: add getControl/ControlLabel/Action/ACTION_* constants
  twitch/
    test_auth.py              # modify: rewritten with mocks, no NotImplementedError tests
  windows/
    test_windows_stubs.py     # modify: drop the now-superseded generic LoginWindow smoke test
    test_login_window.py      # create: LoginWindow-specific tests
  test_main.py                 # create: lib.main.run() routing tests
```

---

### Task 1: Extend Kodi GUI stubs for controls and actions

**Files:**
- Modify: `tests/kodi_stubs/xbmcgui.py`
- Test: `tests/test_kodi_stubs.py`

**Interfaces:**
- Produces: `xbmcgui.ACTION_PREVIOUS_MENU` (int `10`), `xbmcgui.ACTION_NAV_BACK` (int `92`),
  `xbmcgui.Action` (constructed with `action_id`, exposing `.getId() -> int`),
  `xbmcgui.ControlLabel` (constructed with no args, exposing `.setLabel(text) -> None` and
  `.getLabel() -> str`), `xbmcgui.WindowXML.getControl(control_id) -> ControlLabel` (returns a
  `ControlLabel` from an internal per-instance dict, auto-creating one on first access so tests
  don't need to pre-register control IDs).
- Consumed by: Task 4's `lib/windows/login.py`.

- [ ] **Step 1: Write the failing test**

```python
# Append to tests/test_kodi_stubs.py

def test_xbmcgui_stub_action_constants_and_getid():
    import xbmcgui
    assert xbmcgui.ACTION_PREVIOUS_MENU == 10
    assert xbmcgui.ACTION_NAV_BACK == 92
    action = xbmcgui.Action(92)
    assert action.getId() == 92


def test_xbmcgui_stub_control_label_set_and_get():
    import xbmcgui
    label = xbmcgui.ControlLabel()
    label.setLabel("hello")
    assert label.getLabel() == "hello"


def test_xbmcgui_stub_windowxml_getcontrol_returns_label_and_persists():
    import xbmcgui
    win = xbmcgui.WindowXML("dummy.xml", "/tmp")
    control = win.getControl(101)
    control.setLabel("world")
    assert win.getControl(101).getLabel() == "world"
    assert win.getControl(102).getLabel() == ""
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_kodi_stubs.py -v`
Expected: FAIL with `AttributeError: module 'xbmcgui' has no attribute 'ACTION_PREVIOUS_MENU'`.

- [ ] **Step 3: Rewrite `tests/kodi_stubs/xbmcgui.py`**

```python
"""Minimal stand-in for Kodi's built-in xbmcgui module, for pytest-only use."""

ACTION_PREVIOUS_MENU = 10
ACTION_NAV_BACK = 92


class Action:
    def __init__(self, action_id):
        self._action_id = action_id

    def getId(self):
        return self._action_id


class ControlLabel:
    def __init__(self):
        self._label = ""

    def setLabel(self, text):
        self._label = text

    def getLabel(self):
        return self._label


class WindowXML:
    def __init__(self, xml_filename, script_path, default_skin="Default", default_res="1080i"):
        self.xml_filename = xml_filename
        self.script_path = script_path
        self._controls = {}

    def show(self):
        pass

    def close(self):
        pass

    def getControl(self, control_id):
        if control_id not in self._controls:
            self._controls[control_id] = ControlLabel()
        return self._controls[control_id]


class WindowXMLDialog(WindowXML):
    def doModal(self):
        pass
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_kodi_stubs.py -v`
Expected: PASS (7 tests: 4 existing + 3 new).

- [ ] **Step 5: Run the full suite to confirm nothing else broke**

Run: `.venv/bin/pytest -v`
Expected: PASS (all existing tests still green — `getControl` and the new constants are additive).

- [ ] **Step 6: Commit**

```bash
git add tests/kodi_stubs/xbmcgui.py tests/test_kodi_stubs.py
git commit -m "test: extend xbmcgui stub with controls and action constants"
```

---

### Task 2: Add `client_id` and `twitch_token` settings

**Files:**
- Modify: `resources/settings.xml`
- Modify: `resources/language/resource.language.en_gb/strings.po`
- Test: `tests/test_addon_manifest.py`

**Interfaces:**
- Produces: setting ids `client_id` (default `f6exkvelsf4gmy83b8zat5i10t3gy6`) and `twitch_token`
  (default empty string), both hidden (matching the `<constraints><options>hidden</options>`
  convention), both `level` 2.
- Consumed by: Task 4's `lib/windows/login.py` (`client_id`), Task 3's `save_token`/`load_token`
  callers (`twitch_token`, written/read by id, not directly asserted in XML).

- [ ] **Step 1: Write the failing test**

```python
# Append to tests/test_addon_manifest.py
import xml.etree.ElementTree as ET
from pathlib import Path

SETTINGS_XML = Path(__file__).resolve().parent.parent / "resources" / "settings.xml"


def test_settings_xml_declares_client_id_with_default():
    tree = ET.parse(SETTINGS_XML)
    root = tree.getroot()
    setting_ids = {s.attrib["id"]: s for s in root.iter("setting")}
    assert "client_id" in setting_ids
    default = setting_ids["client_id"].find("default")
    assert default is not None
    assert default.text == "f6exkvelsf4gmy83b8zat5i10t3gy6"


def test_settings_xml_declares_twitch_token_setting():
    tree = ET.parse(SETTINGS_XML)
    root = tree.getroot()
    setting_ids = {s.attrib["id"]: s for s in root.iter("setting")}
    assert "twitch_token" in setting_ids
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_addon_manifest.py -v`
Expected: FAIL — `client_id` not found in `setting_ids`.

- [ ] **Step 3: Update `resources/settings.xml`**

```xml
<?xml version="1.0" encoding="UTF-8"?>
<settings version="1">
  <section id="script.twitch.center">
    <category id="general" label="30000">
      <group id="1">
        <setting id="chat_display_mode" type="string" label="30001">
          <level>0</level>
          <default>both</default>
          <constraints>
            <options>
              <option label="30002">overlay</option>
              <option label="30003">standalone</option>
              <option label="30004">both</option>
            </options>
          </constraints>
          <control type="list" format="string"/>
        </setting>
        <setting id="client_id" type="string" label="30005" help="">
          <level>2</level>
          <default>f6exkvelsf4gmy83b8zat5i10t3gy6</default>
          <control type="edit" format="string"/>
          <constraints>
            <options>hidden</options>
          </constraints>
        </setting>
        <setting id="twitch_token" type="string" label="30006" help="">
          <level>2</level>
          <default></default>
          <control type="edit" format="string"/>
          <constraints>
            <options>hidden</options>
          </constraints>
        </setting>
      </group>
    </category>
  </section>
</settings>
```

- [ ] **Step 4: Update `resources/language/resource.language.en_gb/strings.po`**

Append:

```
msgctxt "#30005"
msgid "Twitch Client ID"
msgstr ""

msgctxt "#30006"
msgid "Twitch Token"
msgstr ""
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_addon_manifest.py -v`
Expected: PASS (4 tests: 2 existing + 2 new).

- [ ] **Step 6: Run the full suite**

Run: `.venv/bin/pytest -v`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add resources/settings.xml resources/language/resource.language.en_gb/strings.po tests/test_addon_manifest.py
git commit -m "feat: add hidden client_id and twitch_token settings"
```

---

### Task 3: Implement `lib/twitch/auth.py`

**Files:**
- Modify: `lib/twitch/auth.py`
- Modify: `tests/twitch/test_auth.py`

**Interfaces:**
- Produces:
  - `auth.SCOPES = ["user:read:follows"]`
  - `auth.DEVICE_CODE_URL`, `auth.TOKEN_URL` (module-level constants)
  - `auth.request_device_code(client_id, scopes) -> dict` (keys: `device_code`, `user_code`,
    `verification_uri`, `expires_in`, `interval`) — raises `requests.RequestException` on
    network/HTTP failure (via `response.raise_for_status()`)
  - `auth.poll_device_code_once(client_id, device_code) -> dict` — always returns a dict with a
    `"status"` key: `"success"` (+ `"token"` key), `"pending"`, `"slow_down"`, or `"expired"`.
    Never raises — network errors are caught and treated as `"pending"`.
  - `auth.save_token(token, addon) -> None` — calls `addon.setSetting("twitch_token", json_str)`
  - `auth.load_token(addon) -> dict | None`
  - `auth.run_device_code_login(client_id, scopes, addon, on_code, on_status, cancel_event,
    sleep_fn=time.sleep, request_fn=request_device_code, poll_fn=poll_device_code_once) -> bool` —
    orchestrates the full flow; returns `True` on success, `False` on cancel/expiry/error.
    `on_code(user_code, verification_uri)` is called once after the device code is obtained.
    `on_status(status)` is called with one of `"pending"`, `"expired"`, `"success"`, `"error"`
    after each poll (and once with `"error"` if `request_fn` itself fails).
- Consumed by: Task 4's `lib/windows/login.py` (all of the above), Task 5's `lib/main.py`
  (`load_token`).

- [ ] **Step 1: Write the failing tests**

```python
# tests/twitch/test_auth.py (full replacement of the file)
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/twitch/test_auth.py -v`
Expected: FAIL — `request_device_code` currently raises `NotImplementedError`, not returning a
value, and `auth.requests` doesn't exist yet (module doesn't import `requests`).

- [ ] **Step 3: Write `lib/twitch/auth.py`** (full replacement)

```python
"""Twitch OAuth device-code flow. No xbmc* imports - pure Python, pytest-testable."""
import json
import time

import requests

DEVICE_CODE_URL = "https://id.twitch.tv/oauth2/device"
TOKEN_URL = "https://id.twitch.tv/oauth2/token"
SCOPES = ["user:read:follows"]

_EXPIRED_MESSAGES = {"expired_token", "expired"}


def request_device_code(client_id, scopes):
    """Start the device-code flow. Returns dict with device_code, user_code,
    verification_uri, expires_in, interval (per Twitch's device-code response).
    Raises requests.RequestException on network/HTTP failure."""
    response = requests.post(
        DEVICE_CODE_URL,
        data={"client_id": client_id, "scopes": " ".join(scopes)},
    )
    response.raise_for_status()
    return response.json()


def poll_device_code_once(client_id, device_code):
    """Make one poll attempt against Twitch's token endpoint. Never raises - network
    errors are treated the same as an "authorization_pending" response, since a
    single transient failure shouldn't abort the whole login flow.

    Returns one of:
      {"status": "success", "token": {...}}
      {"status": "pending"}
      {"status": "slow_down"}
      {"status": "expired"}
    """
    try:
        response = requests.post(
            TOKEN_URL,
            data={
                "client_id": client_id,
                "device_code": device_code,
                "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
            },
        )
    except requests.RequestException:
        return {"status": "pending"}

    if response.status_code == 200:
        return {"status": "success", "token": response.json()}

    try:
        body = response.json()
    except ValueError:
        return {"status": "pending"}

    message = body.get("message", "")
    if message == "slow_down":
        return {"status": "slow_down"}
    if message in _EXPIRED_MESSAGES:
        return {"status": "expired"}
    return {"status": "pending"}


def save_token(token, addon):
    """Persist a token dict to the addon's hidden twitch_token setting."""
    addon.setSetting("twitch_token", json.dumps(token))


def load_token(addon):
    """Load a previously saved token dict from the addon's hidden twitch_token
    setting, or None if none saved / the stored value isn't valid JSON."""
    raw = addon.getSetting("twitch_token")
    if not raw:
        return None
    try:
        return json.loads(raw)
    except ValueError:
        return None


def run_device_code_login(
    client_id,
    scopes,
    addon,
    on_code,
    on_status,
    cancel_event,
    sleep_fn=time.sleep,
    request_fn=request_device_code,
    poll_fn=poll_device_code_once,
):
    """Orchestrates the full device-code login flow: request a code, report it via
    on_code, then poll until success/expiry/cancellation, reporting status via
    on_status after each attempt. Returns True on successful login (token saved),
    False otherwise. Safe to run on a background thread - all callbacks are the
    caller's responsibility to make thread-safe for their UI toolkit."""
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
        sleep_fn(interval)
        elapsed += interval

        result = poll_fn(client_id, device_info["device_code"])
        status = result["status"]

        if status == "success":
            save_token(result["token"], addon)
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/twitch/test_auth.py -v`
Expected: PASS (14 tests).

- [ ] **Step 5: Run the full suite**

Run: `.venv/bin/pytest -v`
Expected: PASS. (`tests/test_architecture.py` must still pass — `auth.py` imports only `json`,
`time`, and `requests`, none of which start with `xbmc`.)

- [ ] **Step 6: Commit**

```bash
git add lib/twitch/auth.py tests/twitch/test_auth.py
git commit -m "feat: implement Twitch device-code login flow in lib.twitch.auth"
```

---

### Task 4: Login skin layout and `lib/windows/login.py`

**Files:**
- Create: `resources/skins/Default/1080i/script-twitch-center-login.xml`
- Modify: `lib/windows/login.py`
- Modify: `tests/windows/test_windows_stubs.py`
- Create: `tests/windows/test_login_window.py`

**Interfaces:**
- Consumes: `auth.SCOPES`, `auth.run_device_code_login` (Task 3); `xbmcgui.WindowXML`,
  `xbmcgui.Action`, `xbmcgui.ACTION_PREVIOUS_MENU`, `xbmcgui.ACTION_NAV_BACK` (Task 1);
  `xbmcaddon.Addon` (existing stub).
- Produces: `login.LoginWindow` with class constants `CODE_LABEL_ID = 101`, `URL_LABEL_ID = 102`,
  `STATUS_LABEL_ID = 103`; methods `.onInit()`, `._on_code(user_code, verification_uri)`,
  `._on_status(status)`, `.onAction(action)`; module-level `login.STATUS_MESSAGES` dict.
- Consumed by: Task 5's `lib/main.py`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/windows/test_login_window.py
import threading
from unittest.mock import patch

from lib.windows.login import LoginWindow


def test_on_code_sets_code_and_url_labels():
    win = LoginWindow("script-twitch-center-login.xml", "/tmp")
    win._cancel_event = threading.Event()
    win._on_code("ABCD-1234", "https://www.twitch.tv/activate")
    assert win.getControl(LoginWindow.CODE_LABEL_ID).getLabel() == "ABCD-1234"
    assert win.getControl(LoginWindow.URL_LABEL_ID).getLabel() == "https://www.twitch.tv/activate"


def test_on_status_sets_status_label_text():
    win = LoginWindow("script-twitch-center-login.xml", "/tmp")
    win._cancel_event = threading.Event()
    win._on_status("pending")
    assert win.getControl(LoginWindow.STATUS_LABEL_ID).getLabel() == "Waiting for authorization..."


def test_on_status_success_closes_window():
    win = LoginWindow("script-twitch-center-login.xml", "/tmp")
    win._cancel_event = threading.Event()
    with patch.object(win, "close") as mock_close:
        win._on_status("success")
    mock_close.assert_called_once()


def test_on_action_back_sets_cancel_event_and_closes():
    import xbmcgui

    win = LoginWindow("script-twitch-center-login.xml", "/tmp")
    win._cancel_event = threading.Event()
    with patch.object(win, "close") as mock_close:
        win.onAction(xbmcgui.Action(xbmcgui.ACTION_NAV_BACK))
    assert win._cancel_event.is_set()
    mock_close.assert_called_once()


def test_on_action_unrelated_key_does_nothing():
    import xbmcgui

    win = LoginWindow("script-twitch-center-login.xml", "/tmp")
    win._cancel_event = threading.Event()
    with patch.object(win, "close") as mock_close:
        win.onAction(xbmcgui.Action(999))
    assert not win._cancel_event.is_set()
    mock_close.assert_not_called()


def test_oninit_starts_background_thread_with_run_device_code_login():
    from lib.twitch import auth

    with patch("lib.windows.login.threading.Thread") as mock_thread_cls:
        win = LoginWindow("script-twitch-center-login.xml", "/tmp")
        win.onInit()
    mock_thread_cls.assert_called_once()
    call_kwargs = mock_thread_cls.call_args.kwargs
    assert call_kwargs["target"] is auth.run_device_code_login
    assert call_kwargs["kwargs"]["client_id"] == ""
    assert call_kwargs["kwargs"]["scopes"] == auth.SCOPES
    mock_thread_cls.return_value.start.assert_called_once()
```

Also **modify `tests/windows/test_windows_stubs.py`**: remove `test_login_window_constructs` (it
called `LoginWindow("login.xml", "/tmp").onInit()` with no mocking, which would now spawn a real
background thread hitting the network — superseded by
`test_oninit_starts_background_thread_with_run_device_code_login` above) and remove the now-unused
`from lib.windows.login import LoginWindow` import if nothing else in that file uses it.

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/windows/test_login_window.py -v`
Expected: FAIL — `LoginWindow` has no `_on_code`/`_on_status`/`onAction` yet, and `getControl`
doesn't exist on the current stub-backed instance's expectations (this task assumes Task 1 is
already done, so `getControl` itself exists; the failures here are all about `LoginWindow`'s own
missing behavior).

- [ ] **Step 3: Create `resources/skins/Default/1080i/script-twitch-center-login.xml`**

```xml
<?xml version="1.0" encoding="UTF-8"?>
<window>
  <controls>
    <control type="label" id="101">
      <description>User code</description>
      <label></label>
    </control>
    <control type="label" id="102">
      <description>Verification URL</description>
      <label></label>
    </control>
    <control type="label" id="103">
      <description>Status</description>
      <label></label>
    </control>
    <control type="button" id="104">
      <description>Cancel</description>
      <label>Cancel</label>
      <onclick>PreviousMenu</onclick>
    </control>
  </controls>
</window>
```

- [ ] **Step 4: Write `lib/windows/login.py`** (full replacement)

```python
"""Device-code login screen: displays the code + verification URL, polls for auth."""
import threading

import xbmcaddon
import xbmcgui

from lib.twitch import auth

STATUS_MESSAGES = {
    "pending": "Waiting for authorization...",
    "expired": "Code expired. Reopen the addon to try again.",
    "success": "Logged in!",
    "error": "Connection error. Reopen the addon to try again.",
}


class LoginWindow(xbmcgui.WindowXML):
    CODE_LABEL_ID = 101
    URL_LABEL_ID = 102
    STATUS_LABEL_ID = 103

    def onInit(self):
        self._cancel_event = threading.Event()
        addon = xbmcaddon.Addon()
        client_id = addon.getSetting("client_id")
        thread = threading.Thread(
            target=auth.run_device_code_login,
            kwargs={
                "client_id": client_id,
                "scopes": auth.SCOPES,
                "addon": addon,
                "on_code": self._on_code,
                "on_status": self._on_status,
                "cancel_event": self._cancel_event,
            },
        )
        thread.daemon = True
        thread.start()
        self._thread = thread

    def _on_code(self, user_code, verification_uri):
        self.getControl(self.CODE_LABEL_ID).setLabel(user_code)
        self.getControl(self.URL_LABEL_ID).setLabel(verification_uri)

    def _on_status(self, status):
        message = STATUS_MESSAGES.get(status, "")
        self.getControl(self.STATUS_LABEL_ID).setLabel(message)
        if status == "success":
            self.close()

    def onAction(self, action):
        if action.getId() in (xbmcgui.ACTION_PREVIOUS_MENU, xbmcgui.ACTION_NAV_BACK):
            self._cancel_event.set()
            self.close()
```

Note: `login.py`'s `onInit` calls `threading.Thread(target=auth.run_device_code_login,
kwargs={...})` — both `target` and `kwargs` are passed as keyword arguments to `Thread(...)`
itself, which is what the Step 1 test above asserts against. `client_id` reads as `""` in that
assertion because the `xbmcaddon.Addon` stub's `getSetting` returns `""` for any unset id, and the
stub instance `onInit` constructs via `xbmcaddon.Addon()` has no settings pre-populated.

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/windows/test_login_window.py tests/windows/test_windows_stubs.py -v`
Expected: PASS (6 new tests in `test_login_window.py`; `test_windows_stubs.py` drops one test, so
its count goes from 6 to 5).

- [ ] **Step 6: Run the full suite**

Run: `.venv/bin/pytest -v`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add resources/skins/Default/1080i/script-twitch-center-login.xml lib/windows/login.py tests/windows/test_login_window.py tests/windows/test_windows_stubs.py
git commit -m "feat: implement LoginWindow with device-code polling on a background thread"
```

---

### Task 5: Wire `lib/main.py` routing

**Files:**
- Modify: `lib/main.py`
- Create: `tests/test_main.py`

**Interfaces:**
- Consumes: `auth.load_token` (Task 3), `login.LoginWindow` (Task 4), `home.HomeWindow` (existing
  stub from the scaffold).
- Produces: `main.run(argv, addon=None, login_window_cls=None, home_window_cls=None) -> None` — the
  addon's entry point. Optional params default to `xbmcaddon.Addon()`, `LoginWindow`, `HomeWindow`
  respectively when not supplied (production call from `if __name__ == "__main__"` passes none of
  them), and exist purely so tests can inject fakes without needing a real Kodi environment or
  network access.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_main.py
from lib import main


class FakeAddon:
    def __init__(self, token=None):
        self._token = token

    def getSetting(self, id):
        if id == "twitch_token":
            return '{"access_token": "tok"}' if self._token else ""
        return ""


class FakeWindow:
    instances = []

    def __init__(self, xml_filename, script_path):
        self.xml_filename = xml_filename
        self.script_path = script_path
        self.shown = False
        FakeWindow.instances.append(self)

    def show(self):
        self.shown = True


class FakeLoginWindow(FakeWindow):
    instances = []


class FakeHomeWindow(FakeWindow):
    instances = []


def test_run_opens_login_window_when_no_token_saved():
    FakeLoginWindow.instances.clear()
    FakeHomeWindow.instances.clear()
    main.run(
        [],
        addon=FakeAddon(token=None),
        login_window_cls=FakeLoginWindow,
        home_window_cls=FakeHomeWindow,
    )
    assert len(FakeLoginWindow.instances) == 1
    assert FakeLoginWindow.instances[0].shown is True
    assert len(FakeHomeWindow.instances) == 0


def test_run_opens_home_window_when_token_saved():
    FakeLoginWindow.instances.clear()
    FakeHomeWindow.instances.clear()
    main.run(
        [],
        addon=FakeAddon(token={"access_token": "tok"}),
        login_window_cls=FakeLoginWindow,
        home_window_cls=FakeHomeWindow,
    )
    assert len(FakeHomeWindow.instances) == 1
    assert FakeHomeWindow.instances[0].shown is True
    assert len(FakeLoginWindow.instances) == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_main.py -v`
Expected: FAIL — `main.run` currently raises `NotImplementedError` unconditionally.

- [ ] **Step 3: Write `lib/main.py`** (full replacement)

```python
"""Addon entry point, referenced by addon.xml's library="lib/main.py"."""
import sys

import xbmcaddon

from lib.twitch import auth
from lib.windows.home import HomeWindow
from lib.windows.login import LoginWindow


def run(argv, addon=None, login_window_cls=None, home_window_cls=None):
    """Route to LoginWindow if no token is saved, otherwise HomeWindow."""
    addon = addon or xbmcaddon.Addon()
    login_window_cls = login_window_cls or LoginWindow
    home_window_cls = home_window_cls or HomeWindow

    token = auth.load_token(addon)
    if token is None:
        window = login_window_cls("script-twitch-center-login.xml", addon.getAddonInfo("path"))
    else:
        window = home_window_cls("script-twitch-center-home.xml", addon.getAddonInfo("path"))
    window.show()


if __name__ == "__main__":
    run(sys.argv)
```

Note: `home.HomeWindow` is still the scaffold's no-op stub — this task only wires the routing to it,
it does not give Home real content. `addon.getAddonInfo("path")` matches the `xbmcaddon.Addon`
stub's existing `getAddonInfo` support (Task 2 of the original scaffold plan already added this
method to `tests/kodi_stubs/xbmcaddon.py`); no stub changes needed here.

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_main.py -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Update `tests/test_smoke.py` if needed**

Read the existing `test_main_run_is_callable` test in `tests/test_smoke.py`. It calls
`callable(main.run)`, not `main.run(...)` itself, so it should still pass unchanged — confirm this
by running it rather than editing it.

- [ ] **Step 6: Run the full suite**

Run: `.venv/bin/pytest -v`
Expected: PASS, full suite green (all tasks 1-5 combined).

- [ ] **Step 7: Commit**

```bash
git add lib/main.py tests/test_main.py
git commit -m "feat: wire lib.main routing between LoginWindow and HomeWindow"
```

---

## Post-plan state

After Task 5, launching the addon in Kodi with no saved token shows the device-code login screen,
polls Twitch in the background without freezing the UI, and on success saves the token and would
route to `HomeWindow` (still content-empty) on the next launch. Manually verify in real Kodi per
the pattern already used for the scaffold (symlink into `~/.kodi/addons/`, launch, drive via
JSON-RPC/log inspection) before considering this done — the automated suite covers logic
correctness but not the actual skin XML rendering or real Twitch API responses.

Out of scope, still deferred: token refresh, multi-account support, `HomeWindow`/`DiscoverWindow`
real content, IRC chat, stream resolution — per the original scaffold's "Follow-up specs" list and
this plan's design spec's "Out of scope" section.
