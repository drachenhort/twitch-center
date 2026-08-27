# VODs & Clips for Followed Channels Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a "VODs & Clips" screen (Twitch only), reachable from the main menu: pick a followed channel, see that channel's VODs and Clips as two lists newest-first, play either one video-only.

**Architecture:** Two new screens following this codebase's existing one-`<group>`-per-screen pattern (a channel picker, then a per-channel VODs+Clips view), backed by two new Helix API calls and two new playback-resolution paths (VOD via the existing GQL playback-token mechanism with different variables; Clips via a pure URL-string transform, no GQL needed).

**Tech Stack:** Python 3, Kodi WindowXML skins, `requests`, Twitch Helix API + Twitch's unofficial GraphQL API (already used by `lib/twitch/gql.py`).

**Spec:** `docs/superpowers/specs/2026-08-27-vods-clips-design.md`

## Global Constraints

- Twitch only. Kick is explicitly deferred (see `TODO.md`, "Kick version of VODs & Clips") — do not build any Kick-side code in this plan.
- No VOD replay chat, no Clip chat. All VOD/Clip playback is video-only (`platform="twitch_vod"` / `platform="twitch_clip"` passed to `player.play_stream`, which already skips chat and the ad-skip relay for any `platform != "twitch"`).
- No pagination beyond the first page (20 items) of each list.
- The channel picker lists **all** followed channels regardless of current live status.
- Videos list sorted newest-first via explicit `sort=time` (Helix's default, made explicit). Clips list re-sorted **client-side** by `created_at` descending — Twitch's Clips endpoint does not guarantee chronological order.
- `lib/twitch/*` and `lib/kick/*` must never import xbmc-family modules (enforced by `tests/test_architecture.py`).

---

### Task 1: Helix API — `get_videos` and `get_clips`

**Files:**
- Modify: `lib/twitch/api.py` (add after `get_live_status`, currently ending around line 66)
- Test: `tests/twitch/test_api.py`

**Interfaces:**
- Produces: `get_videos(access_token, client_id, user_id, first=20)` → list of Helix video dicts (raw `/videos` response `data` entries: `id`, `title`, `created_at`, `duration`, `thumbnail_url`, `view_count`, ...). Raises `api.TokenExpiredError` on 401, same as every other function in this module.
- Produces: `get_clips(access_token, client_id, broadcaster_id, first=20)` → list of Helix clip dicts (raw `/clips` response `data` entries: `id`, `title`, `created_at`, `duration`, `thumbnail_url`, `view_count`, ...), **sorted by `created_at` descending** before returning (Twitch does not guarantee order). Raises `api.TokenExpiredError` on 401.

- [ ] **Step 1: Write the failing tests**

Add to `tests/twitch/test_api.py`:

```python
def test_get_videos_returns_data():
    body = {
        "data": [
            {"id": "1", "title": "Stream 1", "created_at": "2026-08-20T00:00:00Z",
             "duration": "3h8m33s", "thumbnail_url": "https://example.invalid/1-%{width}x%{height}.jpg",
             "view_count": 100},
        ],
        "pagination": {},
    }
    with patch.object(api.requests, "get", return_value=_response(body)) as mock_get:
        result = api.get_videos("token", "client-id", "user-id")
    assert result == body["data"]
    params = mock_get.call_args.kwargs["params"]
    assert params["user_id"] == "user-id"
    assert params["type"] == "archive"
    assert params["sort"] == "time"
    assert params["first"] == 20


def test_get_videos_raises_token_expired_on_401():
    with patch.object(api.requests, "get", return_value=_response({}, status_code=401)):
        with pytest.raises(api.TokenExpiredError):
            api.get_videos("token", "client-id", "user-id")


def test_get_clips_returns_data_sorted_newest_first():
    # Deliberately out-of-order response (Twitch's Clips endpoint doesn't
    # guarantee chronological order) - get_clips must re-sort by created_at.
    body = {
        "data": [
            {"id": "old", "created_at": "2026-08-01T00:00:00Z"},
            {"id": "newest", "created_at": "2026-08-25T00:00:00Z"},
            {"id": "middle", "created_at": "2026-08-15T00:00:00Z"},
        ],
    }
    with patch.object(api.requests, "get", return_value=_response(body)) as mock_get:
        result = api.get_clips("token", "client-id", "broadcaster-id")
    assert [c["id"] for c in result] == ["newest", "middle", "old"]
    params = mock_get.call_args.kwargs["params"]
    assert params["broadcaster_id"] == "broadcaster-id"
    assert params["first"] == 20


def test_get_clips_raises_token_expired_on_401():
    with patch.object(api.requests, "get", return_value=_response({}, status_code=401)):
        with pytest.raises(api.TokenExpiredError):
            api.get_clips("token", "client-id", "broadcaster-id")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/twitch/test_api.py -k "get_videos or get_clips" -v`
Expected: FAIL with `AttributeError: module 'lib.twitch.api' has no attribute 'get_videos'`

- [ ] **Step 3: Write minimal implementation**

Add to `lib/twitch/api.py`, directly after `get_live_status`:

```python
def get_videos(access_token, client_id, user_id, first=20):
    """Return the given broadcaster's VODs (Helix /videos, type=archive), newest first.
    sort=time is Helix's own default - passed explicitly so this doesn't silently change
    if Twitch ever changes that default."""
    body = _get(
        HELIX_BASE + "/videos",
        access_token, client_id,
        params={"user_id": user_id, "type": "archive", "sort": "time", "first": first},
    )
    return body["data"]


def get_clips(access_token, client_id, broadcaster_id, first=20):
    """Return the given broadcaster's Clips (Helix /clips), sorted newest first.
    Twitch's Clips endpoint does NOT guarantee chronological order in its response (it's
    view-count-biased) - re-sort client-side by created_at before returning."""
    body = _get(
        HELIX_BASE + "/clips",
        access_token, client_id,
        params={"broadcaster_id": broadcaster_id, "first": first},
    )
    return sorted(body["data"], key=lambda clip: clip["created_at"], reverse=True)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/twitch/test_api.py -v`
Expected: PASS (all existing tests plus the 4 new ones)

- [ ] **Step 5: Commit**

```bash
git add lib/twitch/api.py tests/twitch/test_api.py
git commit -m "Add get_videos and get_clips Helix API calls"
```

---

### Task 2: Playback resolution — VOD (GQL) and Clip (URL transform)

**Files:**
- Modify: `lib/twitch/gql.py` (add after `get_playback_access_token`)
- Modify: `lib/twitch/stream.py` (add after `resolve_stream_url`)
- Test: `tests/twitch/test_gql.py`, `tests/twitch/test_stream.py`

**Interfaces:**
- Consumes: nothing new from other tasks.
- Produces: `gql.get_vod_playback_access_token(vod_id, website_token=None)` → `{"value", "signature"}` dict or `None` (same contract as `get_playback_access_token`).
- Produces: `stream.resolve_vod_url(vod_id, website_token=None)` → HLS URL string. Raises `stream.StreamUnavailableError` if the token can't be resolved.
- Produces: `stream.resolve_clip_url(thumbnail_url)` → direct `.mp4` URL string. Raises `stream.StreamUnavailableError` if `thumbnail_url` doesn't match the expected `...-preview-<W>x<H>.jpg` pattern.

- [ ] **Step 1: Write the failing tests**

Add to `tests/twitch/test_gql.py`:

```python
def test_get_vod_playback_access_token_returns_value_and_signature():
    body = {"data": {"videoPlaybackAccessToken": {"value": "vod-token-json", "signature": "sig123"}}}
    with patch.object(gql.requests, "post", return_value=_response(body)) as mock_post:
        token = gql.get_vod_playback_access_token("123456789")
    assert token == {"value": "vod-token-json", "signature": "sig123"}
    variables = mock_post.call_args.kwargs["json"]["variables"]
    assert variables["isLive"] is False
    assert variables["isVod"] is True
    assert variables["vodID"] == "123456789"
    assert variables["login"] == ""


def test_get_vod_playback_access_token_returns_none_on_missing_field():
    body = {"data": {}}
    with patch.object(gql.requests, "post", return_value=_response(body)):
        assert gql.get_vod_playback_access_token("123456789") is None


def test_get_vod_playback_access_token_returns_none_on_non_200():
    with patch.object(gql.requests, "post", return_value=_response({}, status_code=500)):
        assert gql.get_vod_playback_access_token("123456789") is None


def test_get_vod_playback_access_token_returns_none_on_request_exception():
    with patch.object(gql.requests, "post", side_effect=requests.RequestException("boom")):
        assert gql.get_vod_playback_access_token("123456789") is None


def test_get_vod_playback_access_token_passes_website_token_through():
    body = {"data": {"videoPlaybackAccessToken": {"value": "v", "signature": "s"}}}
    with patch.object(gql.requests, "post", return_value=_response(body)) as mock_post:
        gql.get_vod_playback_access_token("123456789", "my-website-token")
    headers = mock_post.call_args.kwargs["headers"]
    assert headers["Authorization"] == "OAuth my-website-token"
```

`tests/twitch/test_gql.py` already imports `requests` at module scope for other tests — if it doesn't yet, add `import requests` to its imports.

Add to `tests/twitch/test_stream.py`:

```python
def test_resolve_vod_url_builds_usher_vod_url_on_success():
    token = {"value": "vod-token-json", "signature": "abc123"}
    with patch.object(gql, "get_vod_playback_access_token", return_value=token) as mock_get_token:
        url = stream.resolve_vod_url("123456789")
    mock_get_token.assert_called_once_with("123456789", None)
    assert url.startswith("https://usher.ttvnw.net/vod/123456789.m3u8?token=vod-token-json&sig=abc123")


def test_resolve_vod_url_raises_stream_unavailable_when_token_is_none():
    with patch.object(gql, "get_vod_playback_access_token", return_value=None):
        with pytest.raises(stream.StreamUnavailableError):
            stream.resolve_vod_url("123456789")


def test_resolve_vod_url_passes_website_token_through():
    token = {"value": "v", "signature": "s"}
    with patch.object(gql, "get_vod_playback_access_token", return_value=token) as mock_get_token:
        stream.resolve_vod_url("123456789", "my-website-token")
    mock_get_token.assert_called_once_with("123456789", "my-website-token")


def test_resolve_clip_url_replaces_preview_suffix_with_mp4():
    thumb = "https://clips-media-assets2.twitch.tv/AB12CD34-preview-480x272.jpg"
    url = stream.resolve_clip_url(thumb)
    assert url == "https://clips-media-assets2.twitch.tv/AB12CD34.mp4"


def test_resolve_clip_url_raises_on_unexpected_format():
    with pytest.raises(stream.StreamUnavailableError):
        stream.resolve_clip_url("https://example.invalid/not-a-preview-url.jpg")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/twitch/test_gql.py tests/twitch/test_stream.py -k "vod or clip" -v`
Expected: FAIL with `AttributeError` for each new function

- [ ] **Step 3: Write minimal implementation**

Add to `lib/twitch/gql.py`, directly after `get_playback_access_token`:

```python
def get_vod_playback_access_token(vod_id, website_token=None):
    """Return a {"value", "signature"} playback access token for the given VOD id, or None
    on any failure - never raises. Same persisted query as get_playback_access_token, with
    isLive/isVod/vodID/login swapped for the VOD case instead of the live case.

    Known limitation: the query variables here (isVod/vodID) are well-documented in
    Twitch's public web client and high-confidence, but this persisted query's response
    shape was captured for the LIVE case (get_playback_access_token) - whether Twitch's
    fixed response selection set for this exact persisted hash includes
    videoPlaybackAccessToken for a VOD request is unconfirmed until live-tested. If it
    doesn't, this returns None the same as any other failure - no crash, VOD playback
    just won't work until this is revisited."""
    try:
        response = requests.post(
            GQL_URL,
            json={
                "operationName": "PlaybackAccessToken",
                "variables": {
                    "isLive": False,
                    "login": "",
                    "isVod": True,
                    "vodID": vod_id,
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
            headers=_headers(website_token),
            timeout=10,
        )
    except requests.RequestException:
        return None

    if response.status_code != 200:
        return None

    try:
        body = response.json()
        token = body["data"]["videoPlaybackAccessToken"]
        value = token["value"]
        signature = token["signature"]
    except (ValueError, KeyError, TypeError):
        return None

    if not value or not signature:
        return None

    return {"value": value, "signature": signature}
```

Add to `lib/twitch/stream.py`, directly after `resolve_stream_url`:

```python
import re

_CLIP_PREVIEW_SUFFIX_RE = re.compile(r"-preview-\d+x\d+\.jpg$")


def resolve_vod_url(vod_id, website_token=None):
    """Return a direct HLS (.m3u8) URL for the given VOD id. Raises
    StreamUnavailableError if it can't be resolved."""
    token = gql.get_vod_playback_access_token(vod_id, website_token)
    if token is None:
        raise StreamUnavailableError(vod_id)
    return (
        USHER_BASE
        + "/vod/"
        + vod_id
        + ".m3u8"
        + "?token="
        + quote(token["value"], safe="")
        + "&sig="
        + token["signature"]
    )


def resolve_clip_url(thumbnail_url):
    """Derive a clip's direct MP4 URL from its Helix thumbnail_url (e.g.
    ".../AB12CD34-preview-480x272.jpg" -> ".../AB12CD34.mp4"). Raises
    StreamUnavailableError if thumbnail_url doesn't match that pattern - a well-known,
    deterministic technique (no GQL/auth needed), but dependent on Twitch's thumbnail
    naming convention not changing."""
    if not _CLIP_PREVIEW_SUFFIX_RE.search(thumbnail_url):
        raise StreamUnavailableError(thumbnail_url)
    return _CLIP_PREVIEW_SUFFIX_RE.sub(".mp4", thumbnail_url)
```

`import re` belongs at the top of `lib/twitch/stream.py` with the other imports (not inline) — place it alongside the existing `import random` line, not where shown above.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/twitch/test_gql.py tests/twitch/test_stream.py -v`
Expected: PASS

- [ ] **Step 5: Run the architecture boundary test**

Run: `pytest tests/test_architecture.py -v`
Expected: PASS (`lib/twitch/gql.py` and `lib/twitch/stream.py` still have no xbmc imports)

- [ ] **Step 6: Commit**

```bash
git add lib/twitch/gql.py lib/twitch/stream.py tests/twitch/test_gql.py tests/twitch/test_stream.py
git commit -m "Add VOD and Clip playback resolution"
```

---

### Task 3: `lib/providers.py` dispatch wrappers

**Files:**
- Modify: `lib/providers.py` (add after `resolve_stream_url`)
- Test: `tests/test_providers.py`

**Interfaces:**
- Consumes: `twitch_stream.resolve_vod_url(vod_id, website_token)` and `twitch_stream.resolve_clip_url(thumbnail_url)` (Task 2), `twitch_stream.StreamUnavailableError` (Task 2).
- Produces: `providers.resolve_vod_url(addon, vod_id)` → URL string, raises `providers.StreamUnavailableError`. `providers.resolve_clip_url(addon, thumbnail_url)` → URL string, raises `providers.StreamUnavailableError`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_providers.py`:

```python
def test_resolve_vod_url_dispatches_to_twitch():
    addon = xbmcaddon.Addon()
    addon.setSetting("website_token", "webtok")
    with patch.object(twitch_stream, "resolve_vod_url", return_value="https://twitch.example/vod.m3u8") as mock:
        url = providers.resolve_vod_url(addon, "123456789")
    mock.assert_called_once_with("123456789", "webtok")
    assert url == "https://twitch.example/vod.m3u8"


def test_resolve_vod_url_wraps_unavailable_error():
    addon = xbmcaddon.Addon()
    with patch.object(twitch_stream, "resolve_vod_url", side_effect=twitch_stream.StreamUnavailableError("x")):
        with pytest.raises(providers.StreamUnavailableError):
            providers.resolve_vod_url(addon, "123456789")


def test_resolve_vod_url_wraps_any_exception():
    addon = xbmcaddon.Addon()
    with patch.object(twitch_stream, "resolve_vod_url", side_effect=Exception("network error")):
        with pytest.raises(providers.StreamUnavailableError):
            providers.resolve_vod_url(addon, "123456789")


def test_resolve_clip_url_dispatches_to_twitch():
    addon = xbmcaddon.Addon()
    thumb = "https://clips-media-assets2.twitch.tv/AB12CD34-preview-480x272.jpg"
    with patch.object(twitch_stream, "resolve_clip_url", return_value="https://twitch.example/clip.mp4") as mock:
        url = providers.resolve_clip_url(addon, thumb)
    mock.assert_called_once_with(thumb)
    assert url == "https://twitch.example/clip.mp4"


def test_resolve_clip_url_wraps_unavailable_error():
    addon = xbmcaddon.Addon()
    with patch.object(twitch_stream, "resolve_clip_url", side_effect=twitch_stream.StreamUnavailableError("x")):
        with pytest.raises(providers.StreamUnavailableError):
            providers.resolve_clip_url(addon, "bad-url")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_providers.py -k "resolve_vod_url or resolve_clip_url" -v`
Expected: FAIL with `AttributeError`

- [ ] **Step 3: Write minimal implementation**

Add to `lib/providers.py`, directly after `resolve_stream_url`:

```python
def resolve_vod_url(addon, vod_id):
    """Resolve a Twitch VOD id to a playable HLS URL. Raises StreamUnavailableError -
    never the underlying twitch_stream exception - on any failure, matching
    resolve_stream_url's contract."""
    website_token = addon.getSetting("website_token")
    try:
        return twitch_stream.resolve_vod_url(vod_id, website_token)
    except twitch_stream.StreamUnavailableError as exc:
        raise StreamUnavailableError(str(exc)) from exc
    except Exception as exc:
        raise StreamUnavailableError(str(exc)) from exc


def resolve_clip_url(addon, thumbnail_url):
    """Resolve a Twitch clip's thumbnail_url to its playable direct MP4 URL. Raises
    StreamUnavailableError - never the underlying twitch_stream exception - on any
    failure, matching resolve_stream_url's contract."""
    try:
        return twitch_stream.resolve_clip_url(thumbnail_url)
    except twitch_stream.StreamUnavailableError as exc:
        raise StreamUnavailableError(str(exc)) from exc
    except Exception as exc:
        raise StreamUnavailableError(str(exc)) from exc
```

`addon` is unused in `resolve_clip_url`'s body but kept as a parameter for call-site symmetry with `resolve_vod_url`/`resolve_stream_url` (every other `providers.resolve_*` function takes `addon` first) — do not remove it.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_providers.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add lib/providers.py tests/test_providers.py
git commit -m "Add providers.resolve_vod_url and resolve_clip_url dispatch wrappers"
```

---

### Task 4: `lib/views/utils.py` — new ListItem builders

**Files:**
- Modify: `lib/views/utils.py` (add at end of file)
- Test: `tests/views/test_utils.py` (create — `lib/views/utils.py`'s existing builders have no dedicated test file today; they're only exercised indirectly through `tests/views/test_live_streams_view.py`. This is a new file.)

**Interfaces:**
- Produces: `build_followed_channel_item(channel)` → `xbmcgui.ListItem` for the VODs & Clips channel picker (from a `get_followed_channels` entry: `broadcaster_id`, `broadcaster_login`, `broadcaster_name`). Sets properties `broadcaster_id`, `broadcaster_login`, `broadcaster_name`.
- Produces: `build_video_list_item(video)` → `xbmcgui.ListItem` for a VOD tile (from a `get_videos` entry). Sets property `video_id` = `video["id"]`.
- Produces: `build_clip_list_item(clip)` → `xbmcgui.ListItem` for a Clip tile (from a `get_clips` entry). Sets property `thumbnail_url` = `clip["thumbnail_url"]` (needed by `providers.resolve_clip_url`, which takes a thumbnail URL rather than a clip ID).

- [ ] **Step 1: Write the failing tests**

Create `tests/views/test_utils.py`:

```python
from lib.views import utils as view_utils


def test_build_followed_channel_item_sets_properties():
    channel = {"broadcaster_id": "1", "broadcaster_login": "somechannel", "broadcaster_name": "SomeChannel"}
    item = view_utils.build_followed_channel_item(channel)
    assert item.getLabel() == "SomeChannel"
    assert item.getProperty("broadcaster_id") == "1"
    assert item.getProperty("broadcaster_login") == "somechannel"
    assert item.getProperty("broadcaster_name") == "SomeChannel"


def test_build_video_list_item_sets_properties():
    video = {
        "id": "999", "title": "Epic Stream", "created_at": "2026-08-20T00:00:00Z",
        "duration": "3h8m33s", "thumbnail_url": "https://example.invalid/thumb-%{width}x%{height}.jpg",
        "view_count": 150,
    }
    item = view_utils.build_video_list_item(video)
    assert item.getLabel() == "Epic Stream"
    assert item.getProperty("video_id") == "999"
    assert item.getProperty("duration") == "3h8m33s"
    assert item.getProperty("view_count") == "150"


def test_build_clip_list_item_sets_properties():
    clip = {
        "id": "abc", "title": "Great Play", "created_at": "2026-08-20T00:00:00Z",
        "duration": 29.9, "thumbnail_url": "https://clips-media-assets2.twitch.tv/AB12CD34-preview-480x272.jpg",
        "view_count": 42,
    }
    item = view_utils.build_clip_list_item(clip)
    assert item.getLabel() == "Great Play"
    assert item.getProperty("thumbnail_url") == clip["thumbnail_url"]
    assert item.getProperty("view_count") == "42"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/views/test_utils.py -v`
Expected: FAIL with `AttributeError`

- [ ] **Step 3: Write minimal implementation**

Add to `lib/views/utils.py`, at the end of the file:

```python
def build_followed_channel_item(channel):
    """Build a ListItem for a followed Twitch channel on the VODs & Clips channel picker -
    every followed channel regardless of current live status (VODs/Clips exist independent
    of whether the channel is live right now)."""
    item = xbmcgui.ListItem(channel["broadcaster_name"])
    item.setProperty("broadcaster_id", channel["broadcaster_id"])
    item.setProperty("broadcaster_login", channel["broadcaster_login"])
    item.setProperty("broadcaster_name", channel["broadcaster_name"])
    return item


def build_video_list_item(video):
    """Build a ListItem for one VOD tile on the VODs & Clips content screen."""
    item = xbmcgui.ListItem(video["title"])
    item.setLabel2(f"{video['duration']} · {video['view_count']} views")
    item.setArt({"thumb": thumbnail_url(video["thumbnail_url"])})
    item.setProperty("video_id", video["id"])
    item.setProperty("duration", video["duration"])
    item.setProperty("view_count", str(video["view_count"]))
    return item


def build_clip_list_item(clip):
    """Build a ListItem for one Clip tile on the VODs & Clips content screen."""
    item = xbmcgui.ListItem(clip["title"])
    item.setLabel2(f"{int(clip['duration'])}s · {clip['view_count']} views")
    item.setArt({"thumb": clip["thumbnail_url"]})
    item.setProperty("thumbnail_url", clip["thumbnail_url"])
    item.setProperty("view_count", str(clip["view_count"]))
    return item
```

Note: video thumbnails use `thumbnail_url()` (the same `{width}`/`{height}` placeholder replace already used for stream thumbnails) since Twitch's video thumbnail URLs follow a similar templated pattern — if Twitch's actual placeholder token differs slightly (e.g. a `%{width}` form instead of `{width}`), this degrades gracefully to a broken image with the skin's existing `fallback="DefaultAddonNone.png"`, not a crash. Clip thumbnails are used as-is (no placeholder in Helix's Clips response).

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/views/ -v`
Expected: PASS (all existing view-builder tests plus the 3 new ones)

- [ ] **Step 5: Commit**

```bash
git add lib/views/utils.py tests/views/
git commit -m "Add VODs & Clips ListItem builders to view utils"
```

---

### Task 5: `player.py` — `"twitch_clip"` playback branch

**Files:**
- Modify: `lib/windows/player.py::play_stream` (around the existing `if platform == "twitch" and settings.skip_twitch_ads: ... else: ...` block, currently roughly lines 258-277)
- Test: `tests/windows/test_player.py`

**Interfaces:**
- Consumes: nothing new from other tasks — this is independent, only touches how `play_stream` builds its `ListItem` based on the `platform` argument it already accepts.
- Produces: no new function — `play_stream(url, channel, ..., platform="twitch_clip")` now builds a plain-file `ListItem` (no `inputstream` property, `video/mp4` mime type) instead of the HLS/ISA one.

- [ ] **Step 1: Write the failing test**

This mirrors `test_play_stream_skips_chat_overlay_entirely_for_kick_platform`'s exact mocking style in the same file — `"twitch_clip"`, like `"kick"`, never constructs an overlay or relay (both are gated on `platform == "twitch"`), so `play_stream` falls straight to `xbmc.Player().play(play_url, list_item)`, not the `_ChatAwarePlayer` path. Add:

```python
def test_play_stream_twitch_clip_builds_plain_mp4_list_item_without_inputstream():
    with patch("lib.windows.player.xbmc.Player") as mock_player_cls:
        played = player.play_stream(
            "https://clips-media-assets2.twitch.tv/AB12CD34.mp4",
            "someclip",
            settings=FakeSettings(False),
            platform="twitch_clip",
        )
    assert played is True
    list_item = mock_player_cls.return_value.play.call_args[0][1]
    assert list_item.getProperty("inputstream") == ""
    assert list_item.getMimeType() == "video/mp4"


def test_play_stream_twitch_vod_still_uses_inputstream_adaptive():
    # platform="twitch_vod" must fall through to the unchanged HLS/ISA branch, same as
    # live "twitch" - only "twitch_clip" gets the new plain-file branch.
    with patch("lib.windows.player.Helper") as mock_helper_cls, patch(
        "lib.windows.player.xbmc.Player"
    ) as mock_player_cls:
        mock_helper_cls.return_value.check_inputstream.return_value = True
        mock_helper_cls.return_value.inputstream_addon = "inputstream.adaptive"

        played = player.play_stream(
            "https://usher.ttvnw.net/vod/123456789.m3u8",
            "somevod",
            settings=FakeSettings(False),
            platform="twitch_vod",
        )
    assert played is True
    list_item = mock_player_cls.return_value.play.call_args[0][1]
    assert list_item.getProperty("inputstream") == "inputstream.adaptive"
    assert list_item.getMimeType() == "application/x-mpegURL"
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `pytest tests/windows/test_player.py -k "twitch_clip or twitch_vod_still_uses" -v`
Expected: `test_play_stream_twitch_clip_builds_plain_mp4_list_item_without_inputstream` FAILs (the current code always takes the HLS/ISA branch, so `inputstream` is set and the mime type is `application/x-mpegURL`, not `video/mp4`); `test_play_stream_twitch_vod_still_uses_inputstream_adaptive` already PASSes (no code change needed for that path) — that's expected, it's a regression guard for Step 3, not a new-behavior test.

- [ ] **Step 3: Write minimal implementation**

In `lib/windows/player.py`, inside `play_stream`, change:

```python
    relay = None
    play_url = url
    if platform == "twitch" and settings.skip_twitch_ads:
        relay = AdSkipRelay(
            url,
            log_fn=lambda message: xbmc.log(
                "script.twitch.center: ad-skip relay: " + message, xbmc.LOGINFO
            ),
        )
        play_url = relay.start()
        list_item = xbmcgui.ListItem(path=play_url)
        list_item.setMimeType("video/mp2t")
        list_item.setContentLookup(False)
    else:
        is_helper = Helper("hls")
        if not is_helper.check_inputstream():
            return False
        list_item = xbmcgui.ListItem(path=play_url)
        list_item.setProperty("inputstream", is_helper.inputstream_addon)
        list_item.setProperty("inputstream.adaptive.manifest_type", "hls")
        list_item.setMimeType("application/x-mpegURL")
        list_item.setContentLookup(False)
```

to:

```python
    relay = None
    play_url = url
    if platform == "twitch" and settings.skip_twitch_ads:
        relay = AdSkipRelay(
            url,
            log_fn=lambda message: xbmc.log(
                "script.twitch.center: ad-skip relay: " + message, xbmc.LOGINFO
            ),
        )
        play_url = relay.start()
        list_item = xbmcgui.ListItem(path=play_url)
        list_item.setMimeType("video/mp2t")
        list_item.setContentLookup(False)
    elif platform == "twitch_clip":
        # A Twitch clip is a plain direct .mp4 file, not adaptive HLS - no
        # inputstream.adaptive involvement needed or wanted here.
        list_item = xbmcgui.ListItem(path=play_url)
        list_item.setMimeType("video/mp4")
        list_item.setContentLookup(False)
    else:
        is_helper = Helper("hls")
        if not is_helper.check_inputstream():
            return False
        list_item = xbmcgui.ListItem(path=play_url)
        list_item.setProperty("inputstream", is_helper.inputstream_addon)
        list_item.setProperty("inputstream.adaptive.manifest_type", "hls")
        list_item.setMimeType("application/x-mpegURL")
        list_item.setContentLookup(False)
```

(`platform == "twitch_vod"` deliberately falls through to the unchanged final `else` branch — a VOD is real multi-bitrate HLS, same as live, and already gets the correct ISA treatment with zero code changes.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/windows/test_player.py -v`
Expected: PASS (all existing player tests plus the new one)

- [ ] **Step 5: Commit**

```bash
git add lib/windows/player.py tests/windows/test_player.py
git commit -m "Add twitch_clip playback branch (plain mp4, no inputstream.adaptive)"
```

---

### Task 6: `MainWindow` — `BACK_TARGET` generalization and view-context passing

**Files:**
- Modify: `lib/windows/main_window.py`
- Test: `tests/windows/test_main_window.py`

**Interfaces:**
- Produces: `MainWindow.GROUP_IDS` gains two entries: `"vod_clips_channels": 700`, `"vod_clips": 800`.
- Produces: `MainWindow.onAction`'s back handler now uses `getattr(self._views[self._active_name], "BACK_TARGET", "menu")` instead of the hardcoded `"menu"` literal it currently switches to.
- Produces: `MainWindow._switch_view(self, name, context=None)` — `context`, if given, is stored as `view.context` on the target view instance before `activate()` is called. Every existing call site (`self.window._switch_view("live_streams")` etc.) is unaffected since `context` defaults to `None`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/windows/test_main_window.py`:

```python
def test_onaction_back_uses_menu_when_view_has_no_back_target():
    win = _make_window(initial_view="discover")
    win.onInit()
    with patch("lib.windows.main_window.xbmc.Player") as mock_player_cls:
        mock_player_cls.return_value.isPlaying.return_value = False
        win.onAction(xbmcgui.Action(xbmcgui.ACTION_NAV_BACK))
    assert win._active_name == "menu"


def test_onaction_back_routes_through_a_declared_back_target():
    class ContentFakeView(FakeView):
        BACK_TARGET = "vod_clips_channels"

    win = _make_window(
        initial_view="vod_clips",
        view_classes={"vod_clips_channels": FakeView, "vod_clips": ContentFakeView},
    )
    win.onInit()
    with patch("lib.windows.main_window.xbmc.Player") as mock_player_cls:
        mock_player_cls.return_value.isPlaying.return_value = False
        win.onAction(xbmcgui.Action(xbmcgui.ACTION_NAV_BACK))
    assert win._active_name == "vod_clips_channels"


def test_switch_view_stores_context_on_the_target_view():
    win = _make_window(
        initial_view="menu",
        view_classes={"vod_clips_channels": FakeView, "vod_clips": FakeView},
    )
    win.onInit()
    win._switch_view("vod_clips", context={"broadcaster_id": "123"})
    assert win._views["vod_clips"].context == {"broadcaster_id": "123"}


def test_switch_view_defaults_context_to_none():
    win = _make_window(initial_view="menu")
    win.onInit()
    win._switch_view("discover")
    assert win._views["discover"].context is None


def test_group_ids_include_the_new_vod_clips_screens():
    assert MainWindow.GROUP_IDS["vod_clips_channels"] == 700
    assert MainWindow.GROUP_IDS["vod_clips"] == 800
```

Add `self.context = None` to `FakeView.__init__` (already defined at the top of this test file), right after its existing `self.clicks = []` line. `_switch_view` (Step 3) will overwrite this via a plain `view.context = context` attribute assignment on every call, but the two new context tests need a defined starting value to assert against, matching what the real `MainWindow._switch_view` produces for every view once this task ships.

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/windows/test_main_window.py -v`
Expected: FAIL — `test_group_ids_include_the_new_vod_clips_screens` (KeyError), the back-target tests (still going to "menu"/wrong target), and the context tests (`AttributeError: 'FakeView' object has no attribute 'context'` until you've made the `FakeView.__init__` edit from Step 1, at which point they fail on the assertion instead)

- [ ] **Step 3: Write minimal implementation**

In `lib/windows/main_window.py`:

```python
    GROUP_IDS = {
        "login": 100,
        "menu": 500,
        "live_streams": 200,
        "discover": 300,
        "kick_login": 600,
        "vod_clips_channels": 700,
        "vod_clips": 800,
    }
```

Change `_switch_view`:

```python
    def _switch_view(self, name, context=None):
        old_view = self._views.get(self._active_name)
        if old_view is not None and old_view is not self._views.get(name):
            if hasattr(old_view, "stop"):
                old_view.stop()
        for view_name, group_id in self.GROUP_IDS.items():
            control = self._safe_control(group_id)
            if control:
                control.setVisible(view_name == name)
        self._active_name = name
        view = self._views[name]
        view.context = context
        default_focus = getattr(view, "DEFAULT_FOCUS_ID", None)
        if default_focus is not None:
            self.setFocusId(default_focus)
        view.activate()
```

(only the `def _switch_view(self, name):` signature line and the new `view.context = context` line change — everything else in the method body is unchanged, keep it verbatim.)

Change `onAction`'s back handling from:

```python
            if self._active_name == "menu":
                self.closed_event.quit_requested = True
            else:
                self._switch_view("menu")
            return
```

to:

```python
            if self._active_name == "menu":
                self.closed_event.quit_requested = True
            else:
                back_target = getattr(self._views[self._active_name], "BACK_TARGET", "menu")
                self._switch_view(back_target)
            return
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/windows/test_main_window.py -v`
Expected: PASS (all existing tests plus the new ones)

- [ ] **Step 5: Commit**

```bash
git add lib/windows/main_window.py tests/windows/test_main_window.py
git commit -m "Generalize MainWindow back-navigation and add view-context passing"
```

---

### Task 7: Skin — new groups 700/800 and menu button 503

**Files:**
- Modify: `resources/skins/Default/1080i/script-twitch-center-main.xml`
- Test: `tests/test_addon_manifest.py`

**Interfaces:**
- Consumes: nothing from earlier tasks (pure skin/XML + manifest-test work) — but the control IDs declared here (`503`, `701`-`704`, `801`-`805`) are what Task 8/9's view classes will reference.
- Produces: skin groups `700` and `800` with the control IDs below; menu button `503`.

Control IDs this task declares (referenced by Task 8/9):
- Channel picker (group `700`): `701` channel panel, `702` empty label, `703` error label, `704` relogin button, `705` title label.
- Content screen (group `800`): `801` VODs panel, `802` Clips panel, `803` title label, `804` error label, `805` relogin button.
- Menu: `503` "VODs & Clips" button.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_addon_manifest.py`:

```python
def test_menu_skin_declares_vod_clips_button():
    root = ET.parse(MAIN_SKIN_XML).getroot()
    control_ids = {
        int(c.attrib["id"]) for c in root.iter("control") if "id" in c.attrib
    }
    assert 503 in control_ids


def test_vod_clips_channels_skin_declares_expected_control_ids():
    root = ET.parse(MAIN_SKIN_XML).getroot()
    control_ids = {
        int(c.attrib["id"]) for c in root.iter("control") if "id" in c.attrib
    }
    for expected_id in (701, 702, 703, 704, 705):
        assert expected_id in control_ids


def test_vod_clips_skin_declares_expected_control_ids():
    root = ET.parse(MAIN_SKIN_XML).getroot()
    control_ids = {
        int(c.attrib["id"]) for c in root.iter("control") if "id" in c.attrib
    }
    for expected_id in (801, 802, 803, 804, 805):
        assert expected_id in control_ids


def test_vod_clips_channel_picker_default_focus_is_not_a_list():
    # Same reasoning as test_main_skin_defaultcontrol_is_not_a_data_dependent_list:
    # a panel/list that's still empty at skin-parse time can't be safely focused
    # before Python's onInit populates it, so the channel panel must be type="panel"
    # (which this codebase's convention already treats as focusable-when-empty,
    # matching CHANNEL_LIST_ID's existing "panel" type on Live Streams), not "list".
    root = ET.parse(MAIN_SKIN_XML).getroot()
    assert _control_type(root, 701) == "panel"


def test_main_skin_control_ids_are_still_unique_after_vod_clips_additions():
    control_ids = _main_skin_control_ids()
    duplicates = {cid for cid in control_ids if control_ids.count(cid) > 1}
    assert not duplicates
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_addon_manifest.py -k vod_clips -v`
Expected: FAIL (control IDs not found)

- [ ] **Step 3: Update the MENU (500) group**

In `resources/skins/Default/1080i/script-twitch-center-main.xml`, find the MENU group (starts `<!-- ===================== MENU (500) ===================== -->`). Replace the five `<control type="button" ...>` blocks (`501` through `506`) with:

```xml
      <control type="button" id="501">
        <description>Live Streams</description>
        <posx>660</posx>
        <posy>360</posy>
        <width>600</width>
        <height>80</height>
        <font>font20</font>
        <align>center</align>
        <aligny>center</aligny>
        <onright>501</onright>
        <onleft>501</onleft>
        <ondown>503</ondown>
        <onup>506</onup>
        <label>Live Streams</label>
      </control>
      <control type="button" id="503">
        <description>VODs and Clips</description>
        <posx>660</posx>
        <posy>460</posy>
        <width>600</width>
        <height>80</height>
        <font>font20</font>
        <align>center</align>
        <aligny>center</aligny>
        <onright>503</onright>
        <onleft>503</onleft>
        <onup>501</onup>
        <ondown>502</ondown>
        <label>VODs &amp; Clips</label>
      </control>
      <control type="button" id="502">
        <description>Discover</description>
        <posx>660</posx>
        <posy>560</posy>
        <width>600</width>
        <height>80</height>
        <font>font20</font>
        <align>center</align>
        <aligny>center</aligny>
        <onright>502</onright>
        <onleft>502</onleft>
        <onup>503</onup>
        <ondown>504</ondown>
        <label>Discover</label>
      </control>
      <control type="button" id="504">
        <description>Settings</description>
        <posx>660</posx>
        <posy>660</posy>
        <width>600</width>
        <height>80</height>
        <font>font20</font>
        <align>center</align>
        <aligny>center</aligny>
        <onright>504</onright>
        <onleft>504</onleft>
        <onup>502</onup>
        <ondown>505</ondown>
        <label>Settings</label>
      </control>
      <control type="button" id="505">
        <description>Log in again</description>
        <posx>660</posx>
        <posy>760</posy>
        <width>600</width>
        <height>80</height>
        <font>font13</font>
        <align>center</align>
        <aligny>center</aligny>
        <onright>505</onright>
        <onleft>505</onleft>
        <onup>504</onup>
        <ondown>506</ondown>
        <label>(Twitch) Logged in</label>
      </control>
      <control type="button" id="506">
        <description>Log in to Kick</description>
        <posx>660</posx>
        <posy>860</posy>
        <width>600</width>
        <height>80</height>
        <font>font13</font>
        <align>center</align>
        <aligny>center</aligny>
        <onright>506</onright>
        <onleft>506</onleft>
        <onup>505</onup>
        <ondown>501</ondown>
        <label>Log in to Kick</label>
      </control>
```

(`&amp;` is XML's escape for a literal `&` in the label text — required, an unescaped `&` breaks XML parsing.)

- [ ] **Step 4: Add the two new groups**

Insert the following two whole groups right before the `<!-- ===================== VERSION LABEL (900) ===================== -->` comment (i.e., after the DISCOVER (300) group's closing `</control>`):

```xml
    <!-- ===================== VOD/CLIPS CHANNELS (700) ===================== -->
    <control type="group" id="700">
      <control type="label" id="705">
        <description>Title</description>
        <posx>64</posx>
        <posy>48</posy>
        <width>1200</width>
        <height>48</height>
        <font>Title</font>
        <textcolor>FFE6E1E5</textcolor>
        <label>VODs &amp; Clips</label>
      </control>
      <control type="label">
        <description>Subtitle</description>
        <posx>64</posx>
        <posy>100</posy>
        <width>1200</width>
        <height>28</height>
        <font>CardBody</font>
        <textcolor>FFCAC4D0</textcolor>
        <label>Pick a followed channel</label>
      </control>
      <control type="panel" id="701">
        <description>Followed channels (VODs and Clips picker)</description>
        <posx>48</posx>
        <posy>160</posy>
        <width>1824</width>
        <height>860</height>
        <onup>701</onup>
        <ondown>701</ondown>
        <onleft>701</onleft>
        <onright>701</onright>
        <orientation>horizontal</orientation>
        <itemlayout width="300" height="90">
          <control type="image">
            <posx>0</posx>
            <posy>0</posy>
            <width>284</width>
            <height>74</height>
            <texture>name_box.png</texture>
          </control>
          <control type="label">
            <posx>0</posx>
            <posy>0</posy>
            <width>284</width>
            <height>74</height>
            <font>CardHeadline</font>
            <textcolor>FFE6E1E5</textcolor>
            <align>center</align>
            <aligny>center</aligny>
            <scroll>false</scroll>
            <label>$INFO[ListItem.Label]</label>
          </control>
        </itemlayout>
        <focusedlayout width="300" height="90">
          <control type="image">
            <width>284</width>
            <height>74</height>
            <texture>card_surface_focus.png</texture>
            <colordiffuse>ff0a6ed3</colordiffuse>
          </control>
          <control type="label">
            <posx>0</posx>
            <posy>0</posy>
            <width>284</width>
            <height>74</height>
            <font>CardHeadline</font>
            <textcolor>FFD0BCFF</textcolor>
            <align>center</align>
            <aligny>center</aligny>
            <scroll>true</scroll>
            <label>$INFO[ListItem.Label]</label>
          </control>
        </focusedlayout>
      </control>
      <control type="label" id="702">
        <description>Empty followed list message</description>
        <posx>560</posx>
        <posy>460</posy>
        <width>800</width>
        <height>60</height>
        <font>CardHeadline</font>
        <textcolor>FFCAC4D0</textcolor>
        <align>center</align>
        <label></label>
      </control>
      <control type="label" id="703">
        <description>Error / re-login message</description>
        <posx>560</posx>
        <posy>460</posy>
        <width>800</width>
        <height>60</height>
        <font>CardHeadline</font>
        <textcolor>FFCAC4D0</textcolor>
        <align>center</align>
        <label></label>
      </control>
      <control type="button" id="704">
        <description>Log in again</description>
        <posx>760</posx>
        <posy>540</posy>
        <width>400</width>
        <height>60</height>
        <font>CardBody</font>
        <textcolor>FFE6E1E5</textcolor>
        <focusedcolor>FFD0BCFF</focusedcolor>
        <align>center</align>
        <aligny>center</aligny>
        <onup>701</onup>
        <ondown>701</ondown>
        <onleft>704</onleft>
        <onright>704</onright>
        <label>Log in again</label>
        <visible>false</visible>
      </control>
    </control>

    <!-- ===================== VOD/CLIPS CONTENT (800) ===================== -->
    <control type="group" id="800">
      <control type="label" id="803">
        <description>Title (selected channel's display name)</description>
        <posx>64</posx>
        <posy>48</posy>
        <width>1200</width>
        <height>48</height>
        <font>Title</font>
        <textcolor>FFE6E1E5</textcolor>
        <label></label>
      </control>
      <control type="label">
        <description>VODs section label</description>
        <posx>64</posx>
        <posy>110</posy>
        <width>400</width>
        <height>32</height>
        <font>CardHeadline</font>
        <textcolor>FFCAC4D0</textcolor>
        <label>VODs</label>
      </control>
      <control type="panel" id="801">
        <description>VODs</description>
        <posx>48</posx>
        <posy>150</posy>
        <width>1824</width>
        <height>300</height>
        <onup>801</onup>
        <ondown>802</ondown>
        <onleft>801</onleft>
        <onright>801</onright>
        <orientation>horizontal</orientation>
        <itemlayout width="320" height="270">
          <control type="image">
            <posx>8</posx>
            <posy>8</posy>
            <width>304</width>
            <height>28</height>
            <texture>name_box.png</texture>
          </control>
          <control type="label">
            <posx>8</posx>
            <posy>8</posy>
            <width>304</width>
            <height>28</height>
            <font>CardHeadline</font>
            <textcolor>FFE6E1E5</textcolor>
            <align>center</align>
            <aligny>center</aligny>
            <scroll>false</scroll>
            <label>$INFO[ListItem.Label]</label>
          </control>
          <control type="image">
            <posx>8</posx>
            <posy>44</posy>
            <width>304</width>
            <height>171</height>
            <aspectratio>scale</aspectratio>
            <texture fallback="DefaultAddonNone.png">$INFO[ListItem.Art(thumb)]</texture>
            <diffuse>thumb_mask.png</diffuse>
          </control>
          <control type="label">
            <posx>8</posx>
            <posy>223</posy>
            <width>304</width>
            <height>28</height>
            <font>CardBody</font>
            <textcolor>FFCAC4D0</textcolor>
            <aligny>center</aligny>
            <label>$INFO[ListItem.Label2]</label>
          </control>
        </itemlayout>
        <focusedlayout width="320" height="270">
          <control type="image">
            <width>320</width>
            <height>270</height>
            <texture>card_surface_focus.png</texture>
            <colordiffuse>ff0a6ed3</colordiffuse>
          </control>
          <control type="image">
            <posx>8</posx>
            <posy>8</posy>
            <width>304</width>
            <height>28</height>
            <texture>name_box.png</texture>
          </control>
          <control type="label">
            <posx>8</posx>
            <posy>8</posy>
            <width>304</width>
            <height>28</height>
            <font>CardHeadline</font>
            <textcolor>FFD0BCFF</textcolor>
            <align>center</align>
            <aligny>center</aligny>
            <scroll>true</scroll>
            <label>$INFO[ListItem.Label]</label>
          </control>
          <control type="image">
            <posx>8</posx>
            <posy>44</posy>
            <width>304</width>
            <height>171</height>
            <aspectratio>scale</aspectratio>
            <texture fallback="DefaultAddonNone.png">$INFO[ListItem.Art(thumb)]</texture>
            <diffuse>thumb_mask.png</diffuse>
          </control>
          <control type="label">
            <posx>8</posx>
            <posy>223</posy>
            <width>304</width>
            <height>28</height>
            <font>CardBody</font>
            <textcolor>FFE6E1E5</textcolor>
            <aligny>center</aligny>
            <label>$INFO[ListItem.Label2]</label>
          </control>
        </focusedlayout>
      </control>
      <control type="label">
        <description>Clips section label</description>
        <posx>64</posx>
        <posy>470</posy>
        <width>400</width>
        <height>32</height>
        <font>CardHeadline</font>
        <textcolor>FFCAC4D0</textcolor>
        <label>Clips</label>
      </control>
      <control type="panel" id="802">
        <description>Clips</description>
        <posx>48</posx>
        <posy>510</posy>
        <width>1824</width>
        <height>300</height>
        <onup>801</onup>
        <ondown>802</ondown>
        <onleft>802</onleft>
        <onright>802</onright>
        <orientation>horizontal</orientation>
        <itemlayout width="320" height="270">
          <control type="image">
            <posx>8</posx>
            <posy>8</posy>
            <width>304</width>
            <height>28</height>
            <texture>name_box.png</texture>
          </control>
          <control type="label">
            <posx>8</posx>
            <posy>8</posy>
            <width>304</width>
            <height>28</height>
            <font>CardHeadline</font>
            <textcolor>FFE6E1E5</textcolor>
            <align>center</align>
            <aligny>center</aligny>
            <scroll>false</scroll>
            <label>$INFO[ListItem.Label]</label>
          </control>
          <control type="image">
            <posx>8</posx>
            <posy>44</posy>
            <width>304</width>
            <height>171</height>
            <aspectratio>scale</aspectratio>
            <texture fallback="DefaultAddonNone.png">$INFO[ListItem.Art(thumb)]</texture>
            <diffuse>thumb_mask.png</diffuse>
          </control>
          <control type="label">
            <posx>8</posx>
            <posy>223</posy>
            <width>304</width>
            <height>28</height>
            <font>CardBody</font>
            <textcolor>FFCAC4D0</textcolor>
            <aligny>center</aligny>
            <label>$INFO[ListItem.Label2]</label>
          </control>
        </itemlayout>
        <focusedlayout width="320" height="270">
          <control type="image">
            <width>320</width>
            <height>270</height>
            <texture>card_surface_focus.png</texture>
            <colordiffuse>ff0a6ed3</colordiffuse>
          </control>
          <control type="image">
            <posx>8</posx>
            <posy>8</posy>
            <width>304</width>
            <height>28</height>
            <texture>name_box.png</texture>
          </control>
          <control type="label">
            <posx>8</posx>
            <posy>8</posy>
            <width>304</width>
            <height>28</height>
            <font>CardHeadline</font>
            <textcolor>FFD0BCFF</textcolor>
            <align>center</align>
            <aligny>center</aligny>
            <scroll>true</scroll>
            <label>$INFO[ListItem.Label]</label>
          </control>
          <control type="image">
            <posx>8</posx>
            <posy>44</posy>
            <width>304</width>
            <height>171</height>
            <aspectratio>scale</aspectratio>
            <texture fallback="DefaultAddonNone.png">$INFO[ListItem.Art(thumb)]</texture>
            <diffuse>thumb_mask.png</diffuse>
          </control>
          <control type="label">
            <posx>8</posx>
            <posy>223</posy>
            <width>304</width>
            <height>28</height>
            <font>CardBody</font>
            <textcolor>FFE6E1E5</textcolor>
            <aligny>center</aligny>
            <label>$INFO[ListItem.Label2]</label>
          </control>
        </focusedlayout>
      </control>
      <control type="label" id="804">
        <description>Error / re-login message</description>
        <posx>560</posx>
        <posy>860</posy>
        <width>800</width>
        <height>60</height>
        <font>CardHeadline</font>
        <textcolor>FFCAC4D0</textcolor>
        <align>center</align>
        <label></label>
      </control>
      <control type="button" id="805">
        <description>Log in again</description>
        <posx>760</posx>
        <posy>930</posy>
        <width>400</width>
        <height>60</height>
        <font>CardBody</font>
        <textcolor>FFE6E1E5</textcolor>
        <focusedcolor>FFD0BCFF</focusedcolor>
        <align>center</align>
        <aligny>center</aligny>
        <onup>802</onup>
        <ondown>801</ondown>
        <onleft>805</onleft>
        <onright>805</onright>
        <label>Log in again</label>
        <visible>false</visible>
      </control>
    </control>

```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_addon_manifest.py -v`
Expected: PASS (all existing manifest tests plus the new ones — including the pre-existing `test_main_skin_control_ids_are_unique_across_all_groups`, proving no ID collisions were introduced)

- [ ] **Step 6: Commit**

```bash
git add resources/skins/Default/1080i/script-twitch-center-main.xml tests/test_addon_manifest.py
git commit -m "Add VODs & Clips skin groups and menu button"
```

---

### Task 8: `VodClipsChannelsView`

**Files:**
- Create: `lib/views/vod_clips_channels_view.py`
- Modify: `lib/windows/main_window.py::_default_view_classes` (register the new view)
- Modify: `lib/views/menu_view.py` (add the button constant and dispatch)
- Test: `tests/views/test_vod_clips_channels_view.py`, `tests/views/test_menu_view.py`

**Interfaces:**
- Consumes: `api.get_followed_channels(access_token, client_id, user_id)` (existing), `view_utils.build_followed_channel_item(channel)` (Task 4), skin control IDs `701`/`702`/`703`/`704`/`705` (Task 7), `MainWindow._switch_view(name, context=None)` (Task 6).
- Produces: `VodClipsChannelsView` class with `CHANNEL_LIST_ID=701`, `EMPTY_LABEL_ID=702`, `ERROR_LABEL_ID=703`, `RELOGIN_BUTTON_ID=704`, `TITLE_LABEL_ID=705`; `activate()`, `handle_action(action)`, `handle_click(control_id)` methods (same shape as every other view). On selecting a channel, calls `self.window._switch_view("vod_clips", context={"broadcaster_id": ..., "broadcaster_login": ..., "broadcaster_name": ...})`.
- Produces: `MenuView.VOD_CLIPS_BUTTON_ID = 503`; selecting it calls `self.window._switch_view("vod_clips_channels")`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/views/test_menu_view.py`:

```python
def test_selecting_vod_clips_switches_to_vod_clips_channels_view():
    window = FakeMainWindow()
    _select(window, MenuView.VOD_CLIPS_BUTTON_ID)
    assert window.switched_to == ["vod_clips_channels"]
```

Create `tests/views/test_vod_clips_channels_view.py`. This mirrors `tests/views/test_live_streams_view.py`'s established fixture shapes exactly: `FakeAddon = xbmcaddon.Addon`, a `_addon_with_token` helper that saves a token via `lib.twitch.auth.save_token`, a `FakeWindow` with `getControl`/`setFocusId`/`getFocusId`/`_switch_view`, `xbmcaddon.Addon` patched globally (not module-qualified, since the view does a plain `import xbmcaddon`), and `lib.views.<module>.auth.refresh_access_token` patched module-qualified (since the view does `from lib.twitch import auth` then calls `auth.refresh_access_token`). The one difference from `LiveStreamsView`'s tests: `FakeWindow._switch_view` here must record the `context` kwarg too, since `VodClipsChannelsView` passes one.

```python
from unittest.mock import patch

import xbmcaddon
import xbmcgui

from lib.twitch import api
from lib.twitch.auth import load_token, save_token
from lib.views.vod_clips_channels_view import VodClipsChannelsView

FakeAddon = xbmcaddon.Addon


class FakeWindow:
    def __init__(self):
        self._controls = {}
        self._focus_id = None
        self.switched_to = []

    def getControl(self, control_id):
        from xbmcgui import FakeListControl

        if control_id not in self._controls:
            self._controls[control_id] = FakeListControl()
        return self._controls[control_id]

    def setFocusId(self, control_id):
        self._focus_id = control_id

    def getFocusId(self):
        return self._focus_id

    def _switch_view(self, name, context=None):
        self.switched_to.append((name, context))


def _addon_with_token(token):
    addon = FakeAddon()
    if token is not None:
        save_token(token, addon)
    return addon


FOLLOWED = [
    {"broadcaster_id": "1", "broadcaster_login": "alice", "broadcaster_name": "Alice"},
    {"broadcaster_id": "2", "broadcaster_login": "bob", "broadcaster_name": "Bob"},
]


def test_activate_populates_channel_list_from_all_followed_channels():
    addon = _addon_with_token({"access_token": "tok", "refresh_token": "ref", "user_id": "u1"})
    with patch("xbmcaddon.Addon", return_value=addon), patch.object(
        api, "get_followed_channels", return_value=FOLLOWED
    ):
        window = FakeWindow()
        view = VodClipsChannelsView(window)
        view.activate()
    channel_list = window.getControl(VodClipsChannelsView.CHANNEL_LIST_ID)
    assert channel_list.size() == 2
    assert window.getFocusId() == VodClipsChannelsView.CHANNEL_LIST_ID


def test_activate_sets_title():
    addon = _addon_with_token({"access_token": "tok", "refresh_token": "ref", "user_id": "u1"})
    with patch("xbmcaddon.Addon", return_value=addon), patch.object(
        api, "get_followed_channels", return_value=[]
    ):
        window = FakeWindow()
        view = VodClipsChannelsView(window)
        view.activate()
    assert window.getControl(VodClipsChannelsView.TITLE_LABEL_ID).getLabel() == "VODs & Clips"


def test_activate_shows_empty_message_when_no_followed_channels():
    addon = _addon_with_token({"access_token": "tok", "refresh_token": "ref", "user_id": "u1"})
    with patch("xbmcaddon.Addon", return_value=addon), patch.object(
        api, "get_followed_channels", return_value=[]
    ):
        window = FakeWindow()
        view = VodClipsChannelsView(window)
        view.activate()
    empty_label = window.getControl(VodClipsChannelsView.EMPTY_LABEL_ID)
    assert empty_label.getLabel() != ""
    assert window.getControl(VodClipsChannelsView.RELOGIN_BUTTON_ID).isVisible() is True


def test_selecting_a_channel_switches_to_vod_clips_with_context():
    addon = _addon_with_token({"access_token": "tok", "refresh_token": "ref", "user_id": "u1"})
    followed = [{"broadcaster_id": "1", "broadcaster_login": "alice", "broadcaster_name": "Alice"}]
    with patch("xbmcaddon.Addon", return_value=addon), patch.object(
        api, "get_followed_channels", return_value=followed
    ):
        window = FakeWindow()
        view = VodClipsChannelsView(window)
        view.activate()
        channel_list = window.getControl(VodClipsChannelsView.CHANNEL_LIST_ID)
        channel_list.selectItem(0)
        window.setFocusId(VodClipsChannelsView.CHANNEL_LIST_ID)
        view.handle_action(xbmcgui.Action(xbmcgui.ACTION_SELECT_ITEM))
    assert window.switched_to == [(
        "vod_clips",
        {"broadcaster_id": "1", "broadcaster_login": "alice", "broadcaster_name": "Alice"},
    )]


def test_activate_shows_relogin_button_when_no_token():
    with patch("xbmcaddon.Addon", return_value=_addon_with_token(None)):
        window = FakeWindow()
        view = VodClipsChannelsView(window)
        view.activate()
    assert window.getControl(VodClipsChannelsView.ERROR_LABEL_ID).getLabel() != ""
    assert window.getControl(VodClipsChannelsView.RELOGIN_BUTTON_ID).isVisible() is True


def test_activate_shows_relogin_prompt_when_token_refresh_fails_after_expiry():
    old_token = {"access_token": "old", "refresh_token": "ref", "user_id": "u1"}
    addon = _addon_with_token(old_token)
    with patch("xbmcaddon.Addon", return_value=addon), patch.object(
        api, "get_followed_channels", side_effect=api.TokenExpiredError()
    ), patch(
        "lib.views.vod_clips_channels_view.auth.refresh_access_token", return_value=None
    ):
        window = FakeWindow()
        view = VodClipsChannelsView(window)
        view.activate()
    assert load_token(addon) is None
    assert window.getControl(VodClipsChannelsView.ERROR_LABEL_ID).getLabel() != ""
    assert window.getControl(VodClipsChannelsView.RELOGIN_BUTTON_ID).isVisible() is True


def test_selecting_the_relogin_button_switches_to_login():
    window = FakeWindow()
    view = VodClipsChannelsView(window)
    window.setFocusId(VodClipsChannelsView.RELOGIN_BUTTON_ID)
    view.handle_action(xbmcgui.Action(xbmcgui.ACTION_SELECT_ITEM))
    assert window.switched_to == [("login", None)]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/views/test_menu_view.py tests/views/test_vod_clips_channels_view.py -v`
Expected: FAIL — `ModuleNotFoundError` for the view, `AttributeError` for `VOD_CLIPS_BUTTON_ID`

- [ ] **Step 3: Write minimal implementation**

Create `lib/views/vod_clips_channels_view.py`:

```python
"""VODs & Clips channel picker: every followed Twitch channel, live or not - VODs and
Clips exist independent of current live status. Not a Window subclass - see MainWindow."""
import xbmc
import xbmcaddon
import xbmcgui

from lib.twitch import api, auth
from lib.views import utils as view_utils

CHANNEL_LIST_ID = 701
EMPTY_LABEL_ID = 702
ERROR_LABEL_ID = 703
RELOGIN_BUTTON_ID = 704
TITLE_LABEL_ID = 705

_MISSING_TOKEN_MESSAGE = "You're not logged in. Reopen the addon to log in."
_EMPTY_FOLLOWED_MESSAGE = "You're not following anyone yet."
_NETWORK_ERROR_MESSAGE = "Couldn't reach Twitch. Check your connection and reopen the addon."
_RELOGIN_MESSAGE = "Your session expired. Log in again to continue."


class VodClipsChannelsView:
    CHANNEL_LIST_ID = CHANNEL_LIST_ID
    EMPTY_LABEL_ID = EMPTY_LABEL_ID
    ERROR_LABEL_ID = ERROR_LABEL_ID
    RELOGIN_BUTTON_ID = RELOGIN_BUTTON_ID
    TITLE_LABEL_ID = TITLE_LABEL_ID

    def __init__(self, window, closed_event=None):
        self.window = window
        self.closed_event = closed_event

    def _safe_control(self, control_id):
        try:
            return self.window.getControl(control_id)
        except Exception:
            return None

    def activate(self):
        addon = xbmcaddon.Addon()
        title_label = self._safe_control(self.TITLE_LABEL_ID)
        if title_label:
            title_label.setLabel("VODs & Clips")
        client_id = addon.getSetting("client_id")
        token = auth.load_token(addon)
        if token is None:
            self._show_error(_MISSING_TOKEN_MESSAGE)
            return
        if not token.get("user_id"):
            auth.clear_token(addon)
            self._show_error(_RELOGIN_MESSAGE)
            return

        try:
            self._load_and_populate(addon, client_id, token)
        except api.TokenExpiredError:
            self._handle_expired_token(addon, client_id, token)
        except Exception as exc:
            xbmc.log(
                "script.twitch.center: VODs & Clips channel picker failed to load: " + repr(exc),
                xbmc.LOGERROR,
            )
            self._show_error(_NETWORK_ERROR_MESSAGE)

    def _load_and_populate(self, addon, client_id, token):
        followed = api.get_followed_channels(token["access_token"], client_id, token["user_id"])
        self._populate(followed)
        channel_list = self._safe_control(self.CHANNEL_LIST_ID)
        if channel_list and channel_list.size():
            self.window.setFocusId(self.CHANNEL_LIST_ID)
        else:
            self._show_relogin_button()

    def _handle_expired_token(self, addon, client_id, token):
        new_token = auth.refresh_access_token(
            client_id,
            token["refresh_token"],
            on_error=lambda reason: xbmc.log(
                "script.twitch.center: token refresh failed: " + reason, xbmc.LOGERROR
            ),
        )
        if new_token is None:
            auth.clear_token(addon)
            self._show_error(_RELOGIN_MESSAGE)
            return
        new_token["user_id"] = token.get("user_id")
        new_token["login"] = token.get("login")
        new_token["display_name"] = token.get("display_name")
        auth.save_token(new_token, addon)
        try:
            self._load_and_populate(addon, client_id, new_token)
        except api.TokenExpiredError:
            auth.clear_token(addon)
            self._show_error(_RELOGIN_MESSAGE)
        except Exception as exc:
            xbmc.log(
                "script.twitch.center: VODs & Clips channel picker failed after token "
                "refresh: " + repr(exc),
                xbmc.LOGERROR,
            )
            self._show_error(_NETWORK_ERROR_MESSAGE)

    def _populate(self, followed):
        empty_label = self._safe_control(self.EMPTY_LABEL_ID)
        if empty_label:
            empty_label.setLabel("")
        error_label = self._safe_control(self.ERROR_LABEL_ID)
        if error_label:
            error_label.setLabel("")
        relogin_btn = self._safe_control(self.RELOGIN_BUTTON_ID)
        if relogin_btn:
            relogin_btn.setVisible(False)
        control = self._safe_control(self.CHANNEL_LIST_ID)
        if control:
            control.reset()
            if not followed:
                if empty_label:
                    empty_label.setLabel(_EMPTY_FOLLOWED_MESSAGE)
                return
            items = [view_utils.build_followed_channel_item(c) for c in followed]
            control.addItems(items)

    def _show_error(self, message):
        channel_list = self._safe_control(self.CHANNEL_LIST_ID)
        if channel_list:
            channel_list.reset()
        empty_label = self._safe_control(self.EMPTY_LABEL_ID)
        if empty_label:
            empty_label.setLabel("")
        error_label = self._safe_control(self.ERROR_LABEL_ID)
        if error_label:
            error_label.setLabel(message)
        self._show_relogin_button()

    def _show_relogin_button(self):
        relogin_btn = self._safe_control(self.RELOGIN_BUTTON_ID)
        if relogin_btn:
            relogin_btn.setVisible(True)
            self.window.setFocusId(self.RELOGIN_BUTTON_ID)

    def handle_action(self, action):
        if action.getId() != xbmcgui.ACTION_SELECT_ITEM:
            return
        focus = self.window.getFocusId()
        if focus == self.RELOGIN_BUTTON_ID:
            self.window._switch_view("login")
        elif focus == self.CHANNEL_LIST_ID:
            self._on_channel_selected()

    def handle_click(self, control_id):
        pass

    def _on_channel_selected(self):
        control = self._safe_control(self.CHANNEL_LIST_ID)
        if not control:
            return
        selected = control.getSelectedItem()
        if selected is None:
            return
        context = {
            "broadcaster_id": selected.getProperty("broadcaster_id"),
            "broadcaster_login": selected.getProperty("broadcaster_login"),
            "broadcaster_name": selected.getProperty("broadcaster_name"),
        }
        self.window._switch_view("vod_clips", context=context)
```

In `lib/windows/main_window.py::_default_view_classes`, add the import and registration:

```python
        from lib.views.vod_clips_channels_view import VodClipsChannelsView
```

alongside the other view imports, and add `"vod_clips_channels": VodClipsChannelsView,` to the returned dict (the `"vod_clips": ...` entry comes in Task 9, once `VodClipsView` exists — don't add a `"vod_clips"` key yet, or `_default_view_classes` will reference a class that doesn't exist until Task 9).

In `lib/views/menu_view.py`, add the constant and dispatch:

```python
    VOD_CLIPS_BUTTON_ID = 503
```

(add it as a class attribute, next to `LIVE_STREAMS_BUTTON_ID`/`DISCOVER_BUTTON_ID`), and in `handle_action`:

```python
        elif focus == self.VOD_CLIPS_BUTTON_ID:
            self.window._switch_view("vod_clips_channels")
```

(add this `elif` branch anywhere among the existing `elif focus == ...` chain in `handle_action`).

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/views/test_menu_view.py tests/views/test_vod_clips_channels_view.py -v`
Expected: PASS

- [ ] **Step 5: Run the full suite to catch any `_default_view_classes` regressions**

Run: `pytest -v`
Expected: PASS — in particular `tests/windows/test_main_window.py` and `tests/test_main.py`, which exercise `_default_view_classes()` indirectly

- [ ] **Step 6: Commit**

```bash
git add lib/views/vod_clips_channels_view.py lib/views/menu_view.py lib/windows/main_window.py tests/views/test_vod_clips_channels_view.py tests/views/test_menu_view.py
git commit -m "Add VODs & Clips channel picker view and menu entry"
```

---

### Task 9: `VodClipsView` (content screen — VODs + Clips + playback)

**Files:**
- Create: `lib/views/vod_clips_view.py`
- Modify: `lib/windows/main_window.py::_default_view_classes` (register `"vod_clips"`, completing what Task 8 deferred)
- Test: `tests/views/test_vod_clips_view.py`

**Interfaces:**
- Consumes: `api.get_videos`/`api.get_clips` (Task 1), `providers.resolve_vod_url`/`providers.resolve_clip_url`/`providers.StreamUnavailableError` (Task 3), `view_utils.build_video_list_item`/`build_clip_list_item` (Task 4), `player.play_stream(url, title, platform=...)` (existing, extended in Task 5), skin control IDs `801`/`802`/`803`/`804`/`805` (Task 7), `self.context` set by `MainWindow._switch_view` (Task 6) — a dict with `broadcaster_id`/`broadcaster_login`/`broadcaster_name`, or `None` if this view is somehow activated without going through the channel picker (must not crash — treat as an error state, see below).
- Produces: `VodClipsView` class with `VODS_LIST_ID=801`, `CLIPS_LIST_ID=802`, `TITLE_LABEL_ID=803`, `ERROR_LABEL_ID=804`, `RELOGIN_BUTTON_ID=805`, `BACK_TARGET = "vod_clips_channels"`.

- [ ] **Step 1: Write the failing tests**

Create `tests/views/test_vod_clips_view.py`, using the same `FakeWindow`/`_addon_with_token` shapes as Task 8's test file (this view also needs a token to call `api.get_videos`/`api.get_clips`, so it needs the full `_addon_with_token` + `xbmcaddon.Addon` patching, unlike the simpler cases). Patch `player.play_stream` module-qualified (`"lib.views.vod_clips_view.player.play_stream"`), matching `test_live_streams_view.py`'s exact pattern for the same function; patch `providers.resolve_vod_url`/`resolve_clip_url` via `patch.object`, matching that file's pattern for `providers.resolve_stream_url`.

```python
from unittest.mock import patch

import xbmcaddon
import xbmcgui

from lib import providers
from lib.twitch import api
from lib.twitch.auth import load_token, save_token
from lib.views.vod_clips_view import VodClipsView

FakeAddon = xbmcaddon.Addon


class FakeWindow:
    def __init__(self):
        self._controls = {}
        self._focus_id = None
        self.switched_to = []

    def getControl(self, control_id):
        from xbmcgui import FakeListControl

        if control_id not in self._controls:
            self._controls[control_id] = FakeListControl()
        return self._controls[control_id]

    def setFocusId(self, control_id):
        self._focus_id = control_id

    def getFocusId(self):
        return self._focus_id

    def _switch_view(self, name, context=None):
        self.switched_to.append((name, context))


def _addon_with_token(token):
    addon = FakeAddon()
    if token is not None:
        save_token(token, addon)
    return addon


CONTEXT = {"broadcaster_id": "1", "broadcaster_login": "alice", "broadcaster_name": "Alice"}

VIDEOS = [{
    "id": "v1", "title": "VOD 1", "created_at": "2026-08-20T00:00:00Z",
    "duration": "1h", "thumbnail_url": "https://example.invalid/t-%{width}x%{height}.jpg",
    "view_count": 5,
}]

CLIPS = [{
    "id": "c1", "title": "Clip 1", "created_at": "2026-08-20T00:00:00Z",
    "duration": 20.0, "thumbnail_url": "https://clips-media-assets2.twitch.tv/X-preview-480x272.jpg",
    "view_count": 3,
}]


def test_activate_with_no_context_shows_error_without_crashing():
    window = FakeWindow()
    view = VodClipsView(window)
    view.context = None
    view.activate()
    error_label = window.getControl(VodClipsView.ERROR_LABEL_ID)
    assert error_label.getLabel() != ""


def test_activate_populates_both_vods_and_clips_lists():
    addon = _addon_with_token({"access_token": "tok", "refresh_token": "ref", "user_id": "u1"})
    with patch("xbmcaddon.Addon", return_value=addon), patch.object(
        api, "get_videos", return_value=VIDEOS
    ), patch.object(api, "get_clips", return_value=CLIPS):
        window = FakeWindow()
        view = VodClipsView(window)
        view.context = CONTEXT
        view.activate()
    assert window.getControl(VodClipsView.VODS_LIST_ID).size() == 1
    assert window.getControl(VodClipsView.CLIPS_LIST_ID).size() == 1
    assert window.getControl(VodClipsView.TITLE_LABEL_ID).getLabel() == "Alice"
    assert window.getFocusId() == VodClipsView.VODS_LIST_ID


def test_selecting_a_vod_resolves_and_plays_it():
    addon = _addon_with_token({"access_token": "tok", "refresh_token": "ref", "user_id": "u1"})
    with patch("xbmcaddon.Addon", return_value=addon), patch.object(
        api, "get_videos", return_value=VIDEOS
    ), patch.object(api, "get_clips", return_value=[]), patch.object(
        providers, "resolve_vod_url", return_value="https://usher.example/vod.m3u8"
    ) as mock_resolve, patch(
        "lib.views.vod_clips_view.player.play_stream", return_value=True
    ) as mock_play:
        window = FakeWindow()
        view = VodClipsView(window)
        view.context = CONTEXT
        view.activate()
        vods_control = window.getControl(VodClipsView.VODS_LIST_ID)
        vods_control.selectItem(0)
        window.setFocusId(VodClipsView.VODS_LIST_ID)
        view.handle_action(xbmcgui.Action(xbmcgui.ACTION_SELECT_ITEM))

    mock_resolve.assert_called_once()
    assert mock_resolve.call_args.args[1] == "v1"
    mock_play.assert_called_once_with(
        "https://usher.example/vod.m3u8", "VOD 1", platform="twitch_vod"
    )


def test_selecting_a_clip_resolves_and_plays_it():
    addon = _addon_with_token({"access_token": "tok", "refresh_token": "ref", "user_id": "u1"})
    with patch("xbmcaddon.Addon", return_value=addon), patch.object(
        api, "get_videos", return_value=[]
    ), patch.object(api, "get_clips", return_value=CLIPS), patch.object(
        providers, "resolve_clip_url", return_value="https://clips.example/x.mp4"
    ) as mock_resolve, patch(
        "lib.views.vod_clips_view.player.play_stream", return_value=True
    ) as mock_play:
        window = FakeWindow()
        view = VodClipsView(window)
        view.context = CONTEXT
        view.activate()
        clips_control = window.getControl(VodClipsView.CLIPS_LIST_ID)
        clips_control.selectItem(0)
        window.setFocusId(VodClipsView.CLIPS_LIST_ID)
        view.handle_action(xbmcgui.Action(xbmcgui.ACTION_SELECT_ITEM))

    mock_resolve.assert_called_once()
    assert mock_resolve.call_args.args[1] == CLIPS[0]["thumbnail_url"]
    mock_play.assert_called_once_with(
        "https://clips.example/x.mp4", "Clip 1", platform="twitch_clip"
    )


def test_vod_playback_resolution_failure_shows_error_without_crashing():
    addon = _addon_with_token({"access_token": "tok", "refresh_token": "ref", "user_id": "u1"})
    with patch("xbmcaddon.Addon", return_value=addon), patch.object(
        api, "get_videos", return_value=VIDEOS
    ), patch.object(api, "get_clips", return_value=[]), patch.object(
        providers, "resolve_vod_url", side_effect=providers.StreamUnavailableError("x")
    ):
        window = FakeWindow()
        view = VodClipsView(window)
        view.context = CONTEXT
        view.activate()
        vods_control = window.getControl(VodClipsView.VODS_LIST_ID)
        vods_control.selectItem(0)
        window.setFocusId(VodClipsView.VODS_LIST_ID)
        view.handle_action(xbmcgui.Action(xbmcgui.ACTION_SELECT_ITEM))
    error_label = window.getControl(VodClipsView.ERROR_LABEL_ID)
    assert error_label.getLabel() != ""
    # A transient playback failure must not wipe the lists the user is browsing.
    assert window.getControl(VodClipsView.VODS_LIST_ID).size() == 1


def test_activate_shows_relogin_prompt_when_token_refresh_fails_after_expiry():
    old_token = {"access_token": "old", "refresh_token": "ref", "user_id": "u1"}
    addon = _addon_with_token(old_token)
    with patch("xbmcaddon.Addon", return_value=addon), patch.object(
        api, "get_videos", side_effect=api.TokenExpiredError()
    ), patch(
        "lib.views.vod_clips_view.auth.refresh_access_token", return_value=None
    ):
        window = FakeWindow()
        view = VodClipsView(window)
        view.context = CONTEXT
        view.activate()
    assert load_token(addon) is None
    assert window.getControl(VodClipsView.ERROR_LABEL_ID).getLabel() != ""
    assert window.getControl(VodClipsView.RELOGIN_BUTTON_ID).isVisible() is True


def test_back_target_is_the_channel_picker():
    assert VodClipsView.BACK_TARGET == "vod_clips_channels"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/views/test_vod_clips_view.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Write minimal implementation**

Create `lib/views/vod_clips_view.py`:

```python
"""VODs & Clips content screen: the selected followed channel's VODs and Clips, both
video-only playback (no chat, no ad-skip relay - platform="twitch_vod"/"twitch_clip"
already route player.play_stream around both). Not a Window subclass - see MainWindow."""
import xbmc
import xbmcaddon
import xbmcgui

from lib import providers
from lib.twitch import api, auth
from lib.views import utils as view_utils
from lib.windows import player

VODS_LIST_ID = 801
CLIPS_LIST_ID = 802
TITLE_LABEL_ID = 803
ERROR_LABEL_ID = 804
RELOGIN_BUTTON_ID = 805

_MISSING_TOKEN_MESSAGE = "You're not logged in. Reopen the addon to log in."
_NETWORK_ERROR_MESSAGE = "Couldn't reach Twitch. Check your connection and reopen the addon."
_RELOGIN_MESSAGE = "Your session expired. Log in again to continue."
_NO_CONTEXT_MESSAGE = "No channel selected. Go back and pick a followed channel."
_PLAYBACK_ERROR_MESSAGE = "Couldn't start playback. Try again."


class VodClipsView:
    VODS_LIST_ID = VODS_LIST_ID
    CLIPS_LIST_ID = CLIPS_LIST_ID
    TITLE_LABEL_ID = TITLE_LABEL_ID
    ERROR_LABEL_ID = ERROR_LABEL_ID
    RELOGIN_BUTTON_ID = RELOGIN_BUTTON_ID
    BACK_TARGET = "vod_clips_channels"

    def __init__(self, window, closed_event=None):
        self.window = window
        self.closed_event = closed_event
        self.context = None

    def _safe_control(self, control_id):
        try:
            return self.window.getControl(control_id)
        except Exception:
            return None

    def activate(self):
        if not self.context or not self.context.get("broadcaster_id"):
            self._show_error(_NO_CONTEXT_MESSAGE)
            return

        title_label = self._safe_control(self.TITLE_LABEL_ID)
        if title_label:
            title_label.setLabel(self.context.get("broadcaster_name", ""))

        addon = xbmcaddon.Addon()
        client_id = addon.getSetting("client_id")
        token = auth.load_token(addon)
        if token is None:
            self._show_error(_MISSING_TOKEN_MESSAGE)
            return
        if not token.get("user_id"):
            auth.clear_token(addon)
            self._show_error(_RELOGIN_MESSAGE)
            return

        try:
            self._load_and_populate(addon, client_id, token)
        except api.TokenExpiredError:
            self._handle_expired_token(addon, client_id, token)
        except Exception as exc:
            xbmc.log(
                "script.twitch.center: VODs & Clips content failed to load: " + repr(exc),
                xbmc.LOGERROR,
            )
            self._show_error(_NETWORK_ERROR_MESSAGE)

    def _load_and_populate(self, addon, client_id, token):
        broadcaster_id = self.context["broadcaster_id"]
        videos = api.get_videos(token["access_token"], client_id, broadcaster_id)
        clips = api.get_clips(token["access_token"], client_id, broadcaster_id)
        self._populate(videos, clips)

    def _handle_expired_token(self, addon, client_id, token):
        new_token = auth.refresh_access_token(
            client_id,
            token["refresh_token"],
            on_error=lambda reason: xbmc.log(
                "script.twitch.center: token refresh failed: " + reason, xbmc.LOGERROR
            ),
        )
        if new_token is None:
            auth.clear_token(addon)
            self._show_error(_RELOGIN_MESSAGE)
            return
        new_token["user_id"] = token.get("user_id")
        new_token["login"] = token.get("login")
        new_token["display_name"] = token.get("display_name")
        auth.save_token(new_token, addon)
        try:
            self._load_and_populate(addon, client_id, new_token)
        except api.TokenExpiredError:
            auth.clear_token(addon)
            self._show_error(_RELOGIN_MESSAGE)
        except Exception as exc:
            xbmc.log(
                "script.twitch.center: VODs & Clips content failed after token refresh: "
                + repr(exc),
                xbmc.LOGERROR,
            )
            self._show_error(_NETWORK_ERROR_MESSAGE)

    def _populate(self, videos, clips):
        error_label = self._safe_control(self.ERROR_LABEL_ID)
        if error_label:
            error_label.setLabel("")
        relogin_btn = self._safe_control(self.RELOGIN_BUTTON_ID)
        if relogin_btn:
            relogin_btn.setVisible(False)

        vods_control = self._safe_control(self.VODS_LIST_ID)
        if vods_control:
            vods_control.reset()
            vods_control.addItems([view_utils.build_video_list_item(v) for v in videos])

        clips_control = self._safe_control(self.CLIPS_LIST_ID)
        if clips_control:
            clips_control.reset()
            clips_control.addItems([view_utils.build_clip_list_item(c) for c in clips])

        if vods_control and vods_control.size():
            self.window.setFocusId(self.VODS_LIST_ID)
        elif clips_control and clips_control.size():
            self.window.setFocusId(self.CLIPS_LIST_ID)
        else:
            self._show_relogin_button()

    def _show_error(self, message):
        vods_control = self._safe_control(self.VODS_LIST_ID)
        if vods_control:
            vods_control.reset()
        clips_control = self._safe_control(self.CLIPS_LIST_ID)
        if clips_control:
            clips_control.reset()
        error_label = self._safe_control(self.ERROR_LABEL_ID)
        if error_label:
            error_label.setLabel(message)
        self._show_relogin_button()

    def _show_relogin_button(self):
        relogin_btn = self._safe_control(self.RELOGIN_BUTTON_ID)
        if relogin_btn:
            relogin_btn.setVisible(True)
            self.window.setFocusId(self.RELOGIN_BUTTON_ID)

    def _show_results_error(self, message):
        error_label = self._safe_control(self.ERROR_LABEL_ID)
        if error_label:
            error_label.setLabel(message)

    def handle_action(self, action):
        if action.getId() != xbmcgui.ACTION_SELECT_ITEM:
            return
        focus = self.window.getFocusId()
        if focus == self.RELOGIN_BUTTON_ID:
            self.window._switch_view("login")
        elif focus == self.VODS_LIST_ID:
            self._on_vod_selected()
        elif focus == self.CLIPS_LIST_ID:
            self._on_clip_selected()

    def handle_click(self, control_id):
        pass

    def _on_vod_selected(self):
        control = self._safe_control(self.VODS_LIST_ID)
        if not control:
            return
        selected = control.getSelectedItem()
        if selected is None:
            return
        video_id = selected.getProperty("video_id")
        title = selected.getLabel()
        addon = xbmcaddon.Addon()
        try:
            url = providers.resolve_vod_url(addon, video_id)
            played = player.play_stream(url, title, platform="twitch_vod")
        except providers.StreamUnavailableError:
            self._show_results_error(_PLAYBACK_ERROR_MESSAGE)
            return
        except Exception as exc:
            xbmc.log(
                "script.twitch.center: VOD selection failed: " + repr(exc), xbmc.LOGERROR
            )
            self._show_results_error(_PLAYBACK_ERROR_MESSAGE)
            return
        if not played:
            self._show_results_error(_PLAYBACK_ERROR_MESSAGE)

    def _on_clip_selected(self):
        control = self._safe_control(self.CLIPS_LIST_ID)
        if not control:
            return
        selected = control.getSelectedItem()
        if selected is None:
            return
        thumbnail_url = selected.getProperty("thumbnail_url")
        title = selected.getLabel()
        addon = xbmcaddon.Addon()
        try:
            url = providers.resolve_clip_url(addon, thumbnail_url)
            played = player.play_stream(url, title, platform="twitch_clip")
        except providers.StreamUnavailableError:
            self._show_results_error(_PLAYBACK_ERROR_MESSAGE)
            return
        except Exception as exc:
            xbmc.log(
                "script.twitch.center: Clip selection failed: " + repr(exc), xbmc.LOGERROR
            )
            self._show_results_error(_PLAYBACK_ERROR_MESSAGE)
            return
        if not played:
            self._show_results_error(_PLAYBACK_ERROR_MESSAGE)
```

In `lib/windows/main_window.py::_default_view_classes`, add:

```python
        from lib.views.vod_clips_view import VodClipsView
```

and add `"vod_clips": VodClipsView,` to the returned dict.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/views/test_vod_clips_view.py -v`
Expected: PASS

- [ ] **Step 5: Run the full suite**

Run: `pytest -v`
Expected: PASS, no regressions anywhere (in particular `tests/test_architecture.py`, `tests/test_addon_manifest.py`, `tests/windows/test_main_window.py`, `tests/test_main.py`)

- [ ] **Step 6: Commit**

```bash
git add lib/views/vod_clips_view.py lib/windows/main_window.py tests/views/test_vod_clips_view.py
git commit -m "Add VODs & Clips content view with VOD/Clip playback"
```

---

## Manual verification (not automated — do after Task 9)

Per this repo's live-testing conventions: clean Kodi restart, log in, follow a channel that has both VODs and Clips, navigate Menu → VODs & Clips → that channel, confirm both lists populate and are sorted newest-first, play one of each and confirm video-only playback (no chat overlay pops up), confirm Back from the content screen returns to the channel picker (not straight to Menu), confirm Back from the channel picker returns to Menu. This step is out of scope for automated task execution — flag it to the user rather than attempting it as part of plan execution, since it requires a real Kodi instance and a real followed channel with VODs/Clips. Specifically watch for the two flagged unofficial-API risks: whether `get_vod_playback_access_token`'s persisted query actually returns `videoPlaybackAccessToken` (VOD playback), and whether Twitch's video `thumbnail_url` placeholder format matches the existing `{width}`/`{height}` replace (VOD thumbnails — a mismatch here is cosmetic, not a playback blocker).
