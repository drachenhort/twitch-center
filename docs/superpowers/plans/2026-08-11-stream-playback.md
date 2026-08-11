# Stream Playback Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Clicking a live channel in Home's followed-channels list or Discover's results list
actually starts playback in Kodi, using verified-real GraphQL/usher endpoints and
`inputstream.adaptive` for proper adaptive-bitrate HLS.

**Architecture:** `lib/twitch/gql.py` gains `get_playback_access_token` (raises `api.TokenExpiredError`
on 401 — a deliberate, documented exception to this module's usual best-effort convention, since
playback failures must be retryable, not decorative). `lib/twitch/stream.py` (currently a stub)
becomes the real URL-resolution layer, raising a new `StreamUnavailableError` for genuine
unavailability while letting `TokenExpiredError` propagate untouched. `lib/windows/player.py`
(currently a stub) becomes the real Kodi-player layer via `inputstreamhelper`. `lib/windows/home.py`
and `lib/windows/discover.py` wire click-to-play into their existing lists, and Home's
`_handle_expired_token` gets the same `on_success`/`on_error` generalization Discover already has
(Home has never needed it until now — playback is its first network-backed action outside `onInit`).

**Tech Stack:** Python 3, `requests`, `script.module.inputstreamhelper` (new addon dependency,
already present on the target system), `pytest` + `unittest.mock`.

## Global Constraints

- Verified-real values (do not alter): GraphQL `POST https://gql.twitch.tv/gql`, operation
  `PlaybackAccessToken`, persisted query hash
  `ed230aa1e33e07eebb8928504583da78a5173989fadfb1ac94be06a04f3cdbe9`, variables
  `{"isLive": true, "login": <channel_login>, "isVod": false, "vodID": "", "playerType": "site",
  "platform": "web"}`, request body is a **plain dict, not array-wrapped** (unlike
  `FollowingGames_CurrentUser`'s batched array form) — headers `Client-Id:
  kimne78kx3ncx6brgo4mv6wki5h1ko` + `Authorization: OAuth <access_token>`. Response:
  `data.streamPlaybackAccessToken.{value, signature}` (also **not** array-wrapped). Usher URL:
  `https://usher.ttvnw.net/api/channel/hls/<channel_login>.m3u8?token=<url-encoded
  value>&sig=<signature>&allow_source=true&fast_bread=true&player_backend=mediaplayer`.
- `lib/twitch/*` must have zero `xbmc*` imports — enforced by `tests/test_architecture.py`.
  `gql.py` and `stream.py` import only `requests` (`stream.py` also imports `gql` and `urllib.parse`,
  both stdlib/sibling-module, not `xbmc*`).
- `gql.get_playback_access_token` raises `api.TokenExpiredError` on 401; returns `None` on every
  other failure; never raises for anything else.
- `stream.resolve_stream_url` raises `StreamUnavailableError` when the token comes back `None`;
  lets `api.TokenExpiredError` propagate unchanged.
- `player.play_stream` returns `True`/`False`, never raises for the "user declined install" case.
- Offline items: clicking does nothing (silent no-op), not an error.
- `pip install -r requirements-dev.txt && pytest` must pass after every task.
- No test makes a real network call, hits Kodi's real player, or hits `inputstreamhelper`'s real
  install-prompt UI.

---

## File Structure

```
addon.xml                          # modify: add script.module.inputstreamhelper dependency
lib/
  twitch/
    gql.py                         # modify: add get_playback_access_token
    stream.py                      # modify: real implementation
  windows/
    player.py                      # modify: real implementation
    home.py                        # modify: click-to-play wiring, _handle_expired_token generalized
    discover.py                    # modify: click-to-play wiring
tests/
  kodi_stubs/
    xbmc.py                        # modify: add Player class
    xbmcgui.py                     # modify: ListItem gains path/mimetype/content-lookup
    inputstreamhelper.py           # create: Helper stub
  test_kodi_stubs.py               # modify: new tests for the above
  test_addon_manifest.py           # modify: assert inputstreamhelper dependency declared
  twitch/
    test_gql.py                   # modify: add get_playback_access_token tests
    test_stream.py                 # modify: full replacement (real implementation tests)
  windows/
    test_player.py                 # create
    test_home_window.py            # modify: click-to-play tests
    test_discover_window.py        # modify: click-to-play tests
```

---

### Task 1: Extend Kodi stubs for playback (Player, ListItem path/mimetype, inputstreamhelper)

**Files:**
- Modify: `tests/kodi_stubs/xbmc.py`
- Modify: `tests/kodi_stubs/xbmcgui.py`
- Create: `tests/kodi_stubs/inputstreamhelper.py`
- Modify: `tests/test_kodi_stubs.py`

**Interfaces:**
- Produces: `xbmc.Player` (no-op `.play(item=None, listitem=None, windowed=False, startpos=-1)`,
  matching `xbmc.Monitor`'s existing no-op-stand-in style — tests needing to assert on calls patch
  it directly, same as tests already do for `xbmc.Monitor`/`xbmcaddon.Addon`); `ListItem.__init__`
  gains `path=""`, plus `setPath`/`getPath`/`setMimeType`/`getMimeType`/`setContentLookup`/
  `getContentLookup`; `inputstreamhelper.Helper(protocol, drm=None)` with `.inputstream_addon =
  "inputstream.adaptive"` and `.check_inputstream() -> True` (default; tests override via
  `unittest.mock.patch`).
- Consumed by: Task 3's `lib/windows/player.py`.

- [ ] **Step 1: Write the failing tests**

```python
# Append to tests/test_kodi_stubs.py

def test_xbmc_stub_player_play_does_not_raise():
    import xbmc
    player = xbmc.Player()
    player.play("https://example.invalid/stream.m3u8")


def test_xbmcgui_stub_listitem_path_and_playback_properties():
    import xbmcgui
    item = xbmcgui.ListItem(path="https://example.invalid/stream.m3u8")
    assert item.getPath() == "https://example.invalid/stream.m3u8"
    item.setPath("https://example.invalid/other.m3u8")
    assert item.getPath() == "https://example.invalid/other.m3u8"
    item.setMimeType("application/x-mpegURL")
    assert item.getMimeType() == "application/x-mpegURL"
    item.setContentLookup(False)
    assert item.getContentLookup() is False


def test_inputstreamhelper_stub_helper_check_inputstream():
    import inputstreamhelper
    helper = inputstreamhelper.Helper("hls")
    assert helper.inputstream_addon == "inputstream.adaptive"
    assert helper.check_inputstream() is True
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_kodi_stubs.py -v`
Expected: FAIL — `xbmc.Player`, `ListItem`'s `path`/mimetype support, and the `inputstreamhelper`
module don't exist yet.

- [ ] **Step 3: Add `Player` to `tests/kodi_stubs/xbmc.py`** (append after the existing `Monitor`
class; everything else in the file stays unchanged)

```python
class Player:
    """Minimal stand-in for xbmc.Player; real Kodi starts playback."""

    def play(self, item=None, listitem=None, windowed=False, startpos=-1):
        pass
```

- [ ] **Step 4: Update `ListItem` in `tests/kodi_stubs/xbmcgui.py`**

Replace the existing `ListItem.__init__` and add the new methods (every other `ListItem` method —
`setLabel`/`getLabel`/`setLabel2`/`getLabel2`/`setArt`/`getArt`/`setProperty`/`getProperty` — stays
exactly as-is):

```python
class ListItem:
    def __init__(self, label="", path=""):
        self._label = label
        self._label2 = ""
        self._art = {}
        self._properties = {}
        self._path = path
        self._mimetype = ""
        self._content_lookup = True

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

    def setPath(self, path):
        self._path = path

    def getPath(self):
        return self._path

    def setMimeType(self, mimetype):
        self._mimetype = mimetype

    def getMimeType(self):
        return self._mimetype

    def setContentLookup(self, enabled):
        self._content_lookup = enabled

    def getContentLookup(self):
        return self._content_lookup
```

- [ ] **Step 5: Create `tests/kodi_stubs/inputstreamhelper.py`**

```python
"""Minimal stand-in for script.module.inputstreamhelper, for pytest-only use."""


class Helper:
    def __init__(self, protocol, drm=None):
        self.protocol = protocol
        self.drm = drm
        self.inputstream_addon = "inputstream.adaptive"

    def check_inputstream(self):
        return True
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_kodi_stubs.py -v`
Expected: PASS (all existing tests plus the 3 new ones).

- [ ] **Step 7: Run the full suite**

Run: `.venv/bin/pytest -v`
Expected: PASS — purely additive; `ListItem.__init__`'s new `path=""` default keeps every existing
`xbmcgui.ListItem(label)`-style call working unchanged.

- [ ] **Step 8: Commit**

```bash
git add tests/kodi_stubs/xbmc.py tests/kodi_stubs/xbmcgui.py tests/kodi_stubs/inputstreamhelper.py tests/test_kodi_stubs.py
git commit -m "test: add Kodi Player/ListItem-path/inputstreamhelper stubs for playback"
```

---

### Task 2: `lib/twitch/gql.py` playback token + `lib/twitch/stream.py` real implementation

**Files:**
- Modify: `lib/twitch/gql.py`
- Modify: `lib/twitch/stream.py`
- Modify: `tests/twitch/test_gql.py`
- Modify: `tests/twitch/test_stream.py`

**Interfaces:**
- Produces:
  - `gql.get_playback_access_token(access_token, channel_login) -> dict | None` — raises
    `api.TokenExpiredError` on HTTP 401; returns `None` on any other failure; returns
    `{"value": ..., "signature": ...}` on success.
  - `stream.StreamUnavailableError(Exception)` — new.
  - `stream.resolve_stream_url(access_token, channel_login) -> str` — raises
    `StreamUnavailableError` if the token is `None`; lets `api.TokenExpiredError` propagate; returns
    the usher master-playlist URL on success.
- Consumed by: Task 3's `lib/windows/player.py` is NOT a consumer (player.py only plays a URL, it
  doesn't resolve one) — this task's consumers are Task 4/5's `lib/windows/home.py` and
  `lib/windows/discover.py`.

- [ ] **Step 1: Write the failing tests**

```python
# Append to tests/twitch/test_gql.py
# (this file already has `from unittest.mock import MagicMock, patch`, `import requests`,
# `from lib.twitch import gql`, and a `_response(json_body, status_code=200)` helper - reuse them,
# don't redefine)

from lib.twitch import api


def test_get_playback_access_token_returns_value_and_signature_on_success():
    body = {
        "data": {
            "streamPlaybackAccessToken": {"value": "opaque-token-json", "signature": "abc123"}
        }
    }
    with patch.object(gql.requests, "post", return_value=_response(body)) as mock_post:
        result = gql.get_playback_access_token("access-token", "somechannel")
    assert result == {"value": "opaque-token-json", "signature": "abc123"}
    payload = mock_post.call_args.kwargs["json"]
    assert payload["operationName"] == "PlaybackAccessToken"
    assert payload["variables"] == {
        "isLive": True,
        "login": "somechannel",
        "isVod": False,
        "vodID": "",
        "playerType": "site",
        "platform": "web",
    }
    assert (
        payload["extensions"]["persistedQuery"]["sha256Hash"]
        == "ed230aa1e33e07eebb8928504583da78a5173989fadfb1ac94be06a04f3cdbe9"
    )
    headers = mock_post.call_args.kwargs["headers"]
    assert headers["Client-Id"] == gql.WEB_CLIENT_ID
    assert headers["Authorization"] == "OAuth access-token"


def test_get_playback_access_token_raises_token_expired_on_401():
    with patch.object(gql.requests, "post", return_value=_response({}, status_code=401)):
        with pytest.raises(api.TokenExpiredError):
            gql.get_playback_access_token("access-token", "somechannel")


def test_get_playback_access_token_returns_none_on_network_error():
    with patch.object(gql.requests, "post", side_effect=requests.ConnectionError("boom")):
        assert gql.get_playback_access_token("access-token", "somechannel") is None


def test_get_playback_access_token_returns_none_on_other_non_200():
    with patch.object(gql.requests, "post", return_value=_response({}, status_code=500)):
        assert gql.get_playback_access_token("access-token", "somechannel") is None


def test_get_playback_access_token_returns_none_on_missing_token_data():
    body = {"data": {"streamPlaybackAccessToken": None}}
    with patch.object(gql.requests, "post", return_value=_response(body)):
        assert gql.get_playback_access_token("access-token", "somechannel") is None


def test_get_playback_access_token_returns_none_on_unexpected_shape():
    with patch.object(gql.requests, "post", return_value=_response({"unexpected": "shape"})):
        assert gql.get_playback_access_token("access-token", "somechannel") is None
```

Add `import pytest` to `tests/twitch/test_gql.py`'s imports if not already present (check the file
first — it may not need `pytest` yet since no prior test in it used `pytest.raises`).

```python
# tests/twitch/test_stream.py (full replacement)
from unittest.mock import patch

import pytest

from lib.twitch import api, gql, stream


def test_resolve_stream_url_builds_usher_url_on_success():
    token = {"value": "opaque-token-json", "signature": "abc123"}
    with patch.object(gql, "get_playback_access_token", return_value=token) as mock_get_token:
        url = stream.resolve_stream_url("access-token", "somechannel")
    mock_get_token.assert_called_once_with("access-token", "somechannel")
    assert url == (
        "https://usher.ttvnw.net/api/channel/hls/somechannel.m3u8"
        "?token=opaque-token-json&sig=abc123"
        "&allow_source=true&fast_bread=true&player_backend=mediaplayer"
    )


def test_resolve_stream_url_url_encodes_the_token_value():
    token = {"value": "value with spaces & symbols", "signature": "abc123"}
    with patch.object(gql, "get_playback_access_token", return_value=token):
        url = stream.resolve_stream_url("access-token", "somechannel")
    assert "value%20with%20spaces%20%26%20symbols" in url


def test_resolve_stream_url_raises_stream_unavailable_when_token_is_none():
    with patch.object(gql, "get_playback_access_token", return_value=None):
        with pytest.raises(stream.StreamUnavailableError):
            stream.resolve_stream_url("access-token", "somechannel")


def test_resolve_stream_url_lets_token_expired_error_propagate():
    with patch.object(gql, "get_playback_access_token", side_effect=api.TokenExpiredError()):
        with pytest.raises(api.TokenExpiredError):
            stream.resolve_stream_url("access-token", "somechannel")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/twitch/test_gql.py tests/twitch/test_stream.py -v`
Expected: FAIL — `get_playback_access_token` doesn't exist; `stream.resolve_stream_url` raises
`NotImplementedError` with the old scaffold signature (takes only `channel_name`, no
`access_token`).

- [ ] **Step 3: Modify `lib/twitch/gql.py`**

Add the import and the new function. The rest of the file (`GQL_URL`, `WEB_CLIENT_ID`,
`_FOLLOWING_GAMES_QUERY_HASH`, `get_followed_live_games`) stays exactly as-is:

```python
"""Twitch's unofficial internal GraphQL API. No xbmc* imports - pure Python.
...
```
(keep the existing module docstring unchanged)

```python
import requests

from lib.twitch import api

GQL_URL = "https://gql.twitch.tv/gql"
WEB_CLIENT_ID = "kimne78kx3ncx6brgo4mv6wki5h1ko"

_FOLLOWING_GAMES_QUERY_HASH = "f3c5d45175d623ed3d5ff4ca4c7de379ea6a1a4852236087dc1b81b7dbfd3114"
_PLAYBACK_ACCESS_TOKEN_QUERY_HASH = "ed230aa1e33e07eebb8928504583da78a5173989fadfb1ac94be06a04f3cdbe9"
```

(add the `from lib.twitch import api` import and the new hash constant; `get_followed_live_games`
stays untouched below this point)

Add after `get_followed_live_games`:

```python
def get_playback_access_token(access_token, channel_login):
    """Return a {"value", "signature"} playback access token for the given
    live channel login, or None on any non-401 failure (network error,
    non-200, unexpected response shape) - never raises for those. Raises
    api.TokenExpiredError on HTTP 401, unlike get_followed_live_games's pure
    best-effort convention: playback is not decoration, so an expired token
    here must be distinguishable from genuine unavailability, to let the
    caller retry after a refresh rather than just failing silently.

    "value" is an opaque JSON string Twitch issues - never parse it, just
    pass it through unchanged to usher.ttvnw.net."""
    try:
        response = requests.post(
            GQL_URL,
            json={
                "operationName": "PlaybackAccessToken",
                "variables": {
                    "isLive": True,
                    "login": channel_login,
                    "isVod": False,
                    "vodID": "",
                    "playerType": "site",
                    "platform": "web",
                },
                "extensions": {
                    "persistedQuery": {
                        "version": 1,
                        "sha256Hash": _PLAYBACK_ACCESS_TOKEN_QUERY_HASH,
                    }
                },
            },
            headers={
                "Client-Id": WEB_CLIENT_ID,
                "Authorization": "OAuth " + access_token,
            },
            timeout=10,
        )
    except requests.RequestException:
        return None

    if response.status_code == 401:
        raise api.TokenExpiredError()
    if response.status_code != 200:
        return None

    try:
        body = response.json()
        token = body["data"]["streamPlaybackAccessToken"]
        value = token["value"]
        signature = token["signature"]
    except (ValueError, KeyError, TypeError):
        return None

    if not value or not signature:
        return None

    return {"value": value, "signature": signature}
```

- [ ] **Step 4: Write `lib/twitch/stream.py`** (full replacement)

```python
"""Resolves a Twitch channel name to a playable HLS URL via Twitch's GraphQL +
usher.ttvnw.net access-token endpoints. No xbmc* imports - pure Python, pytest-testable."""
from urllib.parse import quote

from lib.twitch import gql

USHER_BASE = "https://usher.ttvnw.net"


class StreamUnavailableError(Exception):
    """Raised when a channel's stream can't be resolved to a playable URL -
    the channel isn't live, Twitch denied access, or the underlying request
    failed for a non-401 reason. api.TokenExpiredError (a 401) is NOT wrapped
    here - it propagates unchanged so the caller can refresh and retry rather
    than treating an expired token the same as "this stream doesn't exist"."""


def resolve_stream_url(access_token, channel_login):
    """Return a direct HLS (.m3u8) URL Kodi's player can open for the given
    live channel login. Raises StreamUnavailableError if it can't be
    resolved; raises api.TokenExpiredError (via gql.get_playback_access_token)
    if the access token has expired."""
    token = gql.get_playback_access_token(access_token, channel_login)
    if token is None:
        raise StreamUnavailableError(channel_login)
    return (
        USHER_BASE
        + "/api/channel/hls/"
        + channel_login
        + ".m3u8"
        + "?token="
        + quote(token["value"], safe="")
        + "&sig="
        + token["signature"]
        + "&allow_source=true&fast_bread=true&player_backend=mediaplayer"
    )
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/twitch/test_gql.py tests/twitch/test_stream.py -v`
Expected: PASS (11 tests in `test_gql.py` total: 5 pre-existing + 6 new; 4 tests in `test_stream.py`,
full replacement of the previous 1).

- [ ] **Step 6: Run the full suite**

Run: `.venv/bin/pytest -v`
Expected: PASS. `tests/test_architecture.py` must still pass — `gql.py` now imports `requests` and
`lib.twitch.api` (which itself has zero `xbmc*` imports, so the chain stays clean); `stream.py`
imports `urllib.parse` (stdlib) and `lib.twitch.gql`.

- [ ] **Step 7: Commit**

```bash
git add lib/twitch/gql.py lib/twitch/stream.py tests/twitch/test_gql.py tests/twitch/test_stream.py
git commit -m "feat: implement stream playback URL resolution (gql + stream)"
```

---

### Task 3: `lib/windows/player.py` real implementation and `addon.xml` dependency

**Files:**
- Modify: `lib/windows/player.py`
- Modify: `addon.xml`
- Create: `tests/windows/test_player.py`
- Modify: `tests/test_addon_manifest.py`

**Interfaces:**
- Produces: `player.play_stream(url) -> bool` — `True` if playback started, `False` if
  `inputstream.adaptive` isn't available/the user declined its install.
- Consumed by: Task 4/5's `lib/windows/home.py`/`lib/windows/discover.py`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_addon_manifest.py — append
def test_addon_xml_requires_inputstreamhelper_module():
    tree = ET.parse(ADDON_XML)
    root = tree.getroot()
    requires = root.find("requires")
    assert requires is not None
    imports = requires.findall("import")
    addon_ids = [imp.attrib.get("addon") for imp in imports]
    assert "script.module.inputstreamhelper" in addon_ids
```

```python
# tests/windows/test_player.py
from unittest.mock import patch

from lib.windows import player


def test_play_stream_returns_true_and_plays_when_inputstream_available():
    with patch("lib.windows.player.Helper") as mock_helper_cls, patch(
        "lib.windows.player.xbmc.Player"
    ) as mock_player_cls:
        mock_helper_cls.return_value.check_inputstream.return_value = True
        mock_helper_cls.return_value.inputstream_addon = "inputstream.adaptive"

        result = player.play_stream("https://example.invalid/stream.m3u8")

    assert result is True
    mock_helper_cls.assert_called_once_with("hls")
    mock_player_cls.return_value.play.assert_called_once()
    call_args = mock_player_cls.return_value.play.call_args
    assert call_args[0][0] == "https://example.invalid/stream.m3u8"
    list_item = call_args[0][1]
    assert list_item.getProperty("inputstream") == "inputstream.adaptive"
    assert list_item.getProperty("inputstream.adaptive.manifest_type") == "hls"
    assert list_item.getMimeType() == "application/x-mpegURL"
    assert list_item.getContentLookup() is False
    assert list_item.getPath() == "https://example.invalid/stream.m3u8"


def test_play_stream_returns_false_when_inputstream_declined():
    with patch("lib.windows.player.Helper") as mock_helper_cls, patch(
        "lib.windows.player.xbmc.Player"
    ) as mock_player_cls:
        mock_helper_cls.return_value.check_inputstream.return_value = False

        result = player.play_stream("https://example.invalid/stream.m3u8")

    assert result is False
    mock_player_cls.return_value.play.assert_not_called()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_addon_manifest.py tests/windows/test_player.py -v`
Expected: FAIL — `addon.xml` doesn't declare the dependency yet; `player.play_stream` raises
`NotImplementedError`.

- [ ] **Step 3: Update `addon.xml`**

Add a new `<import>` inside the existing `<requires>` block, alongside the current two:

```xml
    <import addon="script.module.inputstreamhelper" version="0.4.6"/>
```

- [ ] **Step 4: Write `lib/windows/player.py`** (full replacement)

```python
"""Launches Kodi's native player for a resolved Twitch stream URL."""
import xbmc
import xbmcgui
from inputstreamhelper import Helper


def play_stream(url):
    """Hand the resolved HLS URL to Kodi's player via inputstream.adaptive,
    which handles proper adaptive-bitrate switching for live multi-quality
    HLS (unlike Kodi's native demuxer playing the URL directly). Returns
    True if playback was started, False if inputstream.adaptive isn't
    available and the user declined installing it (Helper.check_inputstream
    handles that install-prompt UI itself)."""
    is_helper = Helper("hls")
    if not is_helper.check_inputstream():
        return False

    list_item = xbmcgui.ListItem(path=url)
    list_item.setProperty("inputstream", is_helper.inputstream_addon)
    list_item.setProperty("inputstream.adaptive.manifest_type", "hls")
    list_item.setMimeType("application/x-mpegURL")
    list_item.setContentLookup(False)
    xbmc.Player().play(url, list_item)
    return True
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_addon_manifest.py tests/windows/test_player.py -v`
Expected: PASS (3 new manifest tests total from prior plans plus this 1; 2 tests in
`test_player.py`).

- [ ] **Step 6: Run the full suite**

Run: `.venv/bin/pytest -v`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add addon.xml lib/windows/player.py tests/windows/test_player.py tests/test_addon_manifest.py
git commit -m "feat: implement stream playback via inputstream.adaptive"
```

---

### Task 4: Click-to-play on Home's channel list

**Files:**
- Modify: `lib/windows/home.py`
- Modify: `tests/windows/test_home_window.py`

**Interfaces:**
- Consumes: `stream.resolve_stream_url`, `stream.StreamUnavailableError`, `api.TokenExpiredError`
  (Task 2); `player.play_stream` (Task 3).
- Produces: `HomeWindow._on_channel_selected()`, `HomeWindow._show_results_error(message)`;
  `HomeWindow._handle_expired_token` gains `on_success=None, on_error=None` parameters (mirroring
  `DiscoverWindow`'s existing signature exactly); `_build_list_item`'s items gain
  `broadcaster_login`/`is_live` properties; the internal `stream` variable name used throughout
  `_merge_channels`/`_build_list_item`/`_populate` is renamed to `stream_data` to avoid shadowing
  the new `from lib.twitch import stream` module import.

- [ ] **Step 1: Read the current `lib/windows/home.py` in full**

This task modifies most of the file's functions. Read it fresh before editing rather than assuming
the exact current line numbers — several prior plans have touched this file.

- [ ] **Step 2: Write the failing tests**

```python
# Append to tests/windows/test_home_window.py
# (this file already imports `api`, `gql`, `HomeWindow`, `_build_list_item`, `_merge_channels`,
# `LoginWindow`, `DiscoverWindow`, `xbmcgui`, `xbmcaddon`, `save_token` - reuse them)

from lib.twitch import stream


def test_build_list_item_live_sets_broadcaster_login_and_is_live_true():
    channel = FOLLOWED[1]  # Bob, broadcaster_login "bob"
    stream_data = LIVE[0]
    item = _build_list_item(channel, stream_data)
    assert item.getProperty("broadcaster_login") == "bob"
    assert item.getProperty("is_live") == "true"


def test_build_list_item_offline_sets_is_live_false():
    channel = FOLLOWED[0]  # Alice
    item = _build_list_item(channel, None)
    assert item.getProperty("broadcaster_login") == "alice"
    assert item.getProperty("is_live") == "false"


def test_selecting_a_live_channel_plays_it():
    addon = _addon_with_token({"access_token": "tok", "refresh_token": "ref", "user_id": "u1"})
    with patch("xbmcaddon.Addon", return_value=addon), patch.object(
        api, "get_followed_channels", return_value=FOLLOWED
    ), patch.object(api, "get_live_status", return_value=LIVE), patch.object(
        gql, "get_followed_live_games", return_value=[]
    ), patch(
        "lib.windows.home.stream.resolve_stream_url",
        return_value="https://example.invalid/stream.m3u8",
    ) as mock_resolve, patch(
        "lib.windows.home.player.play_stream", return_value=True
    ) as mock_play:
        win = HomeWindow("script-twitch-center-home.xml", "/tmp")
        win.onInit()
        channel_control = win.getControl(HomeWindow.CHANNEL_LIST_ID)
        # LIVE-first order per _merge_channels: Carol (200 viewers) then Bob (50), then offline Alice.
        channel_control.selectItem(0)  # Carol, live
        win.setFocusId(HomeWindow.CHANNEL_LIST_ID)
        win.onAction(xbmcgui.Action(xbmcgui.ACTION_SELECT_ITEM))

    mock_resolve.assert_called_once_with("tok", "carol")
    mock_play.assert_called_once_with("https://example.invalid/stream.m3u8")


def test_selecting_an_offline_channel_does_nothing():
    addon = _addon_with_token({"access_token": "tok", "refresh_token": "ref", "user_id": "u1"})
    with patch("xbmcaddon.Addon", return_value=addon), patch.object(
        api, "get_followed_channels", return_value=FOLLOWED
    ), patch.object(api, "get_live_status", return_value=LIVE), patch.object(
        gql, "get_followed_live_games", return_value=[]
    ):
        win = HomeWindow("script-twitch-center-home.xml", "/tmp")
        win.onInit()
        channel_control = win.getControl(HomeWindow.CHANNEL_LIST_ID)
        channel_control.selectItem(2)  # Carol, Bob, then offline Alice at index 2
        win.setFocusId(HomeWindow.CHANNEL_LIST_ID)
        with patch("lib.windows.home.stream.resolve_stream_url") as mock_resolve:
            win.onAction(xbmcgui.Action(xbmcgui.ACTION_SELECT_ITEM))

    mock_resolve.assert_not_called()


def test_selecting_a_live_channel_shows_error_when_resolution_fails():
    addon = _addon_with_token({"access_token": "tok", "refresh_token": "ref", "user_id": "u1"})
    with patch("xbmcaddon.Addon", return_value=addon), patch.object(
        api, "get_followed_channels", return_value=FOLLOWED
    ), patch.object(api, "get_live_status", return_value=LIVE), patch.object(
        gql, "get_followed_live_games", return_value=[]
    ), patch(
        "lib.windows.home.stream.resolve_stream_url",
        side_effect=stream.StreamUnavailableError("carol"),
    ):
        win = HomeWindow("script-twitch-center-home.xml", "/tmp")
        win.onInit()
        channel_control = win.getControl(HomeWindow.CHANNEL_LIST_ID)
        channel_control.selectItem(0)
        win.setFocusId(HomeWindow.CHANNEL_LIST_ID)
        win.onAction(xbmcgui.Action(xbmcgui.ACTION_SELECT_ITEM))

    assert win.getControl(HomeWindow.ERROR_LABEL_ID).getLabel() != ""
    assert win.getControl(HomeWindow.CHANNEL_LIST_ID).size() == 3


def test_selecting_a_live_channel_shows_error_when_playback_declined():
    addon = _addon_with_token({"access_token": "tok", "refresh_token": "ref", "user_id": "u1"})
    with patch("xbmcaddon.Addon", return_value=addon), patch.object(
        api, "get_followed_channels", return_value=FOLLOWED
    ), patch.object(api, "get_live_status", return_value=LIVE), patch.object(
        gql, "get_followed_live_games", return_value=[]
    ), patch(
        "lib.windows.home.stream.resolve_stream_url",
        return_value="https://example.invalid/stream.m3u8",
    ), patch("lib.windows.home.player.play_stream", return_value=False):
        win = HomeWindow("script-twitch-center-home.xml", "/tmp")
        win.onInit()
        channel_control = win.getControl(HomeWindow.CHANNEL_LIST_ID)
        channel_control.selectItem(0)
        win.setFocusId(HomeWindow.CHANNEL_LIST_ID)
        win.onAction(xbmcgui.Action(xbmcgui.ACTION_SELECT_ITEM))

    assert win.getControl(HomeWindow.ERROR_LABEL_ID).getLabel() != ""


def test_expired_token_during_channel_select_retries_playback_after_refresh():
    old_token = {
        "access_token": "old",
        "refresh_token": "ref",
        "user_id": "u1",
        "login": "x",
        "display_name": "X",
    }
    new_token = {"access_token": "new", "refresh_token": "ref2"}
    addon = _addon_with_token(old_token)

    resolve_calls = []

    def fake_resolve(access_token, broadcaster_login):
        resolve_calls.append((access_token, broadcaster_login))
        if access_token == "old":
            raise api.TokenExpiredError()
        return "https://example.invalid/stream.m3u8"

    with patch("xbmcaddon.Addon", return_value=addon), patch.object(
        api, "get_followed_channels", return_value=FOLLOWED
    ), patch.object(api, "get_live_status", return_value=LIVE), patch.object(
        gql, "get_followed_live_games", return_value=[]
    ), patch(
        "lib.windows.home.stream.resolve_stream_url", side_effect=fake_resolve
    ), patch(
        "lib.windows.home.player.play_stream", return_value=True
    ) as mock_play, patch(
        "lib.windows.home.auth.refresh_access_token", return_value=new_token
    ):
        win = HomeWindow("script-twitch-center-home.xml", "/tmp")
        win.onInit()
        channel_control = win.getControl(HomeWindow.CHANNEL_LIST_ID)
        channel_control.selectItem(0)
        win.setFocusId(HomeWindow.CHANNEL_LIST_ID)
        win.onAction(xbmcgui.Action(xbmcgui.ACTION_SELECT_ITEM))

    assert resolve_calls == [("old", "carol"), ("new", "carol")]
    mock_play.assert_called_once_with("https://example.invalid/stream.m3u8")
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/windows/test_home_window.py -v`
Expected: FAIL — `_build_list_item` doesn't set `broadcaster_login`/`is_live`; `onAction` doesn't
route `CHANNEL_LIST_ID`; `_handle_expired_token` doesn't accept `on_success`/`on_error`.

- [ ] **Step 4: Modify `lib/windows/home.py`**

Add imports (alongside the existing `from lib.twitch import api, auth, gql`):

```python
from lib.twitch import api, auth, gql, stream
from lib.windows import player
```

Add a new message constant near the existing ones:

```python
_PLAYBACK_ERROR_MESSAGE = "Couldn't start playback. Try again."
```

Rename every use of the local variable/parameter named `stream` (which now collides with the new
`from lib.twitch import stream` module-level import) to `stream_data`, in these three functions —
no behavior change, purely a rename for clarity:

```python
def _merge_channels(followed, live_list):
    """Split followed channels into (live, offline). live is a list of
    (channel, stream_data) tuples sorted by viewer_count descending; offline
    is a list of channel dicts sorted alphabetically by broadcaster_name."""
    live_by_id = {stream_data["user_id"]: stream_data for stream_data in live_list}
    live = []
    offline = []
    for channel in followed:
        stream_data = live_by_id.get(channel["broadcaster_id"])
        if stream_data:
            live.append((channel, stream_data))
        else:
            offline.append(channel)
    live.sort(key=lambda pair: pair[1]["viewer_count"], reverse=True)
    offline.sort(key=lambda c: c["broadcaster_name"].lower())
    return live, offline


def _build_list_item(channel, stream_data=None):
    item = xbmcgui.ListItem(channel["broadcaster_name"])
    if stream_data:
        item.setLabel2(
            stream_data["game_name"] + " - " + str(stream_data["viewer_count"]) + " viewers"
        )
        item.setArt({"thumb": _thumbnail_url(stream_data["thumbnail_url"])})
        item.setProperty("is_live", "true")
    else:
        item.setLabel2("Offline")
        item.setProperty("is_live", "false")
    item.setProperty("broadcaster_id", channel["broadcaster_id"])
    item.setProperty("broadcaster_login", channel["broadcaster_login"])
    return item
```

And in `_populate`, the list-comprehension loop variable:

```python
        items = [_build_list_item(channel, stream_data) for channel, stream_data in live]
```

(the rest of `_populate` — the `game_filter` comparison `stream["game_name"] == game_filter` —
also needs its loop variable renamed since it iterates the same `live` list: change
`live = [(channel, stream) for channel, stream in live if stream["game_name"] == game_filter]` to
`live = [(channel, stream_data) for channel, stream_data in live if stream_data["game_name"] ==
game_filter]`)

Update `_handle_expired_token` to accept and use `on_success`/`on_error`, mirroring
`DiscoverWindow`'s existing implementation exactly:

```python
    def _handle_expired_token(self, addon, client_id, token, on_success=None, on_error=None):
        """Refresh the access token, then redo whatever the user was doing.

        on_success is a callable taking (addon, client_id, refreshed_token); it
        defaults to reloading the whole Home screen (onInit's behaviour).
        Callers that were mid-action (e.g. playback) pass a closure that
        retries THAT action, so an expiry doesn't silently discard the
        user's click."""
        new_token = auth.refresh_access_token(client_id, token["refresh_token"])
        if new_token is None:
            auth.clear_token(addon)
            self._show_error(_RELOGIN_MESSAGE)
            return

        new_token["user_id"] = token.get("user_id")
        new_token["login"] = token.get("login")
        new_token["display_name"] = token.get("display_name")

        # Twitch's device-code refresh tokens are single-use for public
        # clients: the moment refresh_access_token succeeded above, the OLD
        # refresh_token was invalidated. Persist the new token now, before
        # the retry below - if the retry hits a transient (non-401) error,
        # we still want the new refresh_token on disk rather than the
        # now-dead old one, or the next launch's refresh would fail outright.
        auth.save_token(new_token, addon)

        if on_success is None:
            on_success = self._load_and_populate
        if on_error is None:
            on_error = self._show_error

        try:
            on_success(addon, client_id, new_token)
        except api.TokenExpiredError:
            auth.clear_token(addon)
            self._show_error(_RELOGIN_MESSAGE)
        except Exception as exc:
            xbmc.log(
                "script.twitch.center: Home screen failed after token refresh: " + repr(exc),
                xbmc.LOGERROR,
            )
            on_error(_NETWORK_ERROR_MESSAGE)
```

Note: this changes `_load_and_populate`'s call signature usage here only — `_load_and_populate`
itself already has the signature `(self, addon, client_id, token)`, so passing it directly as
`on_success` works unchanged; no changes needed to `_load_and_populate` itself.

Add `_show_results_error` (place it right after `_show_error`):

```python
    def _show_results_error(self, message):
        """Transient failure (e.g. one playback attempt): keep the channel
        list and games row intact so a single failure doesn't force an
        addon restart - mirrors DiscoverWindow's _show_results_error."""
        self.getControl(self.ERROR_LABEL_ID).setLabel(message)
```

Add `_on_channel_selected` and `_play_channel` (place them near `_on_game_selected`):

```python
    def _on_channel_selected(self):
        selected = self.getControl(self.CHANNEL_LIST_ID).getSelectedItem()
        if selected is None or selected.getProperty("is_live") != "true":
            return
        addon = xbmcaddon.Addon()
        client_id = addon.getSetting("client_id")
        token = auth.load_token(addon)
        if token is None:
            self._show_results_error(_MISSING_TOKEN_MESSAGE)
            return
        broadcaster_login = selected.getProperty("broadcaster_login")
        try:
            self._play_channel(token, broadcaster_login)
        except api.TokenExpiredError:
            self._handle_expired_token(
                addon,
                client_id,
                token,
                on_success=lambda a, c, t: self._play_channel(t, broadcaster_login),
                on_error=self._show_results_error,
            )
        except stream.StreamUnavailableError:
            self._show_results_error(_PLAYBACK_ERROR_MESSAGE)

    def _play_channel(self, token, broadcaster_login):
        url = stream.resolve_stream_url(token["access_token"], broadcaster_login)
        if not player.play_stream(url):
            self._show_results_error(_PLAYBACK_ERROR_MESSAGE)
```

Update `onAction` to add the new branch:

```python
    def onAction(self, action):
        if action.getId() in (xbmcgui.ACTION_PREVIOUS_MENU, xbmcgui.ACTION_NAV_BACK):
            self.close()
            self.closed_event.set()
        elif action.getId() == xbmcgui.ACTION_SELECT_ITEM:
            if self.getFocusId() == self.RELOGIN_BUTTON_ID:
                self._open_login_window()
            elif self.getFocusId() == self.GAMES_LIST_ID:
                self._on_game_selected()
            elif self.getFocusId() == self.DISCOVER_BUTTON_ID:
                self._open_discover_window()
            elif self.getFocusId() == self.CHANNEL_LIST_ID:
                self._on_channel_selected()
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/windows/test_home_window.py -v`
Expected: PASS (all pre-existing tests plus the 7 new ones above).

- [ ] **Step 6: Run the full suite**

Run: `.venv/bin/pytest -v`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add lib/windows/home.py tests/windows/test_home_window.py
git commit -m "feat: wire click-to-play into Home's channel list"
```

---

### Task 5: Click-to-play on Discover's results list

**Files:**
- Modify: `lib/windows/discover.py`
- Modify: `tests/windows/test_discover_window.py`

**Interfaces:**
- Consumes: `stream.resolve_stream_url`, `stream.StreamUnavailableError`, `api.TokenExpiredError`
  (Task 2); `player.play_stream` (Task 3); `DiscoverWindow._handle_expired_token`'s existing
  `on_success`/`on_error` parameters (already present, no change needed here — only `HomeWindow`
  needed that generalization).
- Produces: `DiscoverWindow._on_channel_selected()`, `_play_channel(token, broadcaster_login)`.
  `_build_stream_item`/`_build_channel_item`'s items gain `broadcaster_login`/`is_live` properties;
  the `stream` parameter name in `_build_stream_item` is renamed to `stream_data` to avoid shadowing
  the new `from lib.twitch import stream` module import.

- [ ] **Step 1: Read the current `lib/windows/discover.py` and `tests/windows/test_discover_window.py`
in full** before editing.

- [ ] **Step 2: Update the existing `STREAMS`/`SEARCH_RESULTS` test fixtures**

Neither fixture currently has the login field real Helix responses include (they were written
before anything needed it). Add it — this is a fixture fix, not a new test, and must land before
Step 3's new tests, which read `STREAMS[0]["user_login"]` and
`SEARCH_RESULTS[0]["broadcaster_login"]`:

```python
STREAMS = [
    {
        "user_id": "1",
        "user_login": "alice",
        "user_name": "Alice",
        "game_name": "Just Chatting",
        "viewer_count": 500,
        "thumbnail_url": "https://example.invalid/{width}x{height}.jpg",
    }
]

SEARCH_RESULTS = [
    {
        "id": "2",
        "broadcaster_login": "bob",
        "display_name": "Bob",
        "game_name": "League of Legends",
        "is_live": True,
        "thumbnail_url": "https://example.invalid/bob.jpg",
    },
    {
        "id": "3",
        "broadcaster_login": "carol",
        "display_name": "Carol",
        "game_name": "",
        "is_live": False,
        "thumbnail_url": "https://example.invalid/carol.jpg",
    },
]
```

Only add the two new keys (`user_login` to the `STREAMS` entry, `broadcaster_login` to each
`SEARCH_RESULTS` entry) — every other key/value in both fixtures stays exactly as currently
written; re-read the file first to confirm you're not dropping any existing field (e.g. `Carol`'s
entry may have more fields below `thumbnail_url` than shown here — preserve them).

- [ ] **Step 3: Write the failing tests**

```python
# Append to tests/windows/test_discover_window.py
# (this file already imports `api`, `DiscoverWindow`, `_build_channel_item`, `_build_stream_item`,
# `xbmcgui`, `xbmcaddon`, `save_token` - reuse them)

from lib.twitch import stream


def test_build_stream_item_sets_broadcaster_login_and_is_live_true():
    item = _build_stream_item(STREAMS[0])
    assert item.getProperty("broadcaster_login") == STREAMS[0]["user_login"]
    assert item.getProperty("is_live") == "true"


def test_build_channel_item_sets_broadcaster_login_and_is_live_from_data():
    live_item = _build_channel_item(SEARCH_RESULTS[0])
    assert live_item.getProperty("broadcaster_login") == SEARCH_RESULTS[0]["broadcaster_login"]
    assert live_item.getProperty("is_live") == "true"
    offline_item = _build_channel_item(SEARCH_RESULTS[1])
    assert offline_item.getProperty("is_live") == "false"


def test_selecting_a_live_result_plays_it():
    addon = _addon_with_token({"access_token": "tok", "refresh_token": "ref", "user_id": "u1"})
    with patch("xbmcaddon.Addon", return_value=addon), patch.object(
        api, "get_top_games", return_value=TOP_GAMES
    ), patch.object(api, "get_live_streams_by_game", return_value=STREAMS), patch(
        "lib.windows.discover.stream.resolve_stream_url",
        return_value="https://example.invalid/stream.m3u8",
    ) as mock_resolve, patch(
        "lib.windows.discover.player.play_stream", return_value=True
    ) as mock_play:
        win = DiscoverWindow("script-twitch-center-discover.xml", "/tmp")
        win.onInit()
        games_control = win.getControl(DiscoverWindow.GAMES_LIST_ID)
        games_control.selectItem(0)
        win.setFocusId(DiscoverWindow.GAMES_LIST_ID)
        win.onAction(xbmcgui.Action(xbmcgui.ACTION_SELECT_ITEM))
        results_control = win.getControl(DiscoverWindow.RESULTS_LIST_ID)
        results_control.selectItem(0)
        win.setFocusId(DiscoverWindow.RESULTS_LIST_ID)
        win.onAction(xbmcgui.Action(xbmcgui.ACTION_SELECT_ITEM))

    mock_resolve.assert_called_once_with("tok", STREAMS[0]["user_login"])
    mock_play.assert_called_once_with("https://example.invalid/stream.m3u8")


def test_selecting_an_offline_search_result_does_nothing():
    addon = _addon_with_token({"access_token": "tok", "refresh_token": "ref", "user_id": "u1"})
    with patch("xbmcaddon.Addon", return_value=addon), patch.object(
        api, "get_top_games", return_value=TOP_GAMES
    ), patch.object(api, "search_channels", return_value=SEARCH_RESULTS):
        win = DiscoverWindow("script-twitch-center-discover.xml", "/tmp")
        win.onInit()
        win.getControl(DiscoverWindow.SEARCH_EDIT_ID).setText("bob")
        win.setFocusId(DiscoverWindow.SEARCH_BUTTON_ID)
        win.onAction(xbmcgui.Action(xbmcgui.ACTION_SELECT_ITEM))
        results_control = win.getControl(DiscoverWindow.RESULTS_LIST_ID)
        results_control.selectItem(1)  # Carol, offline per SEARCH_RESULTS[1]
        win.setFocusId(DiscoverWindow.RESULTS_LIST_ID)
        with patch("lib.windows.discover.stream.resolve_stream_url") as mock_resolve:
            win.onAction(xbmcgui.Action(xbmcgui.ACTION_SELECT_ITEM))

    mock_resolve.assert_not_called()


def test_selecting_a_live_result_shows_results_error_when_resolution_fails():
    addon = _addon_with_token({"access_token": "tok", "refresh_token": "ref", "user_id": "u1"})
    with patch("xbmcaddon.Addon", return_value=addon), patch.object(
        api, "get_top_games", return_value=TOP_GAMES
    ), patch.object(api, "get_live_streams_by_game", return_value=STREAMS), patch(
        "lib.windows.discover.stream.resolve_stream_url",
        side_effect=stream.StreamUnavailableError("alice"),
    ):
        win = DiscoverWindow("script-twitch-center-discover.xml", "/tmp")
        win.onInit()
        games_control = win.getControl(DiscoverWindow.GAMES_LIST_ID)
        games_control.selectItem(0)
        win.setFocusId(DiscoverWindow.GAMES_LIST_ID)
        win.onAction(xbmcgui.Action(xbmcgui.ACTION_SELECT_ITEM))
        results_control = win.getControl(DiscoverWindow.RESULTS_LIST_ID)
        results_control.selectItem(0)
        win.setFocusId(DiscoverWindow.RESULTS_LIST_ID)
        win.onAction(xbmcgui.Action(xbmcgui.ACTION_SELECT_ITEM))

    assert win.getControl(DiscoverWindow.ERROR_LABEL_ID).getLabel() != ""
    # Games row must survive a transient playback failure, same as a transient
    # search/browse failure already does.
    assert games_control.size() == 2


def test_expired_token_during_channel_select_retries_playback_after_refresh():
    old_token = {
        "access_token": "old",
        "refresh_token": "ref",
        "user_id": "u1",
        "login": "x",
        "display_name": "X",
    }
    new_token = {"access_token": "new", "refresh_token": "ref2"}
    addon = _addon_with_token(old_token)

    resolve_calls = []

    def fake_resolve(access_token, broadcaster_login):
        resolve_calls.append((access_token, broadcaster_login))
        if access_token == "old":
            raise api.TokenExpiredError()
        return "https://example.invalid/stream.m3u8"

    with patch("xbmcaddon.Addon", return_value=addon), patch.object(
        api, "get_top_games", return_value=TOP_GAMES
    ), patch.object(api, "get_live_streams_by_game", return_value=STREAMS), patch(
        "lib.windows.discover.stream.resolve_stream_url", side_effect=fake_resolve
    ), patch(
        "lib.windows.discover.player.play_stream", return_value=True
    ) as mock_play, patch(
        "lib.windows.discover.auth.refresh_access_token", return_value=new_token
    ):
        win = DiscoverWindow("script-twitch-center-discover.xml", "/tmp")
        win.onInit()
        games_control = win.getControl(DiscoverWindow.GAMES_LIST_ID)
        games_control.selectItem(0)
        win.setFocusId(DiscoverWindow.GAMES_LIST_ID)
        win.onAction(xbmcgui.Action(xbmcgui.ACTION_SELECT_ITEM))
        results_control = win.getControl(DiscoverWindow.RESULTS_LIST_ID)
        results_control.selectItem(0)
        win.setFocusId(DiscoverWindow.RESULTS_LIST_ID)
        win.onAction(xbmcgui.Action(xbmcgui.ACTION_SELECT_ITEM))

    assert resolve_calls == [
        ("old", STREAMS[0]["user_login"]),
        ("new", STREAMS[0]["user_login"]),
    ]
    mock_play.assert_called_once_with("https://example.invalid/stream.m3u8")
```

- [ ] **Step 4: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/windows/test_discover_window.py -v`
Expected: FAIL — `_build_stream_item`/`_build_channel_item` don't set the new properties;
`onAction` doesn't route `RESULTS_LIST_ID`.

- [ ] **Step 5: Modify `lib/windows/discover.py`**

Add imports (alongside the existing `from lib.twitch import api, auth`):

```python
from lib.twitch import api, auth, stream
from lib.windows import player
```

Add a new message constant near the existing ones:

```python
_PLAYBACK_ERROR_MESSAGE = "Couldn't start playback. Try again."
```

Rename `_build_stream_item`'s parameter (the only place in this file using the name `stream` for
something other than the new module import) and add the new properties to both builders:

```python
def _build_stream_item(stream_data):
    item = xbmcgui.ListItem(stream_data["user_name"])
    item.setLabel2(
        stream_data["game_name"] + " - " + str(stream_data["viewer_count"]) + " viewers"
    )
    item.setArt({"thumb": _thumbnail_url(stream_data["thumbnail_url"])})
    item.setProperty("broadcaster_id", stream_data["user_id"])
    item.setProperty("broadcaster_login", stream_data["user_login"])
    item.setProperty("is_live", "true")
    return item


def _build_channel_item(channel):
    item = xbmcgui.ListItem(channel["display_name"])
    if channel.get("is_live"):
        item.setLabel2("Live - " + channel.get("game_name", ""))
    else:
        item.setLabel2("Offline")
    item.setArt({"thumb": channel.get("thumbnail_url", "")})
    item.setProperty("broadcaster_id", channel.get("id", ""))
    item.setProperty("broadcaster_login", channel.get("broadcaster_login", ""))
    item.setProperty("is_live", "true" if channel.get("is_live") else "false")
    return item
```

The call site in `_load_streams_for_game` (`[_build_stream_item(stream) for stream in streams]`)
must also have its loop variable renamed to avoid the same shadowing:

```python
    def _load_streams_for_game(self, addon, client_id, token, game_id):
        streams = api.get_live_streams_by_game(token["access_token"], client_id, game_id)
        self._populate_results([_build_stream_item(stream_data) for stream_data in streams])
```

Add `_on_channel_selected` and `_play_channel` (place them near `_on_game_selected`):

```python
    def _on_channel_selected(self):
        selected = self.getControl(self.RESULTS_LIST_ID).getSelectedItem()
        if selected is None or selected.getProperty("is_live") != "true":
            return
        addon = xbmcaddon.Addon()
        client_id = addon.getSetting("client_id")
        token = auth.load_token(addon)
        if token is None:
            self._show_results_error(_MISSING_TOKEN_MESSAGE)
            return
        broadcaster_login = selected.getProperty("broadcaster_login")
        try:
            self._play_channel(token, broadcaster_login)
        except api.TokenExpiredError:
            self._handle_expired_token(
                addon,
                client_id,
                token,
                on_success=lambda a, c, t: self._play_channel(t, broadcaster_login),
                on_error=self._show_results_error,
            )
        except stream.StreamUnavailableError:
            self._show_results_error(_PLAYBACK_ERROR_MESSAGE)

    def _play_channel(self, token, broadcaster_login):
        url = stream.resolve_stream_url(token["access_token"], broadcaster_login)
        if not player.play_stream(url):
            self._show_results_error(_PLAYBACK_ERROR_MESSAGE)
```

Update `onAction` to add the new branch:

```python
    def onAction(self, action):
        if action.getId() in (xbmcgui.ACTION_PREVIOUS_MENU, xbmcgui.ACTION_NAV_BACK):
            self.close()
            self.closed_event.set()
        elif action.getId() == xbmcgui.ACTION_SELECT_ITEM:
            focus = self.getFocusId()
            if focus == self.RELOGIN_BUTTON_ID:
                self._open_login_window()
            elif focus == self.GAMES_LIST_ID:
                self._on_game_selected()
            elif focus == self.SEARCH_BUTTON_ID:
                self._on_search()
            elif focus == self.RESULTS_LIST_ID:
                self._on_channel_selected()
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/windows/test_discover_window.py -v`
Expected: PASS (all pre-existing tests plus the 6 new ones above; the fixture change in Step 2
doesn't itself add tests, it only unblocks the new ones).

- [ ] **Step 7: Run the full suite**

Run: `.venv/bin/pytest -v`
Expected: PASS, full suite green (all 5 tasks combined).

- [ ] **Step 8: Commit**

```bash
git add lib/windows/discover.py tests/windows/test_discover_window.py
git commit -m "feat: wire click-to-play into Discover's results list"
```

---

## Post-plan state

After Task 5, clicking a live channel in either Home or Discover resolves a real Twitch playback
URL and starts it in Kodi via `inputstream.adaptive`, with token-expiry-during-click correctly
triggering a refresh-then-retry rather than silently failing. Manually verify in real Kodi before
considering this done — specifically: does `inputstream.adaptive`'s install prompt actually appear
and work when not yet installed (this system has `script.module.inputstreamhelper` but not
`inputstream.adaptive` itself, so this is a real, not hypothetical, path to exercise); does the
resolved usher URL actually play smoothly with adaptive quality switching; does the whole
`closed_event`/window-lifetime chain (from the Discover screen's own final review) stay correct
when playback starts from Home vs. from Discover. The automated suite covers logic correctness but
not real Kodi playback behavior or the real `inputstream.adaptive` install flow.

Out of scope, still deferred: manual quality-selection UI, chat-during-playback, VOD/clip playback.
