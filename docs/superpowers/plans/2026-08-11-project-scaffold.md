# Project Scaffold Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stand up the `script.twitch.center` Kodi addon skeleton — installable addon manifest,
`lib/` package boundaries for auth/API/stream-resolution/chat/Home/Discover with stubbed
(not-yet-working) implementations, and a `tests/kodi_stubs/` harness so the pure-Python layer is
pytest-testable without a real Kodi install.

**Architecture:** Kodi *script* addon (not `plugin.video.*`). `lib/twitch/*` is pure Python (zero
`xbmc*` imports) and pytest-testable directly. `lib/windows/*`, `lib/settings.py` are the only
modules touching `xbmcgui`/`xbmcaddon`; they're exercised under pytest via stub modules
(`tests/kodi_stubs/xbmc.py`, `xbmcgui.py`, `xbmcaddon.py`) added to `sys.path` by
`tests/conftest.py`. Follows the pattern established by jellyfin-kodi-plex.

**Tech Stack:** Python 3 (Kodi 20/21 embedded interpreter), `pytest` for tests, `requests` for
future HTTP calls (unused by stubs in this plan). No third-party runtime deps inside the addon
itself — Kodi addons can't rely on pip installs, everything must be vendored or stdlib.

## Global Constraints

- `lib/twitch/*` must have zero `xbmc*` imports (spec: "Module boundary").
- `lib/windows/*`, `lib/settings.py` are the only modules importing `xbmc`/`xbmcgui`/`xbmcaddon`.
- Addon id is `script.twitch.center` (spec: "What this is").
- This plan implements stubs only — functions raise `NotImplementedError` or return empty
  placeholder data, no real Twitch/IRC network calls (spec: "Goals for this scaffold" /
  "Out of scope").
- `pip install -r requirements-dev.txt && pytest` must pass after every task (spec: "Testing").

---

## File Structure

```
addon.xml
resources/
  settings.xml
  language/resource.language.en_gb/strings.po
lib/
  __init__.py
  twitch/
    __init__.py
    auth.py
    api.py
    stream.py
    irc.py
  windows/
    __init__.py
    login.py
    home.py
    discover.py
    player.py
    chat_overlay.py
    chat_window.py
  settings.py
  main.py
tests/
  kodi_stubs/
    xbmc.py
    xbmcgui.py
    xbmcaddon.py
  conftest.py
  test_smoke.py
```

---

### Task 1: Addon manifest and resources

**Files:**
- Create: `addon.xml`
- Create: `resources/settings.xml`
- Create: `resources/language/resource.language.en_gb/strings.po`
- Test: `tests/test_addon_manifest.py`

**Interfaces:**
- Produces: addon id `script.twitch.center`, referenced by no code in this plan but required to
  exist for Task 6's smoke expectations and for future Kodi install testing.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_addon_manifest.py
import xml.etree.ElementTree as ET
from pathlib import Path

ADDON_XML = Path(__file__).resolve().parent.parent / "addon.xml"


def test_addon_xml_parses_with_expected_id():
    tree = ET.parse(ADDON_XML)
    root = tree.getroot()
    assert root.tag == "addon"
    assert root.attrib["id"] == "script.twitch.center"
    assert root.attrib["name"] == "Twitch Center"


def test_addon_xml_declares_script_extension():
    tree = ET.parse(ADDON_XML)
    root = tree.getroot()
    extensions = root.findall("extension")
    points = [ext.attrib.get("point") for ext in extensions]
    assert "xbmc.python.script" in points
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_addon_manifest.py -v`
Expected: FAIL with `FileNotFoundError` (no `addon.xml` yet).

- [ ] **Step 3: Write `addon.xml`**

```xml
<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<addon id="script.twitch.center" name="Twitch Center" version="0.1.0" provider-name="drachenhort">
  <requires>
    <import addon="xbmc.python" version="3.0.0"/>
  </requires>
  <extension point="xbmc.python.script" library="lib/main.py">
    <provides>executable</provides>
  </extension>
  <extension point="xbmc.addon.metadata">
    <summary lang="en_GB">Watch Twitch streams and chat from Kodi</summary>
    <description lang="en_GB">
      View Twitch streams using Kodi's own playback, with a paired IRC chat view. Not designed
      for chatting back to streamers - a second way to consume streamer-generated content.
    </description>
    <platform>all</platform>
    <license>MIT</license>
    <source>https://github.com/drachenhort/twitch-center</source>
  </extension>
</addon>
```

- [ ] **Step 4: Write `resources/settings.xml`**

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
      </group>
    </category>
  </section>
</settings>
```

- [ ] **Step 5: Write `resources/language/resource.language.en_gb/strings.po`**

```
# Kodi Media Center language file
msgid ""
msgstr ""

msgctxt "#30000"
msgid "General"
msgstr ""

msgctxt "#30001"
msgid "Chat display mode"
msgstr ""

msgctxt "#30002"
msgid "Overlay during playback"
msgstr ""

msgctxt "#30003"
msgid "Standalone chat window"
msgstr ""

msgctxt "#30004"
msgid "Both"
msgstr ""
```

- [ ] **Step 6: Run test to verify it passes**

Run: `pytest tests/test_addon_manifest.py -v`
Expected: PASS (2 tests).

- [ ] **Step 7: Commit**

```bash
git add addon.xml resources/settings.xml resources/language/resource.language.en_gb/strings.po tests/test_addon_manifest.py
git commit -m "feat: add Kodi addon manifest and settings skeleton"
```

---

### Task 2: Kodi stub modules for testing

**Files:**
- Create: `tests/kodi_stubs/xbmc.py`
- Create: `tests/kodi_stubs/xbmcgui.py`
- Create: `tests/kodi_stubs/xbmcaddon.py`
- Create: `tests/conftest.py`
- Test: `tests/test_kodi_stubs.py`

**Interfaces:**
- Produces: `xbmc.LOGINFO`, `xbmc.LOGERROR`, `xbmc.log(msg, level=...)`; `xbmcgui.WindowXML`,
  `xbmcgui.WindowXMLDialog` (both no-op base classes accepting `(xml_filename, script_path,
  default_skin="Default", default_res="1080i")` and exposing `.show()`, `.close()`, `.doModal()`
  as no-ops); `xbmcaddon.Addon` with `.getSetting(id) -> str`, `.getSettingBool(id) -> bool`,
  `.getAddonInfo(key) -> str`. These are consumed by Task 4's `lib/windows/*` and
  `lib/settings.py`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_kodi_stubs.py
def test_xbmc_stub_importable():
    import xbmc
    assert xbmc.LOGINFO is not None
    xbmc.log("hello", level=xbmc.LOGINFO)  # must not raise


def test_xbmcgui_stub_windowxml_constructible():
    import xbmcgui
    win = xbmcgui.WindowXML("dummy.xml", "/tmp")
    win.show()
    win.close()


def test_xbmcgui_stub_windowxmldialog_constructible():
    import xbmcgui
    dlg = xbmcgui.WindowXMLDialog("dummy.xml", "/tmp")
    dlg.doModal()
    dlg.close()


def test_xbmcaddon_stub_addon_getters():
    import xbmcaddon
    addon = xbmcaddon.Addon()
    assert addon.getSetting("chat_display_mode") == ""
    assert addon.getSettingBool("does_not_exist") is False
    assert addon.getAddonInfo("id") == "script.twitch.center"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_kodi_stubs.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'xbmc'`.

- [ ] **Step 3: Write `tests/kodi_stubs/xbmc.py`**

```python
"""Minimal stand-in for Kodi's built-in xbmc module, for pytest-only use."""

LOGDEBUG = 0
LOGINFO = 1
LOGWARNING = 2
LOGERROR = 3
LOGFATAL = 4


def log(msg, level=LOGINFO):
    pass
```

- [ ] **Step 4: Write `tests/kodi_stubs/xbmcgui.py`**

```python
"""Minimal stand-in for Kodi's built-in xbmcgui module, for pytest-only use."""


class WindowXML:
    def __init__(self, xml_filename, script_path, default_skin="Default", default_res="1080i"):
        self.xml_filename = xml_filename
        self.script_path = script_path

    def show(self):
        pass

    def close(self):
        pass


class WindowXMLDialog(WindowXML):
    def doModal(self):
        pass
```

- [ ] **Step 5: Write `tests/kodi_stubs/xbmcaddon.py`**

```python
"""Minimal stand-in for Kodi's built-in xbmcaddon module, for pytest-only use."""

_ADDON_INFO = {
    "id": "script.twitch.center",
    "name": "Twitch Center",
    "version": "0.1.0",
}


class Addon:
    def __init__(self, id=None):
        self._settings = {}

    def getSetting(self, id):
        return self._settings.get(id, "")

    def getSettingBool(self, id):
        return bool(self._settings.get(id, False))

    def setSetting(self, id, value):
        self._settings[id] = value

    def getAddonInfo(self, key):
        return _ADDON_INFO.get(key, "")
```

- [ ] **Step 6: Write `tests/conftest.py`**

```python
"""Registers Kodi stub modules onto sys.path before any test imports lib.windows/lib.settings."""
import sys
from pathlib import Path

_KODI_STUBS_DIR = Path(__file__).resolve().parent / "kodi_stubs"
sys.path.insert(0, str(_KODI_STUBS_DIR))
```

- [ ] **Step 7: Run test to verify it passes**

Run: `pytest tests/test_kodi_stubs.py -v`
Expected: PASS (4 tests).

- [ ] **Step 8: Commit**

```bash
git add tests/kodi_stubs tests/conftest.py tests/test_kodi_stubs.py
git commit -m "test: add Kodi module stubs for pytest-only testing"
```

---

### Task 3: `lib/twitch` package stubs

**Files:**
- Create: `lib/__init__.py`
- Create: `lib/twitch/__init__.py`
- Create: `lib/twitch/auth.py`
- Create: `lib/twitch/api.py`
- Create: `lib/twitch/stream.py`
- Create: `lib/twitch/irc.py`
- Test: `tests/twitch/test_auth.py`
- Test: `tests/twitch/test_api.py`
- Test: `tests/twitch/test_stream.py`
- Test: `tests/twitch/test_irc.py`

**Interfaces:**
- Produces (all raise `NotImplementedError` when called — signatures are the contract later
  plans implement against):
  - `auth.request_device_code(client_id: str) -> dict`
  - `auth.poll_for_token(client_id: str, device_code: str, interval: int) -> dict`
  - `auth.save_token(token: dict) -> None`
  - `auth.load_token() -> dict | None`
  - `api.get_followed_channels(access_token: str, user_id: str) -> list[dict]`
  - `api.get_live_status(access_token: str, user_ids: list[str]) -> list[dict]`
  - `api.get_games_for_channels(access_token: str, user_ids: list[str]) -> dict[str, str]`
  - `api.get_live_streams_by_game(access_token: str, game_id: str) -> list[dict]`
  - `api.search_channels(access_token: str, query: str) -> list[dict]`
  - `stream.resolve_stream_url(channel_name: str) -> str`
  - `irc.ChatClient(channel: str)` with `.connect() -> None`, `.read_messages() -> Iterator[dict]`,
    `.disconnect() -> None`

- [ ] **Step 1: Write the failing tests**

```python
# tests/twitch/test_auth.py
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
```

```python
# tests/twitch/test_api.py
import pytest
from lib.twitch import api


def test_get_followed_channels_not_implemented():
    with pytest.raises(NotImplementedError):
        api.get_followed_channels("token", "user-id")


def test_get_live_status_not_implemented():
    with pytest.raises(NotImplementedError):
        api.get_live_status("token", ["user-id"])


def test_get_games_for_channels_not_implemented():
    with pytest.raises(NotImplementedError):
        api.get_games_for_channels("token", ["user-id"])


def test_get_live_streams_by_game_not_implemented():
    with pytest.raises(NotImplementedError):
        api.get_live_streams_by_game("token", "game-id")


def test_search_channels_not_implemented():
    with pytest.raises(NotImplementedError):
        api.search_channels("token", "query")
```

```python
# tests/twitch/test_stream.py
import pytest
from lib.twitch import stream


def test_resolve_stream_url_not_implemented():
    with pytest.raises(NotImplementedError):
        stream.resolve_stream_url("some_channel")
```

```python
# tests/twitch/test_irc.py
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/twitch/ -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'lib'` (package doesn't exist yet).

- [ ] **Step 3: Write `lib/__init__.py` and `lib/twitch/__init__.py`**

```python
# lib/__init__.py
```

```python
# lib/twitch/__init__.py
```

- [ ] **Step 4: Write `lib/twitch/auth.py`**

```python
"""Twitch OAuth device-code flow. No xbmc* imports - pure Python, pytest-testable."""


def request_device_code(client_id):
    """Start the device-code flow. Returns dict with device_code, user_code,
    verification_uri, expires_in, interval (per Twitch's device-code response)."""
    raise NotImplementedError


def poll_for_token(client_id, device_code, interval):
    """Poll Twitch's token endpoint until the user authorizes the device code.
    Returns dict with access_token, refresh_token, expires_in, scope, token_type."""
    raise NotImplementedError


def save_token(token):
    """Persist a token dict to local storage."""
    raise NotImplementedError


def load_token():
    """Load a previously saved token dict, or None if none saved."""
    return None
```

- [ ] **Step 5: Write `lib/twitch/api.py`**

```python
"""Twitch Helix API calls. No xbmc* imports - pure Python, pytest-testable."""


def get_followed_channels(access_token, user_id):
    """Return the user's followed channels as a list of dicts (Helix
    /channels/followed), each with at least broadcaster_id, broadcaster_login,
    broadcaster_name."""
    raise NotImplementedError


def get_live_status(access_token, user_ids):
    """Return live-stream info (Helix /streams) for the given broadcaster user_ids -
    only entries for currently-live channels are returned."""
    raise NotImplementedError


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

- [ ] **Step 6: Write `lib/twitch/stream.py`**

```python
"""Resolves a Twitch channel name to a playable HLS URL via Twitch's GraphQL +
usher.ttvnw.net access-token endpoints. No xbmc* imports - pure Python, pytest-testable."""


def resolve_stream_url(channel_name):
    """Return a direct HLS (.m3u8) URL Kodi's player can open for the given
    live channel name."""
    raise NotImplementedError
```

- [ ] **Step 7: Write `lib/twitch/irc.py`**

```python
"""IRC chat client for irc.chat.twitch.tv. No xbmc* imports - pure Python, pytest-testable."""


class ChatClient:
    def __init__(self, channel):
        self.channel = channel

    def connect(self):
        """Open the IRC socket connection and authenticate."""
        raise NotImplementedError

    def read_messages(self):
        """Yield chat message dicts (at least: username, message, timestamp) as they arrive."""
        raise NotImplementedError

    def disconnect(self):
        """Close the IRC socket connection."""
        raise NotImplementedError
```

- [ ] **Step 8: Run tests to verify they pass**

Run: `pytest tests/twitch/ -v`
Expected: PASS (11 tests).

- [ ] **Step 9: Commit**

```bash
git add lib/__init__.py lib/twitch tests/twitch
git commit -m "feat: add lib.twitch stub package (auth, api, stream, irc)"
```

---

### Task 4: `lib/windows` package stubs and `lib/settings.py`

**Files:**
- Create: `lib/settings.py`
- Create: `lib/windows/__init__.py`
- Create: `lib/windows/login.py`
- Create: `lib/windows/home.py`
- Create: `lib/windows/discover.py`
- Create: `lib/windows/player.py`
- Create: `lib/windows/chat_overlay.py`
- Create: `lib/windows/chat_window.py`
- Test: `tests/test_settings.py`
- Test: `tests/windows/test_windows_stubs.py`

**Interfaces:**
- Consumes: `xbmcgui.WindowXML`, `xbmcgui.WindowXMLDialog`, `xbmcaddon.Addon` (Task 2's stubs when
  under pytest; the real Kodi modules when run inside Kodi).
- Produces:
  - `settings.Settings().chat_display_mode -> str` (one of `"overlay"`, `"standalone"`, `"both"`)
  - `windows.login.LoginWindow`, `windows.home.HomeWindow`, `windows.discover.DiscoverWindow`
    (each `xbmcgui.WindowXML` subclasses with a no-op `onInit`)
  - `windows.player.play_stream(url: str) -> None`
  - `windows.chat_overlay.ChatOverlay`, `windows.chat_window.ChatWindow` (each
    `xbmcgui.WindowXMLDialog`/`WindowXML` subclasses with a no-op `onInit`)

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_settings.py
from lib.settings import Settings


def test_chat_display_mode_defaults_to_both():
    settings = Settings()
    assert settings.chat_display_mode == "both"


def test_chat_display_mode_reads_addon_setting():
    settings = Settings()
    settings._addon.setSetting("chat_display_mode", "overlay")
    assert settings.chat_display_mode == "overlay"
```

```python
# tests/windows/test_windows_stubs.py
from lib.windows.login import LoginWindow
from lib.windows.home import HomeWindow
from lib.windows.discover import DiscoverWindow
from lib.windows.player import play_stream
from lib.windows.chat_overlay import ChatOverlay
from lib.windows.chat_window import ChatWindow


def test_login_window_constructs():
    win = LoginWindow("login.xml", "/tmp")
    win.onInit()


def test_home_window_constructs():
    win = HomeWindow("home.xml", "/tmp")
    win.onInit()


def test_discover_window_constructs():
    win = DiscoverWindow("discover.xml", "/tmp")
    win.onInit()


def test_chat_overlay_constructs():
    overlay = ChatOverlay("chat_overlay.xml", "/tmp")
    overlay.onInit()


def test_chat_window_constructs():
    win = ChatWindow("chat_window.xml", "/tmp")
    win.onInit()


def test_play_stream_is_stubbed():
    import pytest
    with pytest.raises(NotImplementedError):
        play_stream("https://example.invalid/stream.m3u8")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_settings.py tests/windows/ -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'lib.settings'`.

- [ ] **Step 3: Write `lib/settings.py`**

```python
"""Typed wrapper over xbmcaddon settings. Only lib/windows.py and this module touch xbmcaddon."""
import xbmcaddon

VALID_CHAT_DISPLAY_MODES = ("overlay", "standalone", "both")
DEFAULT_CHAT_DISPLAY_MODE = "both"


class Settings:
    def __init__(self, addon=None):
        self._addon = addon or xbmcaddon.Addon()

    @property
    def chat_display_mode(self):
        value = self._addon.getSetting("chat_display_mode")
        if value in VALID_CHAT_DISPLAY_MODES:
            return value
        return DEFAULT_CHAT_DISPLAY_MODE
```

- [ ] **Step 4: Write `lib/windows/__init__.py`**

```python
# lib/windows/__init__.py
```

- [ ] **Step 5: Write `lib/windows/login.py`**

```python
"""Device-code login screen: displays the code + verification URL, polls for auth."""
import xbmcgui


class LoginWindow(xbmcgui.WindowXML):
    def onInit(self):
        """Populate the device code / verification URL and start polling. Stubbed."""
        pass
```

- [ ] **Step 6: Write `lib/windows/home.py`**

```python
"""Home screen: the user's followed channels, live ones surfaced first."""
import xbmcgui


class HomeWindow(xbmcgui.WindowXML):
    def onInit(self):
        """Load and render followed channels. Stubbed."""
        pass
```

- [ ] **Step 7: Write `lib/windows/discover.py`**

```python
"""Discover screen: browse live channels by game (derived from followed channels'
games), or free-text search for any channel by name."""
import xbmcgui


class DiscoverWindow(xbmcgui.WindowXML):
    def onInit(self):
        """Load game categories and render browse/search UI. Stubbed."""
        pass
```

- [ ] **Step 8: Write `lib/windows/player.py`**

```python
"""Launches Kodi's native player for a resolved Twitch stream URL."""


def play_stream(url):
    """Hand the resolved HLS URL to Kodi's player."""
    raise NotImplementedError
```

- [ ] **Step 9: Write `lib/windows/chat_overlay.py`**

```python
"""Non-modal chat overlay shown during playback."""
import xbmcgui


class ChatOverlay(xbmcgui.WindowXMLDialog):
    def onInit(self):
        """Connect to chat and start rendering incoming messages. Stubbed."""
        pass
```

- [ ] **Step 10: Write `lib/windows/chat_window.py`**

```python
"""Standalone full-screen chat view."""
import xbmcgui


class ChatWindow(xbmcgui.WindowXML):
    def onInit(self):
        """Connect to chat and start rendering incoming messages. Stubbed."""
        pass
```

- [ ] **Step 11: Run tests to verify they pass**

Run: `pytest tests/test_settings.py tests/windows/ -v`
Expected: PASS (7 tests).

- [ ] **Step 12: Commit**

```bash
git add lib/settings.py lib/windows tests/test_settings.py tests/windows
git commit -m "feat: add lib.windows stub package and lib.settings"
```

---

### Task 5: `lib/main.py` entry point and full-package smoke test

**Files:**
- Create: `lib/main.py`
- Test: `tests/test_smoke.py`

**Interfaces:**
- Consumes: `lib.twitch.auth`, `lib.twitch.api`, `lib.twitch.stream`, `lib.twitch.irc` (Task 3),
  `lib.windows.login`, `lib.windows.home`, `lib.windows.discover`, `lib.windows.player`,
  `lib.windows.chat_overlay`, `lib.windows.chat_window`, `lib.settings` (Task 4).
- Produces: `main.run(argv: list[str]) -> None` — the addon's entry point, referenced by
  `addon.xml`'s `library="lib/main.py"`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_smoke.py
"""Baseline 'does this even load' check across the whole lib package."""
import importlib


MODULES = [
    "lib.twitch.auth",
    "lib.twitch.api",
    "lib.twitch.stream",
    "lib.twitch.irc",
    "lib.windows.login",
    "lib.windows.home",
    "lib.windows.discover",
    "lib.windows.player",
    "lib.windows.chat_overlay",
    "lib.windows.chat_window",
    "lib.settings",
    "lib.main",
]


def test_all_lib_modules_import_cleanly():
    for module_name in MODULES:
        importlib.import_module(module_name)


def test_main_run_is_callable():
    from lib import main
    assert callable(main.run)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_smoke.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'lib.main'`.

- [ ] **Step 3: Write `lib/main.py`**

```python
"""Addon entry point, referenced by addon.xml's library="lib/main.py"."""
import sys


def run(argv):
    """Route to the appropriate window based on saved auth state. Stubbed - routing
    logic (login vs. home) lands in a follow-up implementation plan."""
    raise NotImplementedError


if __name__ == "__main__":
    run(sys.argv)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_smoke.py -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Run the full test suite**

Run: `pip install -r requirements-dev.txt && pytest -v`
Expected: PASS, all tests across `tests/` green (26 tests total across Tasks 1-5).

- [ ] **Step 6: Commit**

```bash
git add lib/main.py tests/test_smoke.py
git commit -m "feat: add lib.main entry point and full-package smoke test"
```

---

## Post-plan state

After Task 5, `twitch-center` is an installable-shaped Kodi addon with every module boundary from
the design spec in place, fully stubbed, and covered by a green `pytest` suite. Nothing plays a
stream, authenticates, or renders real UI yet — those are separate follow-up plans per the spec's
"Follow-up specs" list (device-code auth, stream resolution, IRC chat, Home screen, Discover
screen), each starting from `superpowers:brainstorming` or directly from `superpowers:writing-plans`
if the design is already clear enough.
