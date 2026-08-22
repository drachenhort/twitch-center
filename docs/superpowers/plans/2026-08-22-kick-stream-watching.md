# Kick Stream Watching Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Merge Kick.com channels into the existing Live Streams / Discover / Search screens (unified lists, interleaved by viewer count) and wire playback through Kodi's player, reusing the already-built, unwired `lib/kick/` package — with no Kick chat (explicitly deferred).

**Architecture:** A new pure-Python dispatch/normalization layer (`lib/providers.py`) sits between the existing per-view UI code and `lib/twitch/`/`lib/kick/`, converting each platform's results into one shared dict shape so views merge/render/dispatch without branching on platform. A new `KickLoginView` (mirroring `LoginView`'s shape but driving `kick.auth.run_pkce_login`'s PKCE flow instead of the device-code flow) is reachable from a new Menu button, gated on `kick_client_id`/`kick_client_secret` being set. `player.py` gets a `platform` parameter that skips the chat-overlay branch entirely for Kick and routes stall-recovery through the correct platform's resolver.

**Tech Stack:** Python 3, `pytest` + `unittest.mock`, existing `xbmcgui`/`xbmcaddon` Kodi stubs (`tests/kodi_stubs/`), Kodi skin XML (`resources/skins/Default/1080i/script-twitch-center-main.xml`).

**Spec:** `docs/superpowers/specs/2026-08-22-kick-stream-watching-design.md`

## Global Constraints

- No `xbmc*` imports in `lib/providers.py` except through an `addon` parameter callers pass in (same discipline as `lib/settings.py` and the existing `lib/twitch/`, `lib/kick/` packages) — enforced by extending `tests/test_architecture.py`.
- Kick's missing-token case is always silent: any `lib/providers.py` function that lists/searches Kick content returns `[]` (never raises, never shows an error) if no Kick token is saved. Twitch's own missing-token behavior in each view is unchanged — untouched by this plan.
- No live network calls in tests — every `lib.twitch.*`/`lib.kick.*` call in `lib/providers.py`'s tests is mocked.
- Normalized dicts share this exact shape everywhere (spec: "Architecture: a thin provider-dispatch layer"):
  ```python
  {
      "platform": "twitch" | "kick",
      "id": str,
      "login": str,
      "display_name": str,
      "is_live": bool,
      "viewer_count": int,
      "game_name": str,
      "thumbnail_url": str,
  }
  ```
- Kick's real field names for `/livestreams` and the unofficial search endpoint are **not confirmed** against a live response as of this writing (spec: "Risks / open items"). Every place this plan reads a Kick response field uses `.get()` with a safe default — never a bare `[...]` subscript that could `KeyError` on a real response with different field names. This must be corrected against a real request early in implementation (see Task 2's note) rather than shipped as an unverified guess.
- No Kick chat, anywhere, in this plan. `chat_overlay_enabled` never applies to a Kick stream.

---

### Task 1: Kick favorites storage (`lib/providers.py` scaffold)

**Files:**
- Create: `lib/providers.py`
- Create: `tests/test_providers.py`
- Modify: `resources/settings.xml`
- Modify: `resources/language/resource.language.en_gb/strings.po`
- Modify: `tests/test_settings.py`

**Interfaces:**
- Produces: `providers.get_kick_favorites(addon) -> list[str]`, `providers.add_kick_favorite(addon, slug)`, `providers.remove_kick_favorite(addon, slug)`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_providers.py
import xbmcaddon

from lib import providers


def test_get_kick_favorites_defaults_to_empty_list():
    addon = xbmcaddon.Addon()
    assert providers.get_kick_favorites(addon) == []


def test_get_kick_favorites_returns_empty_list_for_malformed_json():
    addon = xbmcaddon.Addon()
    addon.setSetting("kick_favorite_channels", "not-json")
    assert providers.get_kick_favorites(addon) == []


def test_get_kick_favorites_returns_empty_list_for_non_list_json():
    addon = xbmcaddon.Addon()
    addon.setSetting("kick_favorite_channels", '{"not": "a list"}')
    assert providers.get_kick_favorites(addon) == []


def test_add_kick_favorite_appends_and_persists():
    addon = xbmcaddon.Addon()
    providers.add_kick_favorite(addon, "somechannel")
    assert providers.get_kick_favorites(addon) == ["somechannel"]


def test_add_kick_favorite_is_idempotent():
    addon = xbmcaddon.Addon()
    providers.add_kick_favorite(addon, "somechannel")
    providers.add_kick_favorite(addon, "somechannel")
    assert providers.get_kick_favorites(addon) == ["somechannel"]


def test_remove_kick_favorite_deletes_it():
    addon = xbmcaddon.Addon()
    providers.add_kick_favorite(addon, "somechannel")
    providers.add_kick_favorite(addon, "otherchannel")
    providers.remove_kick_favorite(addon, "somechannel")
    assert providers.get_kick_favorites(addon) == ["otherchannel"]


def test_remove_kick_favorite_is_a_no_op_if_not_present():
    addon = xbmcaddon.Addon()
    providers.add_kick_favorite(addon, "somechannel")
    providers.remove_kick_favorite(addon, "nosuchchannel")
    assert providers.get_kick_favorites(addon) == ["somechannel"]
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest tests/test_providers.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'lib.providers'`

- [ ] **Step 3: Implement**

```python
# lib/providers.py
"""Cross-platform dispatch layer: normalizes lib.twitch and lib.kick results
into one common shape (see the plan's Global Constraints for the exact dict
shape) so views merge/render/dispatch on channels without branching on
platform. No xbmc* imports - Kodi access happens only through the `addon`
parameter callers pass in, same discipline as lib/settings.py."""
import json


def get_kick_favorites(addon):
    """Return the list of favorited Kick channel slugs, stored as a JSON
    array in the kick_favorite_channels setting. Malformed/missing/non-list
    JSON all normalize to an empty list rather than raising - this is
    user-editable-adjacent state (built up one add_kick_favorite call at a
    time), not something that should ever crash a screen load."""
    raw = addon.getSetting("kick_favorite_channels")
    if not raw:
        return []
    try:
        favorites = json.loads(raw)
    except ValueError:
        return []
    if not isinstance(favorites, list):
        return []
    return favorites


def add_kick_favorite(addon, slug):
    favorites = get_kick_favorites(addon)
    if slug not in favorites:
        favorites.append(slug)
        addon.setSetting("kick_favorite_channels", json.dumps(favorites))


def remove_kick_favorite(addon, slug):
    favorites = get_kick_favorites(addon)
    if slug in favorites:
        favorites.remove(slug)
        addon.setSetting("kick_favorite_channels", json.dumps(favorites))
```

- [ ] **Step 4: Run to verify it passes**

Run: `pytest tests/test_providers.py -v`
Expected: PASS

- [ ] **Step 5: Add the `kick_favorite_channels` setting**

In `resources/settings.xml`, insert after the existing `kick_token` setting block, before `</group>`:

```xml
        <setting id="kick_favorite_channels" type="string" label="30026" help="">
          <level>2</level>
          <default>[]</default>
          <constraints>
            <allowempty>true</allowempty>
          </constraints>
          <control type="edit" format="string"/>
          <visible>false</visible>
        </setting>
```

In `resources/language/resource.language.en_gb/strings.po`, append at the end of the file:

```
msgctxt "#30026"
msgid "Kick Favorite Channels"
msgstr ""
```

(Confirm `#30026` is actually free first: `grep -n msgctxt resources/language/resource.language.en_gb/strings.po | tail -3` — if the repo has moved since this plan was written, use the next free id instead and note the substitution in your commit message, same as provider-core's Task 9 had to.)

- [ ] **Step 6: Add a settings round-trip test**

Append to `tests/test_settings.py`:

```python
def test_kick_favorite_channels_setting_round_trips():
    addon = xbmcaddon.Addon()
    addon.setSetting("kick_favorite_channels", '["somechannel"]')
    assert addon.getSetting("kick_favorite_channels") == '["somechannel"]'
```

- [ ] **Step 7: Run the full relevant test set**

Run: `pytest tests/test_providers.py tests/test_settings.py tests/test_addon_manifest.py -v`
Expected: PASS

- [ ] **Step 8: Commit**

```bash
git add lib/providers.py tests/test_providers.py resources/settings.xml resources/language/resource.language.en_gb/strings.po tests/test_settings.py
git commit -m "feat: add Kick favorites storage (lib/providers.py scaffold)"
```

---

### Task 2: Live-streams normalization + viewer-count merge

**Files:**
- Modify: `lib/providers.py`
- Modify: `tests/test_providers.py`

**Interfaces:**
- Consumes: `lib.kick.auth.load_token`, `lib.kick.api.get_channel`, `lib.providers.get_kick_favorites` (Task 1).
- Produces: `providers.normalize_twitch_channel(channel, stream_data=None) -> dict`, `providers.get_kick_live_favorites(addon, get_channel_fn=None) -> list[dict]`, `providers.merge_by_viewer_count(*lists) -> list[dict]`.

**Before writing code:** the field names below for a Kick `/channels` (`get_channel`) response — `stream.viewer_count`, `stream.category.name`, `stream.thumbnail.url` — are this plan's best-effort guess (the confirmed shape only covers `broadcaster_user_id`, `slug`, and `stream.is_live`/`stream.url`, per `lib/kick/stream.py`'s existing tests). Every read below uses `.get()` with safe defaults specifically because of this — if you have a way to make one real authenticated `GET https://api.kick.com/public/v1/channels?slug=<a real live channel>` request before writing this task's implementation, do it and correct the field names here first; if not, proceed with the guesses and leave the defensive `.get()` calls in place so a wrong guess degrades to a blank subtitle instead of crashing the screen.

- [ ] **Step 1: Write the failing tests**

```python
# append to tests/test_providers.py
from unittest.mock import patch

from lib import providers


def test_normalize_twitch_channel_live():
    channel = {"broadcaster_id": "1", "broadcaster_login": "alice", "broadcaster_name": "Alice"}
    stream_data = {
        "viewer_count": 500,
        "game_name": "Just Chatting",
        "thumbnail_url": "https://example.invalid/{width}x{height}.jpg",
    }
    result = providers.normalize_twitch_channel(channel, stream_data)
    assert result == {
        "platform": "twitch",
        "id": "1",
        "login": "alice",
        "display_name": "Alice",
        "is_live": True,
        "viewer_count": 500,
        "game_name": "Just Chatting",
        "thumbnail_url": "https://example.invalid/320x180.jpg",
    }


def test_normalize_twitch_channel_offline():
    channel = {"broadcaster_id": "1", "broadcaster_login": "alice", "broadcaster_name": "Alice"}
    result = providers.normalize_twitch_channel(channel)
    assert result == {
        "platform": "twitch",
        "id": "1",
        "login": "alice",
        "display_name": "Alice",
        "is_live": False,
        "viewer_count": 0,
        "game_name": "",
        "thumbnail_url": "",
    }


def test_get_kick_live_favorites_returns_empty_list_when_no_kick_token():
    addon = xbmcaddon.Addon()  # no kick_token set
    assert providers.get_kick_live_favorites(addon) == []


def test_get_kick_live_favorites_returns_empty_list_when_no_favorites():
    addon = xbmcaddon.Addon()
    addon.setSetting("kick_token", '{"access_token": "tok"}')
    assert providers.get_kick_live_favorites(addon) == []


def test_get_kick_live_favorites_normalizes_live_favorites_only():
    addon = xbmcaddon.Addon()
    addon.setSetting("kick_token", '{"access_token": "tok"}')
    providers.add_kick_favorite(addon, "livechannel")
    providers.add_kick_favorite(addon, "offlinechannel")

    def fake_get_channel(access_token, slug):
        assert access_token == "tok"
        if slug == "livechannel":
            return {
                "broadcaster_user_id": 42,
                "slug": "livechannel",
                "stream": {
                    "is_live": True,
                    "viewer_count": 300,
                    "category": {"name": "Just Chatting"},
                    "thumbnail": {"url": "https://example.invalid/thumb.jpg"},
                },
            }
        return {"broadcaster_user_id": 43, "slug": "offlinechannel", "stream": {"is_live": False}}

    result = providers.get_kick_live_favorites(addon, get_channel_fn=fake_get_channel)
    assert result == [
        {
            "platform": "kick",
            "id": "42",
            "login": "livechannel",
            "display_name": "livechannel",
            "is_live": True,
            "viewer_count": 300,
            "game_name": "Just Chatting",
            "thumbnail_url": "https://example.invalid/thumb.jpg",
        }
    ]


def test_get_kick_live_favorites_skips_a_favorite_that_errors():
    addon = xbmcaddon.Addon()
    addon.setSetting("kick_token", '{"access_token": "tok"}')
    providers.add_kick_favorite(addon, "brokenchannel")
    providers.add_kick_favorite(addon, "goodchannel")

    def fake_get_channel(access_token, slug):
        if slug == "brokenchannel":
            raise Exception("boom")
        return {
            "broadcaster_user_id": 7,
            "slug": "goodchannel",
            "stream": {"is_live": True, "viewer_count": 10},
        }

    result = providers.get_kick_live_favorites(addon, get_channel_fn=fake_get_channel)
    assert [item["login"] for item in result] == ["goodchannel"]


def test_get_kick_live_favorites_defensively_handles_missing_fields():
    # The Kick /channels response shape for live-favorite lookups is not
    # fully confirmed - this pins the "never crash on an unexpected shape"
    # contract regardless of which fields turn out to be right.
    addon = xbmcaddon.Addon()
    addon.setSetting("kick_token", '{"access_token": "tok"}')
    providers.add_kick_favorite(addon, "sparsechannel")

    def fake_get_channel(access_token, slug):
        return {"broadcaster_user_id": 1, "slug": "sparsechannel", "stream": {"is_live": True}}

    result = providers.get_kick_live_favorites(addon, get_channel_fn=fake_get_channel)
    assert result == [
        {
            "platform": "kick",
            "id": "1",
            "login": "sparsechannel",
            "display_name": "sparsechannel",
            "is_live": True,
            "viewer_count": 0,
            "game_name": "",
            "thumbnail_url": "",
        }
    ]


def test_merge_by_viewer_count_interleaves_descending():
    twitch_items = [
        {"platform": "twitch", "viewer_count": 500},
        {"platform": "twitch", "viewer_count": 50},
    ]
    kick_items = [
        {"platform": "kick", "viewer_count": 300},
    ]
    merged = providers.merge_by_viewer_count(twitch_items, kick_items)
    assert [item["viewer_count"] for item in merged] == [500, 300, 50]


def test_merge_by_viewer_count_handles_empty_lists():
    assert providers.merge_by_viewer_count([], []) == []
    assert providers.merge_by_viewer_count([{"platform": "twitch", "viewer_count": 1}], []) == [
        {"platform": "twitch", "viewer_count": 1}
    ]
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest tests/test_providers.py -v -k "normalize_twitch or kick_live_favorites or merge_by_viewer_count"`
Expected: FAIL with `AttributeError` for each missing function

- [ ] **Step 3: Implement**

```python
# add to lib/providers.py
from lib.kick import auth as kick_auth
from lib.kick.api import get_channel as _kick_get_channel


def _twitch_thumbnail_url(raw_url, width=320, height=180):
    return raw_url.replace("{width}", str(width)).replace("{height}", str(height))


def normalize_twitch_channel(channel, stream_data=None):
    """Convert a (channel, stream_data) pair from lib.twitch.api's followed-
    channels/live-status shape into the shared normalized dict. stream_data
    is None for an offline channel."""
    if stream_data:
        return {
            "platform": "twitch",
            "id": channel["broadcaster_id"],
            "login": channel["broadcaster_login"],
            "display_name": channel["broadcaster_name"],
            "is_live": True,
            "viewer_count": stream_data["viewer_count"],
            "game_name": stream_data["game_name"],
            "thumbnail_url": _twitch_thumbnail_url(stream_data["thumbnail_url"]),
        }
    return {
        "platform": "twitch",
        "id": channel["broadcaster_id"],
        "login": channel["broadcaster_login"],
        "display_name": channel["broadcaster_name"],
        "is_live": False,
        "viewer_count": 0,
        "game_name": "",
        "thumbnail_url": "",
    }


def _normalize_kick_channel(channel):
    """Convert one lib.kick.api.get_channel() response into the shared
    normalized dict. Field names beyond broadcaster_user_id/slug/stream.is_live
    are unconfirmed against a real API response (see this task's note in the
    plan) - every read here uses .get() with a safe default so a wrong guess
    degrades gracefully instead of raising."""
    stream_info = channel.get("stream") or {}
    category = stream_info.get("category") or {}
    thumbnail = stream_info.get("thumbnail") or {}
    slug = channel.get("slug", "")
    return {
        "platform": "kick",
        "id": str(channel.get("broadcaster_user_id", "")),
        "login": slug,
        "display_name": slug,
        "is_live": bool(stream_info.get("is_live", False)),
        "viewer_count": stream_info.get("viewer_count", 0),
        "game_name": category.get("name", ""),
        "thumbnail_url": thumbnail.get("url", ""),
    }


def get_kick_live_favorites(addon, get_channel_fn=None):
    """Return normalized, LIVE-only entries for every favorited Kick channel.
    Silently returns [] if there's no saved Kick token (Kick login is
    optional and independent of Twitch's) - never raises. A favorite whose
    lookup itself raises (network error, deleted channel, etc.) is skipped
    rather than failing the whole list, so one bad favorite can't blank the
    screen."""
    if get_channel_fn is None:
        get_channel_fn = _kick_get_channel
    token = kick_auth.load_token(addon)
    if token is None:
        return []
    results = []
    for slug in get_kick_favorites(addon):
        try:
            channel = get_channel_fn(token["access_token"], slug)
        except Exception:
            continue
        if channel is None:
            continue
        normalized = _normalize_kick_channel(channel)
        if normalized["is_live"]:
            results.append(normalized)
    return results


def merge_by_viewer_count(*lists):
    """Combine any number of normalized-dict lists into one, sorted by
    viewer_count descending. Used to interleave Twitch and Kick results
    (Live Streams, Search, category browsing) without either view knowing
    the other platform exists."""
    combined = []
    for items in lists:
        combined.extend(items)
    combined.sort(key=lambda item: item["viewer_count"], reverse=True)
    return combined
```

- [ ] **Step 4: Run to verify it passes**

Run: `pytest tests/test_providers.py -v`
Expected: PASS (all tests in the file)

- [ ] **Step 5: Commit**

```bash
git add lib/providers.py tests/test_providers.py
git commit -m "feat: add live-streams normalization and viewer-count merge to providers"
```

---

### Task 3: Kick categories (Discover row support)

**Files:**
- Modify: `lib/providers.py`
- Modify: `tests/test_providers.py`

**Interfaces:**
- Consumes: `lib.kick.auth.load_token`, `lib.kick.api.get_top_categories`, `lib.kick.api.get_live_streams`, `_normalize_kick_channel` (Task 2).
- Produces: `providers.get_kick_top_categories(addon, get_top_categories_fn=None) -> list[dict]`, `providers.get_kick_category_streams(addon, category_id, get_live_streams_fn=None) -> list[dict]`.

- [ ] **Step 1: Write the failing tests**

```python
# append to tests/test_providers.py
def test_get_kick_top_categories_returns_empty_list_when_no_kick_token():
    addon = xbmcaddon.Addon()
    assert providers.get_kick_top_categories(addon) == []


def test_get_kick_top_categories_returns_categories_when_logged_in():
    addon = xbmcaddon.Addon()
    addon.setSetting("kick_token", '{"access_token": "tok"}')

    def fake_get_top_categories(access_token, first=20):
        assert access_token == "tok"
        return [{"id": 7, "name": "Just Chatting"}, {"id": 8, "name": "Games"}]

    result = providers.get_kick_top_categories(addon, get_top_categories_fn=fake_get_top_categories)
    assert result == [{"id": 7, "name": "Just Chatting"}, {"id": 8, "name": "Games"}]


def test_get_kick_top_categories_returns_empty_list_on_error():
    addon = xbmcaddon.Addon()
    addon.setSetting("kick_token", '{"access_token": "tok"}')

    def failing(access_token, first=20):
        raise Exception("boom")

    result = providers.get_kick_top_categories(addon, get_top_categories_fn=failing)
    assert result == []


def test_get_kick_category_streams_returns_empty_list_when_no_kick_token():
    addon = xbmcaddon.Addon()
    assert providers.get_kick_category_streams(addon, category_id=7) == []


def test_get_kick_category_streams_normalizes_results():
    addon = xbmcaddon.Addon()
    addon.setSetting("kick_token", '{"access_token": "tok"}')

    def fake_get_live_streams(access_token, category_id=None, first=20):
        assert access_token == "tok"
        assert category_id == 7
        return [
            {
                "broadcaster_user_id": 1,
                "slug": "somechannel",
                "viewer_count": 42,
                "category": {"name": "Just Chatting"},
            }
        ]

    result = providers.get_kick_category_streams(addon, category_id=7, get_live_streams_fn=fake_get_live_streams)
    assert result == [
        {
            "platform": "kick",
            "id": "1",
            "login": "somechannel",
            "display_name": "somechannel",
            "is_live": True,
            "viewer_count": 42,
            "game_name": "Just Chatting",
            "thumbnail_url": "",
        }
    ]


def test_get_kick_category_streams_returns_empty_list_on_error():
    addon = xbmcaddon.Addon()
    addon.setSetting("kick_token", '{"access_token": "tok"}')

    def failing(access_token, category_id=None, first=20):
        raise Exception("boom")

    result = providers.get_kick_category_streams(addon, category_id=7, get_live_streams_fn=failing)
    assert result == []
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest tests/test_providers.py -v -k "kick_top_categories or kick_category_streams"`
Expected: FAIL with `AttributeError` for each missing function

- [ ] **Step 3: Implement**

`lib/kick/api.get_live_streams`'s entries come back **without** the `stream` wrapper that `get_channel` uses (per its existing implementation - it returns `body["data"]` directly, one dict per live stream, not nested under a `"stream"` key like `get_channel`'s single-channel response is). Note: `_normalize_kick_channel` (Task 2) expects the `get_channel`-shaped nesting, so category-stream entries need their own, flatter normalizer.

```python
# add to lib/providers.py
from lib.kick.api import get_live_streams as _kick_get_live_streams, get_top_categories as _kick_get_top_categories


def get_kick_top_categories(addon, get_top_categories_fn=None):
    """Return Kick's top categories, or [] if there's no saved Kick token or
    the call fails - never raises. Used to populate Discover's Kick
    categories row, which simply doesn't appear (via an empty row) rather
    than erroring when the user isn't logged into Kick."""
    if get_top_categories_fn is None:
        get_top_categories_fn = _kick_get_top_categories
    token = kick_auth.load_token(addon)
    if token is None:
        return []
    try:
        return get_top_categories_fn(token["access_token"])
    except Exception:
        return []


def _normalize_kick_live_stream_entry(entry):
    """Convert one entry from lib.kick.api.get_live_streams() (flat shape,
    NOT nested under "stream" like get_channel()'s response) into the shared
    normalized dict. Every entry from this endpoint is live by definition.
    Field names beyond broadcaster_user_id/slug are unconfirmed (see this
    plan's Task 2 note) - .get() throughout."""
    category = entry.get("category") or {}
    thumbnail = entry.get("thumbnail") or {}
    slug = entry.get("slug", "")
    return {
        "platform": "kick",
        "id": str(entry.get("broadcaster_user_id", "")),
        "login": slug,
        "display_name": slug,
        "is_live": True,
        "viewer_count": entry.get("viewer_count", 0),
        "game_name": category.get("name", ""),
        "thumbnail_url": thumbnail.get("url", ""),
    }


def get_kick_category_streams(addon, category_id, get_live_streams_fn=None):
    """Return normalized live streams for one Kick category, or [] if
    there's no saved Kick token or the call fails - never raises."""
    if get_live_streams_fn is None:
        get_live_streams_fn = _kick_get_live_streams
    token = kick_auth.load_token(addon)
    if token is None:
        return []
    try:
        entries = get_live_streams_fn(token["access_token"], category_id=category_id)
    except Exception:
        return []
    return [_normalize_kick_live_stream_entry(entry) for entry in entries]
```

- [ ] **Step 4: Run to verify it passes**

Run: `pytest tests/test_providers.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add lib/providers.py tests/test_providers.py
git commit -m "feat: add Kick category browsing to providers"
```

---

### Task 4: Search normalization + merge

**Files:**
- Modify: `lib/providers.py`
- Modify: `tests/test_providers.py`

**Interfaces:**
- Consumes: `lib.kick.auth.load_token`, `lib.kick.api.search_channels`.
- Produces: `providers.normalize_twitch_search_result(item) -> dict`, `providers.get_kick_search_results(addon, query, search_channels_fn=None) -> list[dict]`.

- [ ] **Step 1: Write the failing tests**

```python
# append to tests/test_providers.py
def test_normalize_twitch_search_result_from_channel_shape():
    item = {
        "id": "1",
        "broadcaster_login": "alice",
        "display_name": "Alice",
        "is_live": True,
        "game_name": "Just Chatting",
        "thumbnail_url": "https://example.invalid/thumb.jpg",
    }
    result = providers.normalize_twitch_search_result(item)
    assert result == {
        "platform": "twitch",
        "id": "1",
        "login": "alice",
        "display_name": "Alice",
        "is_live": True,
        "viewer_count": 0,
        "game_name": "Just Chatting",
        "thumbnail_url": "https://example.invalid/thumb.jpg",
    }


def test_normalize_twitch_search_result_from_stream_shape():
    item = {
        "user_id": "2",
        "user_login": "bob",
        "user_name": "Bob",
        "viewer_count": 77,
        "game_name": "Games",
        "thumbnail_url": "https://example.invalid/{width}x{height}.jpg",
    }
    result = providers.normalize_twitch_search_result(item)
    assert result == {
        "platform": "twitch",
        "id": "2",
        "login": "bob",
        "display_name": "Bob",
        "is_live": True,
        "viewer_count": 77,
        "game_name": "Games",
        "thumbnail_url": "https://example.invalid/320x180.jpg",
    }


def test_normalize_twitch_search_result_defensive_on_missing_fields():
    result = providers.normalize_twitch_search_result({})
    assert result == {
        "platform": "twitch",
        "id": "",
        "login": "",
        "display_name": "Unknown",
        "is_live": False,
        "viewer_count": 0,
        "game_name": "",
        "thumbnail_url": "",
    }


def test_get_kick_search_results_returns_empty_list_when_no_kick_token():
    addon = xbmcaddon.Addon()
    assert providers.get_kick_search_results(addon, "query") == []


def test_get_kick_search_results_normalizes_results():
    addon = xbmcaddon.Addon()
    addon.setSetting("kick_token", '{"access_token": "tok"}')

    def fake_search(access_token, query, first=20):
        assert access_token == "tok"
        assert query == "somequery"
        return [{"slug": "somechannel"}]

    result = providers.get_kick_search_results(addon, "somequery", search_channels_fn=fake_search)
    assert result == [
        {
            "platform": "kick",
            "id": "",
            "login": "somechannel",
            "display_name": "somechannel",
            "is_live": False,
            "viewer_count": 0,
            "game_name": "",
            "thumbnail_url": "",
        }
    ]


def test_get_kick_search_results_returns_empty_list_on_error():
    addon = xbmcaddon.Addon()
    addon.setSetting("kick_token", '{"access_token": "tok"}')

    def failing(access_token, query, first=20):
        raise Exception("boom")

    result = providers.get_kick_search_results(addon, "q", search_channels_fn=failing)
    assert result == []
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest tests/test_providers.py -v -k "normalize_twitch_search_result or kick_search_results"`
Expected: FAIL with `AttributeError` for each missing function

- [ ] **Step 3: Implement**

```python
# add to lib/providers.py
from lib.kick.api import search_channels as _kick_search_channels


def normalize_twitch_search_result(item):
    """Convert one raw dict from lib.twitch.gql.search() - which returns a
    mix of Twitch's search/channels shape (broadcaster_login, display_name,
    is_live, no viewer_count) and search/streams shape (user_login,
    user_name, viewer_count, always live) - into the shared normalized dict.
    Mirrors the .get() fallback chain lib/views/search_view.py's
    _render_results/play_selected already use for display/login, extended to
    the full normalized shape."""
    display_name = item.get("display_name") or item.get("user_name") or "Unknown"
    login = item.get("broadcaster_login") or item.get("user_login") or item.get("login") or ""
    viewer_count = item.get("viewer_count", 0)
    return {
        "platform": "twitch",
        "id": item.get("id") or item.get("user_id") or "",
        "login": login,
        "display_name": display_name,
        "is_live": bool(item.get("is_live", False)) or "viewer_count" in item,
        "viewer_count": viewer_count,
        "game_name": item.get("game_name", ""),
        "thumbnail_url": _twitch_thumbnail_url(item["thumbnail_url"]) if item.get("thumbnail_url") else "",
    }


def get_kick_search_results(addon, query, search_channels_fn=None):
    """Return normalized Kick search results, or [] if there's no saved Kick
    token or the call fails - never raises. Kick's search endpoint has no
    anonymous/app-token path (see this feature's design spec), so a
    logged-out-of-Kick user's searches simply never surface Kick results,
    with no error shown - this is the documented, accepted asymmetry with
    Twitch search (which needs no login at all)."""
    if search_channels_fn is None:
        search_channels_fn = _kick_search_channels
    token = kick_auth.load_token(addon)
    if token is None:
        return []
    try:
        entries = search_channels_fn(token["access_token"], query)
    except Exception:
        return []
    results = []
    for entry in entries:
        slug = entry.get("slug", "")
        results.append(
            {
                "platform": "kick",
                "id": str(entry["broadcaster_user_id"]) if entry.get("broadcaster_user_id") else "",
                "login": slug,
                "display_name": slug,
                "is_live": bool(entry.get("is_live", False)),
                "viewer_count": entry.get("viewer_count", 0),
                "game_name": entry.get("game_name", ""),
                "thumbnail_url": entry.get("thumbnail_url", ""),
            }
        )
    return results
```

- [ ] **Step 4: Run to verify it passes**

Run: `pytest tests/test_providers.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add lib/providers.py tests/test_providers.py
git commit -m "feat: add search normalization and Kick search to providers"
```

---

### Task 5: Provider-aware stream URL resolution

**Files:**
- Modify: `lib/providers.py`
- Modify: `tests/test_providers.py`

**Interfaces:**
- Consumes: `lib.twitch.stream.resolve_stream_url`, `lib.kick.stream.resolve_stream_url`, `lib.kick.auth.load_token`.
- Produces: `providers.StreamUnavailableError`, `providers.resolve_stream_url(addon, platform, identifier) -> str`.

- [ ] **Step 1: Write the failing tests**

```python
# append to tests/test_providers.py
import pytest

from lib.kick import stream as kick_stream
from lib.twitch import stream as twitch_stream


def test_resolve_stream_url_dispatches_to_twitch():
    addon = xbmcaddon.Addon()
    addon.setSetting("website_token", "webtok")
    with patch.object(twitch_stream, "resolve_stream_url", return_value="https://twitch.example/x.m3u8") as mock:
        url = providers.resolve_stream_url(addon, "twitch", "somechannel")
    mock.assert_called_once_with("somechannel", "webtok")
    assert url == "https://twitch.example/x.m3u8"


def test_resolve_stream_url_wraps_twitch_unavailable_error():
    addon = xbmcaddon.Addon()
    with patch.object(twitch_stream, "resolve_stream_url", side_effect=twitch_stream.StreamUnavailableError("x")):
        with pytest.raises(providers.StreamUnavailableError):
            providers.resolve_stream_url(addon, "twitch", "somechannel")


def test_resolve_stream_url_dispatches_to_kick():
    addon = xbmcaddon.Addon()
    addon.setSetting("kick_token", '{"access_token": "tok"}')
    with patch.object(kick_stream, "resolve_stream_url", return_value="https://kick.example/x.m3u8") as mock:
        url = providers.resolve_stream_url(addon, "kick", "somechannel")
    mock.assert_called_once_with("tok", "somechannel")
    assert url == "https://kick.example/x.m3u8"


def test_resolve_stream_url_wraps_kick_unavailable_error():
    addon = xbmcaddon.Addon()
    addon.setSetting("kick_token", '{"access_token": "tok"}')
    with patch.object(kick_stream, "resolve_stream_url", side_effect=kick_stream.StreamUnavailableError("x")):
        with pytest.raises(providers.StreamUnavailableError):
            providers.resolve_stream_url(addon, "kick", "somechannel")


def test_resolve_stream_url_raises_for_kick_when_not_logged_in():
    addon = xbmcaddon.Addon()  # no kick_token
    with pytest.raises(providers.StreamUnavailableError):
        providers.resolve_stream_url(addon, "kick", "somechannel")


def test_resolve_stream_url_raises_for_unknown_platform():
    addon = xbmcaddon.Addon()
    with pytest.raises(providers.StreamUnavailableError):
        providers.resolve_stream_url(addon, "nonsense", "somechannel")
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest tests/test_providers.py -v -k resolve_stream_url`
Expected: FAIL with `AttributeError: module 'lib.providers' has no attribute 'StreamUnavailableError'`

- [ ] **Step 3: Implement**

```python
# add to lib/providers.py
from lib.kick import stream as kick_stream
from lib.twitch import stream as twitch_stream


class StreamUnavailableError(Exception):
    """Raised when a channel (either platform) can't be resolved to a
    playable URL - wraps lib.twitch.stream.StreamUnavailableError and
    lib.kick.stream.StreamUnavailableError so callers catch one exception
    type regardless of platform."""


def resolve_stream_url(addon, platform, identifier):
    """Resolve `identifier` (a Twitch login or Kick slug) to a playable HLS
    URL for the given platform. Raises StreamUnavailableError - never the
    underlying per-platform exception - on any failure, including "not
    logged into Kick" (unlike listing, an explicit play action needs a
    definite error, not a silent empty result)."""
    if platform == "twitch":
        website_token = addon.getSetting("website_token")
        try:
            return twitch_stream.resolve_stream_url(identifier, website_token)
        except twitch_stream.StreamUnavailableError as exc:
            raise StreamUnavailableError(str(exc)) from exc
    if platform == "kick":
        token = kick_auth.load_token(addon)
        if token is None:
            raise StreamUnavailableError("not logged into Kick")
        try:
            return kick_stream.resolve_stream_url(token["access_token"], identifier)
        except kick_stream.StreamUnavailableError as exc:
            raise StreamUnavailableError(str(exc)) from exc
    raise StreamUnavailableError("unknown platform: " + repr(platform))
```

- [ ] **Step 4: Run to verify it passes**

Run: `pytest tests/test_providers.py -v`
Expected: PASS (every test in the file)

- [ ] **Step 5: Run the architecture boundary test**

Run: `pytest tests/test_architecture.py -v`
Expected: PASS — `lib/providers.py` isn't in `PROVIDER_DIRS` (it's not a provider package itself, it's the dispatch layer above both), so this should already pass untouched. If you find yourself wanting to add an `xbmc*` import to `lib/providers.py` anywhere in this task, stop - that import belongs in a view instead.

- [ ] **Step 6: Commit**

```bash
git add lib/providers.py tests/test_providers.py
git commit -m "feat: add provider-aware stream URL resolution"
```

---

### Task 6: `KickLoginView` + skin group + `MainWindow` wiring

**Files:**
- Create: `lib/views/kick_login_view.py`
- Create: `tests/views/test_kick_login_view.py`
- Modify: `resources/skins/Default/1080i/script-twitch-center-main.xml`
- Modify: `lib/windows/main_window.py`
- Modify: `tests/windows/test_main_window.py`

**Interfaces:**
- Consumes: `lib.kick.auth.run_pkce_login(client_id, client_secret, redirect_port, addon, on_code, on_status, cancel_event, scopes=None, ...)` (already exists), `lib.kick.auth.SCOPES`.
- Produces: `KickLoginView` with `URL_LABEL_ID`, `STATUS_LABEL_ID`, `CANCEL_BUTTON_ID`, `DEFAULT_FOCUS_ID` class attributes, `activate()`, `handle_action()`, `handle_click()`, `stop()`. Registers as `MainWindow.GROUP_IDS["kick_login"] = 600` and in `_default_view_classes()`.

**Note on the id block used here:** control ids `600`-`603` and skin group `600` are chosen to follow the existing convention (group N houses controls N+1..N+K — see Menu's 500/501-505, Login's 100/101-104). Confirm these are still free before implementing (`grep -n 'id="6' resources/skins/Default/1080i/script-twitch-center-main.xml`) — if a later, unrelated change already claimed them, shift this whole block to the next free hundred and note the substitution in your commit message, same precedent as provider-core's Task 9.

- [ ] **Step 1: Add the skin group**

In `resources/skins/Default/1080i/script-twitch-center-main.xml`, insert a new group after the closing `</control>` of the MENU (500) group and before the `<!-- ===================== LIVE STREAMS (200) ===================== -->` comment:

```xml
    <!-- ===================== KICK LOGIN (600) ===================== -->
    <control type="group" id="600">
      <control type="label">
        <description>Title</description>
        <posx>560</posx>
        <posy>200</posy>
        <width>800</width>
        <height>50</height>
        <font>font32</font>
        <align>center</align>
        <label>Log in to Kick</label>
      </control>
      <control type="label">
        <description>Instructions</description>
        <posx>560</posx>
        <posy>280</posy>
        <width>800</width>
        <height>60</height>
        <font>font13</font>
        <align>center</align>
        <label>Open this URL on your phone or PC (same network as this device):</label>
      </control>
      <control type="label" id="601">
        <description>Authorize URL</description>
        <posx>560</posx>
        <posy>360</posy>
        <width>800</width>
        <height>100</height>
        <font>font13</font>
        <align>center</align>
        <aligny>center</aligny>
        <label></label>
      </control>
      <control type="label" id="602">
        <description>Status</description>
        <posx>560</posx>
        <posy>560</posy>
        <width>800</width>
        <height>40</height>
        <font>font13</font>
        <align>center</align>
        <label></label>
      </control>
      <control type="button" id="603">
        <description>Cancel</description>
        <posx>760</posx>
        <posy>640</posy>
        <width>400</width>
        <height>60</height>
        <font>font13</font>
        <align>center</align>
        <label>Cancel</label>
        <onclick>PreviousMenu</onclick>
      </control>
    </control>

    <!-- ===================== LIVE STREAMS (200) ===================== -->
```

- [ ] **Step 2: Write the failing tests**

```python
# tests/views/test_kick_login_view.py
import threading
from unittest.mock import MagicMock, patch

import xbmcgui

from lib.views.kick_login_view import KickLoginView


class FakeWindow:
    def __init__(self):
        self._controls = {}

    def getControl(self, control_id):
        from xbmcgui import FakeListControl

        if control_id not in self._controls:
            self._controls[control_id] = FakeListControl()
        return self._controls[control_id]


def test_on_code_sets_url_label():
    win = KickLoginView(FakeWindow(), closed_event=threading.Event())
    win._cancel_event = threading.Event()
    win._on_code(win._cancel_event, "https://id.kick.com/oauth/authorize?client_id=x")
    assert win.window.getControl(KickLoginView.URL_LABEL_ID).getLabel() == (
        "https://id.kick.com/oauth/authorize?client_id=x"
    )


def test_on_status_sets_status_label_text():
    win = KickLoginView(FakeWindow(), closed_event=threading.Event())
    win._cancel_event = threading.Event()
    win._on_status(win._cancel_event, "pending")
    assert win.window.getControl(KickLoginView.STATUS_LABEL_ID).getLabel() == "Waiting for authorization..."


def test_on_status_denied_sets_status_label_text():
    win = KickLoginView(FakeWindow(), closed_event=threading.Event())
    win._cancel_event = threading.Event()
    win._on_status(win._cancel_event, "denied")
    assert win.window.getControl(KickLoginView.STATUS_LABEL_ID).getLabel() == (
        "Access denied. Reopen this screen to try again."
    )


def test_on_status_success_sets_login_succeeded_flag():
    win = KickLoginView(FakeWindow(), closed_event=threading.Event())
    win._cancel_event = threading.Event()
    win._on_status(win._cancel_event, "success")
    assert win.login_succeeded is True


def test_on_code_does_nothing_when_cancelled():
    win = KickLoginView(FakeWindow(), closed_event=threading.Event())
    win._cancel_event = threading.Event()
    win._cancel_event.set()
    win._on_code(win._cancel_event, "https://id.kick.com/oauth/authorize?client_id=x")
    assert win.window.getControl(KickLoginView.URL_LABEL_ID).getLabel() == ""


def test_on_status_does_nothing_when_cancelled():
    win = KickLoginView(FakeWindow(), closed_event=threading.Event())
    win._cancel_event = threading.Event()
    win._cancel_event.set()
    win._on_status(win._cancel_event, "success")
    assert win.login_succeeded is False
    assert win.window.getControl(KickLoginView.STATUS_LABEL_ID).getLabel() == ""


def test_activate_starts_background_thread_with_run_pkce_login():
    import xbmcaddon

    from lib.kick import auth

    addon = xbmcaddon.Addon()
    addon.setSetting("kick_client_id", "cid")
    addon.setSetting("kick_client_secret", "csecret")
    addon.setSetting("kick_redirect_port", "8919")

    with patch("lib.views.kick_login_view.xbmcaddon.Addon", return_value=addon), patch(
        "lib.views.kick_login_view.threading.Thread"
    ) as mock_thread_cls:
        win = KickLoginView(FakeWindow(), closed_event=threading.Event())
        win.activate()

    mock_thread_cls.assert_called_once()
    call_kwargs = mock_thread_cls.call_args.kwargs
    assert call_kwargs["target"] is auth.run_pkce_login
    assert call_kwargs["kwargs"]["client_id"] == "cid"
    assert call_kwargs["kwargs"]["client_secret"] == "csecret"
    assert call_kwargs["kwargs"]["redirect_port"] == 8919
    assert call_kwargs["kwargs"]["scopes"] == auth.SCOPES
    mock_thread_cls.return_value.start.assert_called_once()


def test_activate_is_idempotent_when_thread_already_running():
    with patch("lib.views.kick_login_view.threading.Thread") as mock_thread_cls:
        mock_thread_cls.return_value.is_alive.return_value = True
        win = KickLoginView(FakeWindow(), closed_event=threading.Event())
        win.activate()
        win.activate()
    mock_thread_cls.assert_called_once()


def test_activate_starts_a_fresh_login_flow_on_a_second_visit():
    with patch("lib.views.kick_login_view.threading.Thread") as mock_thread_cls:
        first_thread = MagicMock()
        first_thread.is_alive.return_value = True
        second_thread = MagicMock()
        mock_thread_cls.side_effect = [first_thread, second_thread]

        win = KickLoginView(FakeWindow(), closed_event=threading.Event())
        win.activate()
        win._on_status(win._cancel_event, "success")
        assert win.login_succeeded is True

        win.stop()
        win.activate()

    assert mock_thread_cls.call_count == 2
    second_thread.start.assert_called_once()
    assert win.login_succeeded is False
    assert not win._cancel_event.is_set()


def test_activate_does_not_restart_after_success_even_if_reactivated():
    win = KickLoginView(FakeWindow(), closed_event=threading.Event())
    win._cancel_event = threading.Event()
    win._on_status(win._cancel_event, "success")

    with patch("lib.views.kick_login_view.threading.Thread") as mock_thread_cls:
        win.activate()
    mock_thread_cls.assert_not_called()


def test_on_action_and_click_are_no_ops():
    win = KickLoginView(FakeWindow(), closed_event=threading.Event())
    win._cancel_event = threading.Event()
    win.handle_action(xbmcgui.Action(xbmcgui.ACTION_NAV_BACK))
    win.handle_click(KickLoginView.CANCEL_BUTTON_ID)
    # Neither raises, and stop() (which would set the cancel event) is never
    # implicitly called by either - Back/Cancel are handled by the skin's
    # <onclick>PreviousMenu</onclick> and MainWindow's central Back handling,
    # same as LoginView's CANCEL_BUTTON_ID.
    assert not win._cancel_event.is_set()
```

- [ ] **Step 3: Run to verify it fails**

Run: `pytest tests/views/test_kick_login_view.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'lib.views.kick_login_view'`

- [ ] **Step 4: Implement `KickLoginView`**

```python
# lib/views/kick_login_view.py
"""Kick login view: PKCE flow, displays the authorize URL to open on another
device, waits for the loopback callback. Not a Window subclass - see
MainWindow. Mirrors lib/views/login_view.py's shape (fresh flow per visit,
stale-callback guarding via a per-flow cancel_event) but drives
kick.auth.run_pkce_login instead of twitch.auth.run_device_code_login - see
that module's docstring for how the two callback contracts differ."""
import functools
import threading

import xbmc
import xbmcaddon

from lib.kick import auth

STATUS_MESSAGES = {
    "pending": "Waiting for authorization...",
    "expired": "Timed out waiting for authorization. Reopen this screen to try again.",
    "denied": "Access denied. Reopen this screen to try again.",
    "success": "Logged in!",
    "error": "Connection error. Reopen this screen to try again.",
}


class KickLoginView:
    URL_LABEL_ID = 601
    STATUS_LABEL_ID = 602
    CANCEL_BUTTON_ID = 603
    DEFAULT_FOCUS_ID = CANCEL_BUTTON_ID

    def __init__(self, window, closed_event=None):
        self.window = window
        self.closed_event = closed_event
        self._cancel_event = threading.Event()
        self._thread = None
        self.login_succeeded = False

    def stop(self):
        self._cancel_event.set()

    def activate(self):
        # Same reasoning as LoginView.activate(): a set cancel_event means
        # "the previous visit is over" (MainWindow calls stop() on navigating
        # away), so the guards below only exist to absorb Kodi re-firing
        # onInit/activation WITHIN the current visit, not across visits.
        resuming_after_stop = self._cancel_event.is_set()
        if not resuming_after_stop:
            if self.login_succeeded:
                return
            if self._thread is not None and self._thread.is_alive():
                return
        self.login_succeeded = False
        self._cancel_event = threading.Event()
        cancel_event = self._cancel_event
        on_code = functools.partial(self._on_code, cancel_event)
        on_status = functools.partial(self._on_status, cancel_event)

        addon = xbmcaddon.Addon()
        client_id = addon.getSetting("kick_client_id")
        client_secret = addon.getSetting("kick_client_secret")
        redirect_port = int(addon.getSetting("kick_redirect_port"))
        thread = threading.Thread(
            target=auth.run_pkce_login,
            kwargs={
                "client_id": client_id,
                "client_secret": client_secret,
                "redirect_port": redirect_port,
                "addon": addon,
                "on_code": on_code,
                "on_status": on_status,
                "cancel_event": cancel_event,
                "scopes": auth.SCOPES,
            },
        )
        thread.daemon = True
        thread.start()
        self._thread = thread

    def _on_code(self, cancel_event, url):
        if cancel_event.is_set():
            return
        self.window.getControl(self.URL_LABEL_ID).setLabel(url)

    def _on_status(self, cancel_event, status):
        if cancel_event.is_set():
            return
        if status == "error":
            xbmc.log("script.twitch.center: Kick PKCE login reported an error", xbmc.LOGERROR)
        message = STATUS_MESSAGES.get(status, "")
        self.window.getControl(self.STATUS_LABEL_ID).setLabel(message)
        if status == "success":
            self.login_succeeded = True

    def handle_action(self, action):
        pass

    def handle_click(self, control_id):
        pass
```

- [ ] **Step 5: Run to verify it passes**

Run: `pytest tests/views/test_kick_login_view.py -v`
Expected: PASS

- [ ] **Step 6: Register the view in `MainWindow`**

In `lib/windows/main_window.py`, modify the `GROUP_IDS` dict:

```python
    GROUP_IDS = {
        "login": 100,
        "menu": 500,
        "live_streams": 200,
        "discover": 300,
        "search": 400,
        "kick_login": 600,
    }
```

And modify `_default_view_classes()`:

```python
    @staticmethod
    def _default_view_classes():
        from lib.views.discover_view import DiscoverView
        from lib.views.kick_login_view import KickLoginView
        from lib.views.live_streams_view import LiveStreamsView
        from lib.views.login_view import LoginView
        from lib.views.menu_view import MenuView
        from lib.views.search_view import SearchView

        return {
            "login": LoginView,
            "menu": MenuView,
            "live_streams": LiveStreamsView,
            "discover": DiscoverView,
            "search": SearchView,
            "kick_login": KickLoginView,
        }
```

- [ ] **Step 7: Extend `MainWindow` tests**

In `tests/windows/test_main_window.py`, modify `_make_window`'s default views dict to include `"kick_login"`:

```python
def _make_window(initial_view="menu", view_classes=None):
    views = {
        name: FakeView
        for name in ("login", "menu", "live_streams", "discover", "search", "kick_login")
    }
    views.update(view_classes or {})
    return MainWindow(
        "script-twitch-center-main.xml", "/tmp", initial_view=initial_view, view_classes=views
    )
```

Append a dedicated test:

```python
def test_switch_view_can_reach_kick_login():
    win = _make_window(initial_view="menu")
    win.onInit()
    win._switch_view("kick_login")
    assert win._active_name == "kick_login"
    assert win.getControl(win.GROUP_IDS["kick_login"]).isVisible() is True
    for name, group_id in win.GROUP_IDS.items():
        if name != "kick_login":
            assert win.getControl(group_id).isVisible() is False
```

- [ ] **Step 8: Run the full test file**

Run: `pytest tests/windows/test_main_window.py tests/views/test_kick_login_view.py -v`
Expected: PASS (every test)

- [ ] **Step 9: Confirm `settings.xml` is still well-formed**

Run: `python -c "import xml.dom.minidom; xml.dom.minidom.parse('resources/skins/Default/1080i/script-twitch-center-main.xml'); print('OK')"`
Expected: `OK`

- [ ] **Step 10: Commit**

```bash
git add lib/views/kick_login_view.py tests/views/test_kick_login_view.py \
  resources/skins/Default/1080i/script-twitch-center-main.xml \
  lib/windows/main_window.py tests/windows/test_main_window.py
git commit -m "feat: add KickLoginView (PKCE flow) and wire it into MainWindow"
```

---

### Task 7: "Log in to Kick" menu entry

**Files:**
- Modify: `resources/skins/Default/1080i/script-twitch-center-main.xml`
- Modify: `lib/views/menu_view.py`
- Modify: `tests/views/test_menu_view.py`

**Interfaces:**
- Consumes: `KickLoginView` (registered as `"kick_login"` view, Task 6).
- Produces: `MenuView.KICK_LOGIN_BUTTON_ID = 506`.

- [ ] **Step 1: Add the button to the skin**

In `resources/skins/Default/1080i/script-twitch-center-main.xml`'s MENU (500) group, change button `505`'s `<ondown>` from `501` to `506`:

```xml
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
        <label>Log in again</label>
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

And change button `501`'s `<onup>` from `505` to `506`:

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
        <ondown>502</ondown>
        <onup>506</onup>
        <label>Live Streams</label>
      </control>
```

- [ ] **Step 2: Write the failing tests**

Append to `tests/views/test_menu_view.py`:

```python
def test_selecting_kick_login_switches_to_kick_login_view_when_credentials_set():
    window = FakeMainWindow()
    addon = xbmcaddon.Addon()
    addon.setSetting("kick_client_id", "cid")
    addon.setSetting("kick_client_secret", "csecret")
    with patch("lib.views.menu_view.xbmcaddon.Addon", return_value=addon):
        _select(window, MenuView.KICK_LOGIN_BUTTON_ID)
    assert window.switched_to == ["kick_login"]


def test_selecting_kick_login_shows_a_dialog_when_client_id_missing():
    window = FakeMainWindow()
    addon = xbmcaddon.Addon()
    addon.setSetting("kick_client_secret", "csecret")  # client id left empty
    with patch("lib.views.menu_view.xbmcaddon.Addon", return_value=addon), patch(
        "lib.views.menu_view.xbmcgui.Dialog"
    ) as mock_dialog_cls:
        _select(window, MenuView.KICK_LOGIN_BUTTON_ID)
    mock_dialog_cls.return_value.ok.assert_called_once()
    assert window.switched_to == []


def test_selecting_kick_login_shows_a_dialog_when_client_secret_missing():
    window = FakeMainWindow()
    addon = xbmcaddon.Addon()
    addon.setSetting("kick_client_id", "cid")  # secret left empty
    with patch("lib.views.menu_view.xbmcaddon.Addon", return_value=addon), patch(
        "lib.views.menu_view.xbmcgui.Dialog"
    ) as mock_dialog_cls:
        _select(window, MenuView.KICK_LOGIN_BUTTON_ID)
    mock_dialog_cls.return_value.ok.assert_called_once()
    assert window.switched_to == []
```

- [ ] **Step 3: Run to verify it fails**

Run: `pytest tests/views/test_menu_view.py -v -k kick_login`
Expected: FAIL with `AttributeError: type object 'MenuView' has no attribute 'KICK_LOGIN_BUTTON_ID'`

- [ ] **Step 4: Implement**

Replace `lib/views/menu_view.py` in full:

```python
"""Menu view: the landing screen after Login - Live Streams / Discover /
Search / Settings / Log in again / Log in to Kick. Not a Window subclass -
see MainWindow."""
import xbmcaddon
import xbmcgui


class MenuView:
    LIVE_STREAMS_BUTTON_ID = 501
    DISCOVER_BUTTON_ID = 502
    SEARCH_BUTTON_ID = 503
    SETTINGS_BUTTON_ID = 504
    RELOGIN_BUTTON_ID = 505
    KICK_LOGIN_BUTTON_ID = 506
    # MainWindow focuses this when Menu becomes visible - the skin's own
    # <defaultcontrol> only fires once, on the very first window activation.
    DEFAULT_FOCUS_ID = LIVE_STREAMS_BUTTON_ID

    def __init__(self, window, closed_event=None):
        self.window = window
        self.closed_event = closed_event

    def activate(self):
        pass

    def handle_action(self, action):
        if action.getId() != xbmcgui.ACTION_SELECT_ITEM:
            return
        focus = self.window.getFocusId()
        if focus == self.LIVE_STREAMS_BUTTON_ID:
            self.window._switch_view("live_streams")
        elif focus == self.DISCOVER_BUTTON_ID:
            self.window._switch_view("discover")
        elif focus == self.SEARCH_BUTTON_ID:
            self.window._switch_view("search")
        elif focus == self.SETTINGS_BUTTON_ID:
            xbmcaddon.Addon().openSettings()
        elif focus == self.RELOGIN_BUTTON_ID:
            self.window._switch_view("login")
        elif focus == self.KICK_LOGIN_BUTTON_ID:
            self._select_kick_login()

    def _select_kick_login(self):
        addon = xbmcaddon.Addon()
        if not addon.getSetting("kick_client_id") or not addon.getSetting("kick_client_secret"):
            xbmcgui.Dialog().ok(
                "Kick", "Set Kick Client ID and Client Secret in Settings first."
            )
            return
        self.window._switch_view("kick_login")

    def handle_click(self, control_id):
        pass
```

- [ ] **Step 5: Run to verify it passes**

Run: `pytest tests/views/test_menu_view.py -v`
Expected: PASS (every test in the file)

- [ ] **Step 6: Confirm the skin is still well-formed and ids stay unique**

Run: `python -c "import xml.dom.minidom; xml.dom.minidom.parse('resources/skins/Default/1080i/script-twitch-center-main.xml'); print('OK')"`
Run: `pytest tests/test_addon_manifest.py -v -k control_ids_are_unique`
Expected: both PASS

- [ ] **Step 7: Commit**

```bash
git add resources/skins/Default/1080i/script-twitch-center-main.xml lib/views/menu_view.py tests/views/test_menu_view.py
git commit -m "feat: add Log in to Kick menu entry, gated on Kick credentials being set"
```

---

### Task 8: `player.py` platform-aware playback

**Files:**
- Modify: `lib/windows/player.py`
- Modify: `tests/windows/test_player.py`

**Interfaces:**
- Consumes: `providers.resolve_stream_url(addon, platform, identifier)`, `providers.StreamUnavailableError` (Task 5).
- Produces: `play_stream(url, channel, settings=None, access_token=None, client_id=None, user_id=None, chat_overlay_cls=None, chat_client_cls=None, platform="twitch")`. `RecoveryManager(player, channel, platform="twitch")` (was `RecoveryManager(player, channel, website_token=None)`). `_ChatAwarePlayer(overlay, url=None, channel=None, platform="twitch", enable_watchdog=True)` (was `..., website_token=None, ...`).

**Incidental fix, not in scope to investigate further:** `RecoveryManager` currently gets its `website_token` from `_website_token_from_settings(settings)`, which reads `getattr(settings, "website_token", None)` — but `lib/settings.py`'s `Settings` class has no `website_token` property, so this has always evaluated to `None` in real usage (the real Twitch website token, read correctly everywhere else in this codebase via `addon.getSetting("website_token")` directly, never reached stall-recovery). Routing recovery through `providers.resolve_stream_url`, which reads `addon.getSetting("website_token")` directly, fixes this as a side effect. Do not expand this task to "investigate the settings/website_token property gap" — out of scope here, just note it in the commit message.

- [ ] **Step 1: Write the failing tests**

Replace the recovery-related tests in `tests/windows/test_player.py`. Find and replace `test_recovery_manager_resolves_fresh_url_and_restarts_player` and `test_recovery_manager_is_noop_when_already_recovering`:

```python
def test_recovery_manager_resolves_fresh_url_and_restarts_player():
    with patch.object(
        providers, "resolve_stream_url", return_value="https://fresh.url/stream.m3u8"
    ) as mock_resolve, patch("lib.windows.player.Helper") as mock_helper_cls:
        mock_helper_cls.return_value.check_inputstream.return_value = True
        mock_helper_cls.return_value.inputstream_addon = "inputstream.adaptive"

        fake_player = FakePlayerForRecovery()
        recovery = player.RecoveryManager(fake_player, "somechannel")
        recovery.recover()

    mock_resolve.assert_called_once()
    call_args = mock_resolve.call_args
    assert call_args.args[1] == "twitch"
    assert call_args.args[2] == "somechannel"
    assert len(fake_player.played) == 1
    assert fake_player.played[0][0] == "https://fresh.url/stream.m3u8"
    assert fake_player.played[0][1] == "https://fresh.url/stream.m3u8"


def test_recovery_manager_resolves_via_kick_when_platform_is_kick():
    with patch.object(
        providers, "resolve_stream_url", return_value="https://kick.example/stream.m3u8"
    ) as mock_resolve, patch("lib.windows.player.Helper") as mock_helper_cls:
        mock_helper_cls.return_value.check_inputstream.return_value = True
        mock_helper_cls.return_value.inputstream_addon = "inputstream.adaptive"

        fake_player = FakePlayerForRecovery()
        recovery = player.RecoveryManager(fake_player, "somechannel", platform="kick")
        recovery.recover()

    call_args = mock_resolve.call_args
    assert call_args.args[1] == "kick"
    assert call_args.args[2] == "somechannel"


def test_recovery_manager_logs_and_aborts_on_stream_unavailable():
    with patch.object(
        providers, "resolve_stream_url", side_effect=providers.StreamUnavailableError("x")
    ), patch("lib.windows.player.Helper") as mock_helper_cls, patch(
        "lib.windows.player.xbmc.log"
    ) as mock_log:
        fake_player = FakePlayerForRecovery()
        recovery = player.RecoveryManager(fake_player, "somechannel")
        recovery.recover()

    mock_log.assert_called_once()
    assert fake_player.played == []


def test_recovery_manager_is_noop_when_already_recovering():
    with patch.object(providers, "resolve_stream_url") as mock_resolve, patch(
        "lib.windows.player.Helper"
    ) as mock_helper_cls:
        mock_helper_cls.return_value.check_inputstream.return_value = True

        fake_player = FakePlayerForRecovery()
        recovery = player.RecoveryManager(fake_player, "somechannel")

        # Hold the lock to simulate a concurrent recovery in progress.
        with recovery._lock:
            recovery.recover()

        mock_resolve.assert_not_called()
```

Add `from lib import providers` to the test file's imports (alongside the existing `from lib.twitch import eventsub as eventsub_module` etc. block) and remove the now-unused `from lib.twitch import stream` import if nothing else in the file references `stream` directly (check with `grep -n "\bstream\." tests/windows/test_player.py` first — if any other test still uses it, leave the import in place).

Append new platform-dispatch tests for `play_stream` itself:

```python
def test_play_stream_skips_chat_overlay_entirely_for_kick_platform():
    FakeChatOverlay.instances.clear()
    with patch("lib.windows.player.Helper") as mock_helper_cls, patch(
        "lib.windows.player.xbmc.Player"
    ) as mock_player_cls, patch("lib.windows.player.PlaybackWatchdog", FakeWatchdog):
        mock_helper_cls.return_value.check_inputstream.return_value = True
        mock_helper_cls.return_value.inputstream_addon = "inputstream.adaptive"

        result = player.play_stream(
            "https://example.invalid/kickstream.m3u8",
            "somekickchannel",
            settings=FakeSettings(True),  # chat_overlay_enabled=True - must still be ignored
            platform="kick",
            chat_overlay_cls=FakeChatOverlay,
            chat_client_cls=FakeChatClient,
        )

    assert result is True
    assert len(FakeChatOverlay.instances) == 0
    mock_player_cls.return_value.play.assert_called_once_with(
        "https://example.invalid/kickstream.m3u8", ANY
    )


def test_play_stream_defaults_to_twitch_platform_when_unspecified():
    FakeChatOverlay.instances.clear()
    with patch("lib.windows.player.Helper") as mock_helper_cls, patch(
        "lib.windows.player.xbmc.Player"
    ) as mock_player_cls, patch("lib.windows.player.PlaybackWatchdog", FakeWatchdog):
        mock_helper_cls.return_value.check_inputstream.return_value = True
        mock_helper_cls.return_value.inputstream_addon = "inputstream.adaptive"

        player.play_stream(
            "https://example.invalid/stream.m3u8",
            "somechannel",
            settings=FakeSettings(True),
            chat_overlay_cls=FakeChatOverlay,
            chat_client_cls=FakeChatClient,
        )

    assert len(FakeChatOverlay.instances) == 1
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest tests/windows/test_player.py -v -k "recovery_manager or platform"`
Expected: FAIL — `mock_resolve.call_args` shape mismatch (still calling `stream.resolve_stream_url(channel, website_token)` positionally) and `AttributeError`/`TypeError: play_stream() got an unexpected keyword argument 'platform'`

- [ ] **Step 3: Implement**

Modify `lib/windows/player.py`'s imports — remove `from lib.twitch import stream` (no longer used anywhere in this file after this task) and add:

```python
from lib import providers
```

Replace `RecoveryManager` in full:

```python
class RecoveryManager:
    """Refreshes the stream URL (via the correct platform's resolver) and
    restarts Kodi playback."""

    def __init__(self, player, channel, platform="twitch"):
        self._player = player
        self._channel = channel
        self._platform = platform
        self._lock = threading.Lock()

    def recover(self):
        if not self._lock.acquire(blocking=False):
            return
        try:
            addon = xbmcaddon.Addon()
            try:
                new_url = providers.resolve_stream_url(addon, self._platform, self._channel)
            except providers.StreamUnavailableError as exc:
                xbmc.log(
                    "script.twitch.center: recovery cannot resolve stream: " + repr(exc),
                    xbmc.LOGERROR,
                )
                return

            is_helper = Helper("hls")
            if not is_helper.check_inputstream():
                xbmc.log(
                    "script.twitch.center: recovery aborted, inputstream.adaptive unavailable",
                    xbmc.LOGERROR,
                )
                return

            list_item = xbmcgui.ListItem(path=new_url)
            list_item.setProperty("inputstream", is_helper.inputstream_addon)
            list_item.setProperty("inputstream.adaptive.manifest_type", "hls")
            list_item.setMimeType("application/x-mpegURL")
            list_item.setContentLookup(False)
            self._player.play(new_url, list_item)
            xbmc.log(
                "script.twitch.center: restarted playback with fresh stream URL",
                xbmc.LOGINFO,
            )
        finally:
            self._lock.release()
```

Modify `_ChatAwarePlayer.__init__` (change `website_token=None` to `platform="twitch"`, drop `self._website_token`, and pass `platform` to `RecoveryManager`):

```python
    def __init__(self, overlay, url=None, channel=None, platform="twitch", enable_watchdog=True):
        super().__init__()
        self._overlay = overlay
        self._url = url
        self._channel = channel
        self._paused = False
        self._ad_state = AdBreakState()
        self._recovery = RecoveryManager(self, channel, platform)
        self._watchdog = PlaybackWatchdog(
            self, self._ad_state, self._recovery, is_paused_fn=lambda: self._paused
        )
        if enable_watchdog:
            self._watchdog.start()
```

Delete the now-unused `_website_token_from_settings` function entirely.

Modify `play_stream`'s signature and its two `xbmc.Player().play(url, list_item)` / `_ChatAwarePlayer(...)` call sites:

```python
def play_stream(url, channel, settings=None, access_token=None, client_id=None, user_id=None,
                 chat_overlay_cls=None, chat_client_cls=None, platform="twitch"):
    """Hand the resolved HLS URL to Kodi's player via inputstream.adaptive,
    which handles proper adaptive-bitrate switching for live multi-quality
    HLS (unlike Kodi's native demuxer playing the URL directly). Returns
    True if playback was started, False if inputstream.adaptive isn't
    available and the user declined installing it (Helper.check_inputstream
    handles that install-prompt UI itself).

    If playback started, platform == "twitch", and chat_overlay_enabled is
    set, also creates and shows a ChatOverlay for `channel`, and keeps a
    _ChatAwarePlayer alive at module level so its onPlaybackStopped/
    onPlaybackEnded callbacks close the overlay and disconnect its chat
    client when this stream ends - a locally-scoped instance would be
    garbage-collected and stop receiving Kodi's callbacks. platform=="kick"
    always skips chat entirely, regardless of chat_overlay_enabled - there
    is no Kick chat client yet.

    access_token/client_id/user_id are the logged-in Twitch user's Helix
    credentials - required only when settings.chat_engine == "eventsub"
    (to resolve the channel's numeric id and subscribe); ignored for the
    default "irc" engine and always ignored for platform=="kick"."""
    global _current_chat_watcher

    is_helper = Helper("hls")
    if not is_helper.check_inputstream():
        return False

    list_item = xbmcgui.ListItem(path=url)
    list_item.setProperty("inputstream", is_helper.inputstream_addon)
    list_item.setProperty("inputstream.adaptive.manifest_type", "hls")
    list_item.setMimeType("application/x-mpegURL")
    list_item.setContentLookup(False)

    settings = settings or Settings()
    if platform == "twitch" and settings.chat_overlay_enabled:
        try:
            if _current_chat_watcher is not None:
                _current_chat_watcher._teardown()
                _current_chat_watcher = None

            engine = settings.chat_engine
            broadcaster_user_id = None
            if chat_client_cls is None and engine == "eventsub":
                try:
                    user = api.get_user_by_login(access_token, client_id, channel)
                except Exception as exc:
                    xbmc.log(
                        "script.twitch.center: EventSub broadcaster-id lookup failed for "
                        "%r (%r), falling back to IRC" % (channel, repr(exc)),
                        xbmc.LOGWARNING,
                    )
                    user = None
                if user is None:
                    xbmc.log(
                        "script.twitch.center: EventSub chat engine could not resolve "
                        "broadcaster id for %r, falling back to IRC" % channel,
                        xbmc.LOGWARNING,
                    )
                    engine = "irc"
                else:
                    broadcaster_user_id = user["id"]

            resolved_chat_client_cls = chat_client_cls or _CHAT_CLIENT_CLS_BY_ENGINE.get(
                engine, irc.ChatClient
            )

            if chat_overlay_cls is not None:
                overlay_cls = chat_overlay_cls
            elif engine == "eventsub" and settings.chat_overlay_variable_height:
                overlay_cls = VariableChatOverlay
            else:
                overlay_cls = ChatOverlay
            overlay = overlay_cls(
                "script-twitch-center-chat-overlay.xml",
                xbmcaddon.Addon().getAddonInfo("path"),
                "Default",
                "1080i",
                channel=channel,
                access_token=access_token,
                client_id=client_id,
                broadcaster_user_id=broadcaster_user_id,
                user_id=user_id,
                chat_client_cls=resolved_chat_client_cls,
            )
            overlay.show()
            _current_chat_watcher = _ChatAwarePlayer(
                overlay, url=url, channel=channel, platform=platform
            )
            _current_chat_watcher.play(url, list_item)
        except Exception as exc:
            xbmc.log(
                "script.twitch.center: chat overlay failed to start: " + repr(exc),
                xbmc.LOGERROR,
            )
            xbmc.Player().play(url, list_item)
    else:
        xbmc.Player().play(url, list_item)

    return True
```

- [ ] **Step 4: Run to verify it passes**

Run: `pytest tests/windows/test_player.py -v`
Expected: PASS (every test in the file, including every pre-existing Twitch-path test — `platform` defaults to `"twitch"`, preserving current behavior for every call site not yet updated to pass it)

- [ ] **Step 5: Commit**

```bash
git add lib/windows/player.py tests/windows/test_player.py
git commit -m "feat: make play_stream and stall-recovery platform-aware, skip chat entirely for Kick"
```

---

### Task 9: `LiveStreamsView` — merge Kick favorites in, platform-aware playback

**Files:**
- Modify: `resources/skins/Default/1080i/script-twitch-center-main.xml`
- Modify: `lib/views/live_streams_view.py`
- Modify: `tests/views/test_live_streams_view.py`

**Interfaces:**
- Consumes: `providers.get_kick_live_favorites(addon)`, `providers.resolve_stream_url(addon, platform, identifier)`, `providers.StreamUnavailableError` (Tasks 2, 5), `player.play_stream(..., platform=...)` (Task 8).
- Produces: every rendered `ListItem` in `CHANNEL_LIST_ID` carries a `platform` (`"twitch"`/`"kick"`) property; live Twitch and Kick favorites are interleaved by viewer count; selecting a live item dispatches playback through the correct platform.

**Design choice, so you don't "simplify" it away:** this task does NOT route Twitch items through `providers.normalize_twitch_channel` before building their `ListItem`s. `_build_list_item(channel, stream_data)` and `_merge_channels(followed, live_list)` keep their exact existing two-value signatures and behavior untouched, because 2 existing tests (`test_build_list_item_live_sets_label2_and_thumbnail`, `test_build_list_item_live_sets_broadcaster_login_and_is_live_true`) call `_build_list_item` directly with that shape, and rewriting them isn't needed to achieve the goal. Instead, a new `_interleave_live_items` helper sorts the *already twitch-shaped* `(channel, stream_data)` tuples together with Kick's normalized dicts by comparing `viewer_count` directly, then dispatches each entry to the right item-builder. `_build_list_item` only gains one new line (tagging `platform="twitch"`) — purely additive, breaks nothing.

- [ ] **Step 1: Add the Kick platform badge to the skin**

In `resources/skins/Default/1080i/script-twitch-center-main.xml`, inside the `<control type="panel" id="201">` block, add a new label to the END of `<itemlayout width="415" height="275">` (right before its closing `</itemlayout>` tag, after the existing viewer-count label):

```xml
          <control type="label">
            <posx>16</posx>
            <posy>251</posy>
            <width>270</width>
            <height>20</height>
            <font>CardLabel</font>
            <textcolor>ff53fc18</textcolor>
            <visible>String.IsEqual(ListItem.Property(platform),kick)</visible>
            <label>KICK</label>
          </control>
```

(`53fc18` is Kick's brand green - a Twitch item never has `ListItem.Property(platform)` equal to `"kick"`, so this stays invisible for every Twitch card exactly as today; there's an unused 24px strip at the bottom of the 275px-tall card, below the existing game-name/viewer-count row, which this fits into without touching any other control's position.)

Add the identical block to the END of `<focusedlayout width="415" height="275">` (right before its closing `</focusedlayout>` tag) too, so the badge stays visible while a Kick card is focused.

Confirm the file is still well-formed after this edit: `python -c "import xml.dom.minidom; xml.dom.minidom.parse('resources/skins/Default/1080i/script-twitch-center-main.xml'); print('OK')"`.

- [ ] **Step 2: Write the failing tests**

Append to `tests/views/test_live_streams_view.py`:

```python
from lib import providers


KICK_LIVE_FAVORITE = {
    "platform": "kick",
    "id": "42",
    "login": "kickchannel",
    "display_name": "kickchannel",
    "is_live": True,
    "viewer_count": 120,
    "game_name": "Slots",
    "thumbnail_url": "https://example.invalid/kickthumb.jpg",
}


def test_oninit_merges_kick_favorites_into_the_channel_list():
    # Twitch live: Carol (200), Bob (50). Kick live favorite: 120 viewers.
    # Interleaved by viewer count: Carol (200), kickchannel (120), Bob (50).
    addon = _addon_with_token({"access_token": "tok", "refresh_token": "ref", "user_id": "u1"})
    with patch("xbmcaddon.Addon", return_value=addon), patch.object(
        api, "get_followed_channels", return_value=FOLLOWED
    ), patch.object(api, "get_live_status", return_value=LIVE), patch.object(
        gql, "get_followed_live_games", return_value=[]
    ), patch.object(
        providers, "get_kick_live_favorites", return_value=[KICK_LIVE_FAVORITE]
    ):
        win = LiveStreamsView(FakeWindow())
        win.activate()

    channel_control = win.window.getControl(LiveStreamsView.CHANNEL_LIST_ID)
    logins = [
        channel_control.getListItem(i).getProperty("broadcaster_login")
        for i in range(channel_control.size())
    ]
    platforms = [
        channel_control.getListItem(i).getProperty("platform")
        for i in range(channel_control.size())
    ]
    assert logins[:3] == ["carol", "kickchannel", "bob"]
    assert platforms[:3] == ["twitch", "kick", "twitch"]


def test_oninit_shows_kick_favorites_alone_when_no_twitch_channels_are_live():
    addon = _addon_with_token({"access_token": "tok", "refresh_token": "ref", "user_id": "u1"})
    with patch("xbmcaddon.Addon", return_value=addon), patch.object(
        api, "get_followed_channels", return_value=[]
    ), patch.object(api, "get_live_status", return_value=[]), patch.object(
        gql, "get_followed_live_games", return_value=[]
    ), patch.object(
        providers, "get_kick_live_favorites", return_value=[KICK_LIVE_FAVORITE]
    ):
        win = LiveStreamsView(FakeWindow())
        win.activate()

    channel_control = win.window.getControl(LiveStreamsView.CHANNEL_LIST_ID)
    assert channel_control.size() == 1
    assert channel_control.getListItem(0).getProperty("broadcaster_login") == "kickchannel"
    assert win.window.getControl(LiveStreamsView.EMPTY_LABEL_ID).getLabel() == ""


def test_oninit_shows_empty_message_when_no_twitch_followed_and_no_kick_favorites():
    addon = _addon_with_token({"access_token": "tok", "refresh_token": "ref", "user_id": "u1"})
    with patch("xbmcaddon.Addon", return_value=addon), patch.object(
        api, "get_followed_channels", return_value=[]
    ), patch.object(api, "get_live_status", return_value=[]), patch.object(
        gql, "get_followed_live_games", return_value=[]
    ), patch.object(providers, "get_kick_live_favorites", return_value=[]):
        win = LiveStreamsView(FakeWindow())
        win.activate()

    assert win.window.getControl(LiveStreamsView.EMPTY_LABEL_ID).getLabel() != ""


def test_selecting_a_game_filter_hides_kick_favorites():
    # The games filter is Twitch-only - Kick has no equivalent taxonomy, so
    # selecting a specific game hides Kick results rather than showing them
    # unfiltered alongside a filtered Twitch list (documented spec decision).
    addon = _addon_with_token({"access_token": "tok", "refresh_token": "ref", "user_id": "u1"})
    with patch("xbmcaddon.Addon", return_value=addon), patch.object(
        api, "get_followed_channels", return_value=FOLLOWED
    ), patch.object(api, "get_live_status", return_value=LIVE), patch.object(
        gql, "get_followed_live_games", return_value=GAMES
    ), patch.object(
        providers, "get_kick_live_favorites", return_value=[KICK_LIVE_FAVORITE]
    ):
        win = LiveStreamsView(FakeWindow())
        win.activate()
        games_control = win.window.getControl(LiveStreamsView.GAMES_LIST_ID)
        # GAMES[0]["displayName"] must be "Programming" (Carol's game) for
        # this assertion to isolate her alone - see GAMES' definition.
        for i in range(games_control.size()):
            if games_control.getListItem(i).getProperty("game_name") == "Programming":
                games_control.selectItem(i)
                break
        win.window.setFocusId(LiveStreamsView.GAMES_LIST_ID)
        win.handle_action(xbmcgui.Action(xbmcgui.ACTION_SELECT_ITEM))

    channel_control = win.window.getControl(LiveStreamsView.CHANNEL_LIST_ID)
    logins = [
        channel_control.getListItem(i).getProperty("broadcaster_login")
        for i in range(channel_control.size())
    ]
    assert "kickchannel" not in logins


def test_selecting_a_live_kick_channel_plays_it():
    addon = _addon_with_token({"access_token": "tok", "refresh_token": "ref", "user_id": "u1"})
    with patch("xbmcaddon.Addon", return_value=addon), patch.object(
        api, "get_followed_channels", return_value=[]
    ), patch.object(api, "get_live_status", return_value=[]), patch.object(
        gql, "get_followed_live_games", return_value=[]
    ), patch.object(
        providers, "get_kick_live_favorites", return_value=[KICK_LIVE_FAVORITE]
    ), patch.object(
        providers, "resolve_stream_url", return_value="https://kick.example/x.m3u8"
    ) as mock_resolve, patch(
        "lib.views.live_streams_view.player.play_stream", return_value=True
    ) as mock_play:
        win = LiveStreamsView(FakeWindow())
        win.activate()
        channel_control = win.window.getControl(LiveStreamsView.CHANNEL_LIST_ID)
        channel_control.selectItem(0)
        win.window.setFocusId(LiveStreamsView.CHANNEL_LIST_ID)
        win.handle_action(xbmcgui.Action(xbmcgui.ACTION_SELECT_ITEM))

    mock_resolve.assert_called_once()
    call_args = mock_resolve.call_args
    assert call_args.args[1] == "kick"
    assert call_args.args[2] == "kickchannel"
    mock_play.assert_called_once_with(
        "https://kick.example/x.m3u8", "kickchannel", platform="kick"
    )


def test_selecting_a_live_kick_channel_shows_error_when_resolution_fails():
    addon = _addon_with_token({"access_token": "tok", "refresh_token": "ref", "user_id": "u1"})
    with patch("xbmcaddon.Addon", return_value=addon), patch.object(
        api, "get_followed_channels", return_value=[]
    ), patch.object(api, "get_live_status", return_value=[]), patch.object(
        gql, "get_followed_live_games", return_value=[]
    ), patch.object(
        providers, "get_kick_live_favorites", return_value=[KICK_LIVE_FAVORITE]
    ), patch.object(
        providers, "resolve_stream_url", side_effect=providers.StreamUnavailableError("x")
    ):
        win = LiveStreamsView(FakeWindow())
        win.activate()
        channel_control = win.window.getControl(LiveStreamsView.CHANNEL_LIST_ID)
        channel_control.selectItem(0)
        win.window.setFocusId(LiveStreamsView.CHANNEL_LIST_ID)
        win.handle_action(xbmcgui.Action(xbmcgui.ACTION_SELECT_ITEM))

    assert win.window.getControl(LiveStreamsView.ERROR_LABEL_ID).getLabel() != ""
```

- [ ] **Step 3: Run to verify it fails**

Run: `pytest tests/views/test_live_streams_view.py -v -k "kick"`
Expected: FAIL — `providers.get_kick_live_favorites` never called (view doesn't know about it yet), `platform` property missing/wrong, `player.play_stream` called without `platform=`

- [ ] **Step 4: Implement**

Modify `lib/views/live_streams_view.py`'s imports — replace:

```python
from lib.settings import Settings
from lib.twitch import api, auth, gql, stream
from lib.windows import player
```

with:

```python
from lib import providers
from lib.settings import Settings
from lib.twitch import api, auth, gql
from lib.windows import player
```

Add `self._kick_live = []` to `__init__`, right after `self._selected_game = None` is no longer there (it's set per-load) — insert alongside the other per-instance lists:

```python
    def __init__(self, window, closed_event=None, settings=None):
        self.window = window
        # Shared across every view hosted by MainWindow, which bootstraps it.
        self.closed_event = closed_event
        self._settings = settings or Settings()
        self._followed = []
        self._live = []
        self._games = []
        self._kick_live = []
        self._selected_game = None
```

Modify `_build_list_item` — add one line before the final `return item`:

```python
def _build_list_item(channel, stream_data=None):
    item = xbmcgui.ListItem(channel["broadcaster_name"])
    if stream_data:
        item.setLabel2(
            stream_data["game_name"] + " - " + str(stream_data["viewer_count"]) + " viewers"
        )
        item.setArt({"thumb": _thumbnail_url(stream_data["thumbnail_url"])})
        item.setProperty("is_live", "true")
        item.setProperty("viewer_count", str(stream_data["viewer_count"]))
        item.setProperty("game_name", stream_data["game_name"])
        item.setProperty(
            "subtitle", str(stream_data["viewer_count"]) + " viewers · " + stream_data["game_name"]
        )
    else:
        item.setLabel2("Offline")
        item.setProperty("is_live", "false")
        item.setProperty("viewer_count", "")
        item.setProperty("game_name", "")
        item.setProperty("subtitle", "Offline")
    item.setProperty("broadcaster_id", channel["broadcaster_id"])
    item.setProperty("broadcaster_login", channel["broadcaster_login"])
    item.setProperty("platform", "twitch")
    return item
```

Add two new module-level functions right after `_build_list_item`:

```python
def _build_kick_list_item(normalized):
    item = xbmcgui.ListItem(normalized["display_name"])
    item.setLabel2(
        normalized["game_name"] + " - " + str(normalized["viewer_count"]) + " viewers"
    )
    item.setArt({"thumb": normalized["thumbnail_url"]})
    item.setProperty("is_live", "true")
    item.setProperty("viewer_count", str(normalized["viewer_count"]))
    item.setProperty("game_name", normalized["game_name"])
    item.setProperty(
        "subtitle",
        str(normalized["viewer_count"]) + " viewers · " + normalized["game_name"],
    )
    item.setProperty("broadcaster_id", normalized["id"])
    item.setProperty("broadcaster_login", normalized["login"])
    item.setProperty("platform", "kick")
    return item


def _interleave_live_items(twitch_live, kick_live):
    """twitch_live: list of (channel, stream_data) tuples, already live-only
    (from _merge_channels). kick_live: list of normalized Kick dicts, already
    live-only (from providers.get_kick_live_favorites). Returns built
    ListItems, interleaved by viewer_count descending, without needing
    _build_list_item's or providers' shapes to match each other."""
    tagged = [("twitch", stream_data["viewer_count"], (channel, stream_data)) for channel, stream_data in twitch_live]
    tagged += [("kick", normalized["viewer_count"], normalized) for normalized in kick_live]
    tagged.sort(key=lambda entry: entry[1], reverse=True)
    items = []
    for entry_platform, _viewer_count, payload in tagged:
        if entry_platform == "twitch":
            channel, stream_data = payload
            items.append(_build_list_item(channel, stream_data))
        else:
            items.append(_build_kick_list_item(payload))
    return items
```

Modify `_load_and_populate`:

```python
    def _load_and_populate(self, addon, client_id, token):
        followed = api.get_followed_channels(token["access_token"], client_id, token["user_id"])
        broadcaster_ids = [c["broadcaster_id"] for c in followed]
        live_list = api.get_live_status(token["access_token"], client_id, broadcaster_ids)
        games = gql.get_followed_live_games(addon.getSetting("website_token"))
        kick_live = providers.get_kick_live_favorites(addon)
        self._followed = followed
        self._live = live_list
        self._games = games
        self._kick_live = kick_live
        self._selected_game = None
        self._populate_games(games)
        self._populate(followed, live_list, kick_live)
        # MainWindow focuses a view's DEFAULT_FOCUS_ID (if any) before
        # activate() runs; claim the channel list explicitly now that it is
        # actually populated, so a leftover keypress can't trigger an
        # unintended action while focus is still up for grabs. If it stayed
        # empty there is nothing to focus, so offer the re-login button and
        # leave the explanatory message on screen (Back returns to Menu).
        channel_list = self._safe_control(self.CHANNEL_LIST_ID)
        if channel_list and channel_list.size():
            self.window.setFocusId(self.CHANNEL_LIST_ID)
        else:
            self._show_relogin_button()
```

Modify `_populate`:

```python
    def _populate(self, followed, live_list, kick_live, game_filter=None):
        empty_label = self._safe_control(self.EMPTY_LABEL_ID)
        if empty_label:
            empty_label.setLabel("")
        error_label = self._safe_control(self.ERROR_LABEL_ID)
        if error_label:
            error_label.setLabel("")
        control = self._safe_control(self.CHANNEL_LIST_ID)
        if control:
            control.reset()
            if not followed and not kick_live:
                if empty_label:
                    empty_label.setLabel(_EMPTY_FOLLOWED_MESSAGE)
                return
            live, offline = _merge_channels(followed, live_list)
            if game_filter is not None:
                live = [
                    (channel, stream_data)
                    for channel, stream_data in live
                    if stream_data["game_name"] == game_filter
                ]
                offline = []
                # The games filter is Twitch-only - Kick has no equivalent
                # taxonomy, so a selected filter hides Kick results entirely
                # rather than showing them unfiltered (documented decision).
                kick_live = []
            elif not self._settings.show_offline_channels:
                offline = []
            items = _interleave_live_items(live, kick_live)
            items += [_build_list_item(channel) for channel in offline]
            if not items:
                if empty_label:
                    empty_label.setLabel(_NO_MATCHES_MESSAGE if game_filter else _NO_LIVE_MESSAGE)
                return
            control.addItems(items)
```

Modify `_on_game_selected`:

```python
    def _on_game_selected(self):
        control = self._safe_control(self.GAMES_LIST_ID)
        if not control:
            return
        selected = control.getSelectedItem()
        if selected is None:
            return
        game_name = selected.getProperty("game_name")
        self._selected_game = game_name or None
        self._populate(self._followed, self._live, self._kick_live, game_filter=self._selected_game)
```

Replace `_on_channel_selected` and `_play_channel` in full:

```python
    def _on_channel_selected(self):
        control = self._safe_control(self.CHANNEL_LIST_ID)
        if not control:
            return
        selected = control.getSelectedItem()
        if selected is None or selected.getProperty("is_live") != "true":
            return
        platform = selected.getProperty("platform") or "twitch"
        broadcaster_login = selected.getProperty("broadcaster_login")
        if platform == "kick":
            self._play_channel("kick", broadcaster_login)
            return
        addon = xbmcaddon.Addon()
        token = auth.load_token(addon)
        if token is None:
            self._show_results_error(_MISSING_TOKEN_MESSAGE)
            return
        client_id = addon.getSetting("client_id")
        self._play_channel("twitch", broadcaster_login, token=token, client_id=client_id)

    def _play_channel(self, platform, broadcaster_login, token=None, client_id=None):
        addon = xbmcaddon.Addon()
        try:
            url = providers.resolve_stream_url(addon, platform, broadcaster_login)
        except providers.StreamUnavailableError:
            self._show_results_error(_PLAYBACK_ERROR_MESSAGE)
            return
        except Exception as exc:
            xbmc.log(
                "script.twitch.center: Live Streams channel selection failed: " + repr(exc),
                xbmc.LOGERROR,
            )
            self._show_results_error(_PLAYBACK_ERROR_MESSAGE)
            return
        play_kwargs = {"platform": platform}
        if platform == "twitch":
            play_kwargs.update(
                access_token=token["access_token"], client_id=client_id, user_id=token["user_id"]
            )
        if player.play_stream(url, broadcaster_login, **play_kwargs):
            error_label = self._safe_control(self.ERROR_LABEL_ID)
            if error_label:
                error_label.setLabel("")
        else:
            self._show_results_error(_PLAYBACK_ERROR_MESSAGE)
```

- [ ] **Step 5: Update the 6 existing tests that mock `lib.twitch.stream` directly**

These tests currently patch `lib.views.live_streams_view.stream.resolve_stream_url` — that import no longer exists in the module, so they need to patch `providers.resolve_stream_url` instead and adjust their call-argument assertions. Find and replace each of these 6 test functions in `tests/views/test_live_streams_view.py`:

```python
def test_selecting_a_live_channel_plays_it():
    addon = _addon_with_token({"access_token": "tok", "refresh_token": "ref", "user_id": "u1"})
    with patch("xbmcaddon.Addon", return_value=addon), patch.object(
        api, "get_followed_channels", return_value=FOLLOWED
    ), patch.object(api, "get_live_status", return_value=LIVE), patch.object(
        gql, "get_followed_live_games", return_value=[]
    ), patch.object(
        providers, "resolve_stream_url", return_value="https://example.invalid/stream.m3u8"
    ) as mock_resolve, patch(
        "lib.views.live_streams_view.player.play_stream", return_value=True
    ) as mock_play:
        win = LiveStreamsView(FakeWindow())
        win.activate()
        channel_control = win.window.getControl(LiveStreamsView.CHANNEL_LIST_ID)
        # LIVE-first order per _merge_channels: Carol (200 viewers) then Bob (50).
        channel_control.selectItem(0)  # Carol, live
        win.window.setFocusId(LiveStreamsView.CHANNEL_LIST_ID)
        win.handle_action(xbmcgui.Action(xbmcgui.ACTION_SELECT_ITEM))

    mock_resolve.assert_called_once()
    call_args = mock_resolve.call_args
    assert call_args.args[1] == "twitch"
    assert call_args.args[2] == "carol"
    mock_play.assert_called_once_with(
        "https://example.invalid/stream.m3u8",
        "carol",
        platform="twitch",
        access_token="tok",
        client_id="",
        user_id="u1",
    )


def test_selecting_a_live_channel_shows_error_when_resolution_fails():
    addon = _addon_with_token({"access_token": "tok", "refresh_token": "ref", "user_id": "u1"})
    with patch("xbmcaddon.Addon", return_value=addon), patch.object(
        api, "get_followed_channels", return_value=FOLLOWED
    ), patch.object(api, "get_live_status", return_value=LIVE), patch.object(
        gql, "get_followed_live_games", return_value=[]
    ), patch.object(
        providers, "resolve_stream_url", side_effect=providers.StreamUnavailableError("carol"),
    ):
        win = LiveStreamsView(FakeWindow())
        win.activate()
        channel_control = win.window.getControl(LiveStreamsView.CHANNEL_LIST_ID)
        channel_control.selectItem(0)
        win.window.setFocusId(LiveStreamsView.CHANNEL_LIST_ID)
        win.handle_action(xbmcgui.Action(xbmcgui.ACTION_SELECT_ITEM))

    assert win.window.getControl(LiveStreamsView.ERROR_LABEL_ID).getLabel() != ""
    assert win.window.getControl(LiveStreamsView.CHANNEL_LIST_ID).size() == 2


def test_selecting_a_live_channel_shows_error_when_playback_declined():
    addon = _addon_with_token({"access_token": "tok", "refresh_token": "ref", "user_id": "u1"})
    with patch("xbmcaddon.Addon", return_value=addon), patch.object(
        api, "get_followed_channels", return_value=FOLLOWED
    ), patch.object(api, "get_live_status", return_value=LIVE), patch.object(
        gql, "get_followed_live_games", return_value=[]
    ), patch.object(
        providers, "resolve_stream_url", return_value="https://example.invalid/stream.m3u8"
    ), patch("lib.views.live_streams_view.player.play_stream", return_value=False):
        win = LiveStreamsView(FakeWindow())
        win.activate()
        channel_control = win.window.getControl(LiveStreamsView.CHANNEL_LIST_ID)
        channel_control.selectItem(0)
        win.window.setFocusId(LiveStreamsView.CHANNEL_LIST_ID)
        win.handle_action(xbmcgui.Action(xbmcgui.ACTION_SELECT_ITEM))

    assert win.window.getControl(LiveStreamsView.ERROR_LABEL_ID).getLabel() != ""


def test_populate_clears_stale_playback_error_on_next_populate():
    # A playback failure sets the error label; the next time the channel list
    # is rebuilt (e.g. re-selecting "All" in the games filter), the stale
    # error must be cleared rather than sticking around for the rest of the
    # session.
    addon = _addon_with_token({"access_token": "tok", "refresh_token": "ref", "user_id": "u1"})
    with patch("xbmcaddon.Addon", return_value=addon), patch.object(
        api, "get_followed_channels", return_value=FOLLOWED
    ), patch.object(api, "get_live_status", return_value=LIVE), patch.object(
        gql, "get_followed_live_games", return_value=GAMES
    ), patch.object(
        providers, "resolve_stream_url", side_effect=providers.StreamUnavailableError("carol"),
    ):
        win = LiveStreamsView(FakeWindow())
        win.activate()
        channel_control = win.window.getControl(LiveStreamsView.CHANNEL_LIST_ID)
        channel_control.selectItem(0)
        win.window.setFocusId(LiveStreamsView.CHANNEL_LIST_ID)
        win.handle_action(xbmcgui.Action(xbmcgui.ACTION_SELECT_ITEM))

    assert win.window.getControl(LiveStreamsView.ERROR_LABEL_ID).getLabel() != ""

    games_control = win.window.getControl(LiveStreamsView.GAMES_LIST_ID)
    games_control.selectItem(0)  # "All"
    win.window.setFocusId(LiveStreamsView.GAMES_LIST_ID)
    win.handle_action(xbmcgui.Action(xbmcgui.ACTION_SELECT_ITEM))

    assert win.window.getControl(LiveStreamsView.ERROR_LABEL_ID).getLabel() == ""


def test_selecting_a_live_channel_clears_stale_error_on_successful_retry():
    addon = _addon_with_token({"access_token": "tok", "refresh_token": "ref", "user_id": "u1"})
    with patch("xbmcaddon.Addon", return_value=addon), patch.object(
        api, "get_followed_channels", return_value=FOLLOWED
    ), patch.object(api, "get_live_status", return_value=LIVE), patch.object(
        gql, "get_followed_live_games", return_value=[]
    ), patch.object(
        providers, "resolve_stream_url", side_effect=providers.StreamUnavailableError("carol"),
    ):
        win = LiveStreamsView(FakeWindow())
        win.activate()
        channel_control = win.window.getControl(LiveStreamsView.CHANNEL_LIST_ID)
        channel_control.selectItem(0)
        win.window.setFocusId(LiveStreamsView.CHANNEL_LIST_ID)
        win.handle_action(xbmcgui.Action(xbmcgui.ACTION_SELECT_ITEM))

    assert win.window.getControl(LiveStreamsView.ERROR_LABEL_ID).getLabel() != ""

    with patch("xbmcaddon.Addon", return_value=addon), patch.object(
        providers, "resolve_stream_url", return_value="https://example.invalid/stream.m3u8"
    ), patch("lib.views.live_streams_view.player.play_stream", return_value=True):
        win.handle_action(xbmcgui.Action(xbmcgui.ACTION_SELECT_ITEM))

    assert win.window.getControl(LiveStreamsView.ERROR_LABEL_ID).getLabel() == ""


def test_selecting_a_live_channel_shows_error_on_unexpected_exception():
    addon = _addon_with_token({"access_token": "tok", "refresh_token": "ref", "user_id": "u1"})
    with patch("xbmcaddon.Addon", return_value=addon), patch.object(
        api, "get_followed_channels", return_value=FOLLOWED
    ), patch.object(api, "get_live_status", return_value=LIVE), patch.object(
        gql, "get_followed_live_games", return_value=[]
    ), patch.object(providers, "resolve_stream_url", side_effect=RuntimeError("boom")):
        win = LiveStreamsView(FakeWindow())
        win.activate()
        channel_control = win.window.getControl(LiveStreamsView.CHANNEL_LIST_ID)
        channel_control.selectItem(0)
        win.window.setFocusId(LiveStreamsView.CHANNEL_LIST_ID)
        win.handle_action(xbmcgui.Action(xbmcgui.ACTION_SELECT_ITEM))

    assert win.window.getControl(LiveStreamsView.ERROR_LABEL_ID).getLabel() != ""
    assert win.window.getControl(LiveStreamsView.CHANNEL_LIST_ID).size() == 2
```

Also remove the now-unused `from lib.twitch import stream` import line from the top of the test file (`grep -n "\bstream\." tests/views/test_live_streams_view.py` first to confirm nothing else in the file still references the bare `stream` module - the local variable named `stream` inside `test_build_list_item_live_sets_label2_and_thumbnail` shadows it within that one function only and is unaffected either way).

- [ ] **Step 6: Run to verify everything passes**

Run: `pytest tests/views/test_live_streams_view.py -v`
Expected: PASS (every test in the file, old and new)

- [ ] **Step 7: Run the full relevant test set**

Run: `pytest tests/views/test_live_streams_view.py tests/test_providers.py tests/windows/test_player.py tests/test_addon_manifest.py -v`
Expected: PASS

- [ ] **Step 8: Commit**

```bash
git add resources/skins/Default/1080i/script-twitch-center-main.xml lib/views/live_streams_view.py tests/views/test_live_streams_view.py
git commit -m "feat: merge Kick favorites into Live Streams, interleaved by viewer count"
```

---

### Task 10: `DiscoverView` — Kick categories row

**Files:**
- Modify: `resources/skins/Default/1080i/script-twitch-center-main.xml`
- Modify: `lib/views/discover_view.py`
- Modify: `tests/views/test_discover_view.py`

**Interfaces:**
- Consumes: `providers.get_kick_top_categories(addon)`, `providers.get_kick_category_streams(addon, category_id)`, `providers.resolve_stream_url`, `providers.StreamUnavailableError` (Tasks 3, 5), `player.play_stream(..., platform=...)` (Task 8).
- Produces: `DiscoverView.KICK_CATEGORIES_LIST_ID = 309`, a second category-browse row separate from Twitch's existing `GAMES_LIST_ID`, populating the same shared `RESULTS_LIST_ID` on selection with Kick-tagged results.

**Design choice - the row stays separate, not merged with Twitch's games row:** Kick categories and Twitch games are different taxonomies with no id mapping between them (confirmed during this feature's design spec) - presenting them as one interchangeable row would misrepresent that. This task also migrates `DiscoverView`'s *existing* Twitch-only playback path from importing `lib.twitch.stream` directly to `providers.resolve_stream_url` (platform always `"twitch"` there), for the same reason `LiveStreamsView` did in Task 9 - one resolution mechanism in the codebase, not two that could drift.

- [ ] **Step 1: Shift the skin layout and add the Kick categories row**

In `resources/skins/Default/1080i/script-twitch-center-main.xml`'s DISCOVER (300) group:

Change the existing games list (`305`)'s `<ondown>` from `301` to `309`:

```xml
      <control type="list" id="305">
        <description>Top games</description>
        <posx>60</posx>
        <posy>220</posy>
        <width>1800</width>
        <height>90</height>
        <orientation>horizontal</orientation>
        <onup>306</onup>
        <ondown>309</ondown>
        <onleft>305</onleft>
        <onright>305</onright>
```

(its `<itemlayout>`/`<focusedlayout>` content is unchanged)

Insert a new list control right after `305`'s closing `</control>`, before the existing `<control type="list" id="301">`:

```xml
      <control type="list" id="309">
        <description>Kick categories</description>
        <posx>60</posx>
        <posy>320</posy>
        <width>1800</width>
        <height>90</height>
        <orientation>horizontal</orientation>
        <onup>305</onup>
        <ondown>301</ondown>
        <onleft>309</onleft>
        <onright>309</onright>
        <itemlayout width="220" height="80">
          <control type="label">
            <width>220</width>
            <height>80</height>
            <font>font13</font>
            <align>center</align>
            <aligny>center</aligny>
            <textcolor>ff53fc18</textcolor>
            <label>$INFO[ListItem.Label]</label>
          </control>
        </itemlayout>
        <focusedlayout width="220" height="80">
          <control type="label">
            <width>220</width>
            <height>80</height>
            <font>font13</font>
            <align>center</align>
            <aligny>center</aligny>
            <textcolor>ffffffff</textcolor>
            <label>$INFO[ListItem.Label]</label>
          </control>
        </focusedlayout>
      </control>
```

Change the results list (`301`)'s `posy`/`height`/`onup` (shifted down 100px to make room, bottom edge stays at 1000 so nothing overflows):

```xml
      <control type="list" id="301">
        <description>Results</description>
        <posx>60</posx>
        <posy>420</posy>
        <width>1800</width>
        <height>580</height>
        <onup>309</onup>
        <ondown>301</ondown>
```

(its `<itemlayout>`/`<focusedlayout>` content is unchanged)

Confirm the file is still well-formed: `python -c "import xml.dom.minidom; xml.dom.minidom.parse('resources/skins/Default/1080i/script-twitch-center-main.xml'); print('OK')"`

- [ ] **Step 2: Write the failing tests**

Append to `tests/views/test_discover_view.py`:

```python
from lib import providers


KICK_TOP_CATEGORIES = [{"id": 7, "name": "Just Chatting"}, {"id": 8, "name": "Slots"}]

KICK_CATEGORY_STREAM = {
    "platform": "kick",
    "id": "42",
    "login": "kickchannel",
    "display_name": "kickchannel",
    "is_live": True,
    "viewer_count": 88,
    "game_name": "Slots",
    "thumbnail_url": "https://example.invalid/kickthumb.jpg",
}


def test_oninit_populates_kick_categories_row():
    addon = _addon_with_token({"access_token": "tok", "refresh_token": "ref", "user_id": "u1"})
    with patch("xbmcaddon.Addon", return_value=addon), patch.object(
        api, "get_top_games", return_value=TOP_GAMES
    ), patch.object(providers, "get_kick_top_categories", return_value=KICK_TOP_CATEGORIES):
        win = DiscoverView(FakeWindow())
        win.activate()

    kick_control = win.window.getControl(DiscoverView.KICK_CATEGORIES_LIST_ID)
    assert kick_control.size() == 2
    assert kick_control.getListItem(0).getLabel() == "Just Chatting"
    assert kick_control.getListItem(0).getProperty("category_id") == "7"


def test_kick_categories_row_is_empty_when_no_kick_token():
    addon = _addon_with_token({"access_token": "tok", "refresh_token": "ref", "user_id": "u1"})
    with patch("xbmcaddon.Addon", return_value=addon), patch.object(
        api, "get_top_games", return_value=TOP_GAMES
    ), patch.object(providers, "get_kick_top_categories", return_value=[]):
        win = DiscoverView(FakeWindow())
        win.activate()

    kick_control = win.window.getControl(DiscoverView.KICK_CATEGORIES_LIST_ID)
    assert kick_control.size() == 0


def test_selecting_a_kick_category_populates_results_with_kick_items():
    addon = _addon_with_token({"access_token": "tok", "refresh_token": "ref", "user_id": "u1"})
    with patch("xbmcaddon.Addon", return_value=addon), patch.object(
        api, "get_top_games", return_value=TOP_GAMES
    ), patch.object(
        providers, "get_kick_top_categories", return_value=KICK_TOP_CATEGORIES
    ), patch.object(
        providers, "get_kick_category_streams", return_value=[KICK_CATEGORY_STREAM]
    ) as mock_get_streams:
        win = DiscoverView(FakeWindow())
        win.activate()
        kick_control = win.window.getControl(DiscoverView.KICK_CATEGORIES_LIST_ID)
        kick_control.selectItem(0)
        win.window.setFocusId(DiscoverView.KICK_CATEGORIES_LIST_ID)
        win.handle_action(xbmcgui.Action(xbmcgui.ACTION_SELECT_ITEM))

    mock_get_streams.assert_called_once()
    assert mock_get_streams.call_args.args[1] == "7"
    results_control = win.window.getControl(DiscoverView.RESULTS_LIST_ID)
    assert results_control.size() == 1
    assert results_control.getListItem(0).getProperty("broadcaster_login") == "kickchannel"
    assert results_control.getListItem(0).getProperty("platform") == "kick"


def test_selecting_a_live_kick_result_plays_it():
    addon = _addon_with_token({"access_token": "tok", "refresh_token": "ref", "user_id": "u1"})
    with patch("xbmcaddon.Addon", return_value=addon), patch.object(
        api, "get_top_games", return_value=TOP_GAMES
    ), patch.object(
        providers, "get_kick_top_categories", return_value=KICK_TOP_CATEGORIES
    ), patch.object(
        providers, "get_kick_category_streams", return_value=[KICK_CATEGORY_STREAM]
    ), patch.object(
        providers, "resolve_stream_url", return_value="https://kick.example/x.m3u8"
    ) as mock_resolve, patch(
        "lib.views.discover_view.player.play_stream", return_value=True
    ) as mock_play:
        win = DiscoverView(FakeWindow())
        win.activate()
        kick_control = win.window.getControl(DiscoverView.KICK_CATEGORIES_LIST_ID)
        kick_control.selectItem(0)
        win.window.setFocusId(DiscoverView.KICK_CATEGORIES_LIST_ID)
        win.handle_action(xbmcgui.Action(xbmcgui.ACTION_SELECT_ITEM))
        results_control = win.window.getControl(DiscoverView.RESULTS_LIST_ID)
        results_control.selectItem(0)
        win.window.setFocusId(DiscoverView.RESULTS_LIST_ID)
        win.handle_action(xbmcgui.Action(xbmcgui.ACTION_SELECT_ITEM))

    call_args = mock_resolve.call_args
    assert call_args.args[1] == "kick"
    assert call_args.args[2] == "kickchannel"
    mock_play.assert_called_once_with(
        "https://kick.example/x.m3u8", "kickchannel", platform="kick"
    )
```

- [ ] **Step 3: Run to verify it fails**

Run: `pytest tests/views/test_discover_view.py -v -k kick`
Expected: FAIL with `AttributeError: type object 'DiscoverView' has no attribute 'KICK_CATEGORIES_LIST_ID'`

- [ ] **Step 4: Implement**

Modify `lib/views/discover_view.py`'s imports:

```python
"""Discover view: browse live channels by any game, or search by channel name or
by game/category name (toggle via SEARCH_MODE_TOGGLE_ID). Also browses Kick's top
categories in a separate row. Not a Window subclass - see MainWindow."""
import xbmc
import xbmcaddon
import xbmcgui

from lib import providers
from lib.twitch import api, auth
from lib.windows import player

RESULTS_LIST_ID = 301
EMPTY_LABEL_ID = 302
ERROR_LABEL_ID = 303
RELOGIN_BUTTON_ID = 304
GAMES_LIST_ID = 305
SEARCH_EDIT_ID = 306
SEARCH_BUTTON_ID = 307
SEARCH_MODE_TOGGLE_ID = 308
KICK_CATEGORIES_LIST_ID = 309
```

(`stream` is no longer imported at module level - `_play_channel` now goes through `providers`.)

Add a Kick result-item builder near the existing `_build_stream_item`/`_build_channel_item`:

```python
def _build_kick_result_item(normalized):
    item = xbmcgui.ListItem(normalized["display_name"])
    item.setLabel2(
        normalized["game_name"] + " - " + str(normalized["viewer_count"]) + " viewers"
    )
    item.setArt({"thumb": normalized["thumbnail_url"]})
    item.setProperty("broadcaster_id", normalized["id"])
    item.setProperty("broadcaster_login", normalized["login"])
    item.setProperty("is_live", "true")
    item.setProperty("platform", "kick")
    return item
```

Modify the `DiscoverView` class attribute block to include the new id:

```python
class DiscoverView:
    RESULTS_LIST_ID = RESULTS_LIST_ID
    EMPTY_LABEL_ID = EMPTY_LABEL_ID
    ERROR_LABEL_ID = ERROR_LABEL_ID
    RELOGIN_BUTTON_ID = RELOGIN_BUTTON_ID
    GAMES_LIST_ID = GAMES_LIST_ID
    SEARCH_EDIT_ID = SEARCH_EDIT_ID
    SEARCH_BUTTON_ID = SEARCH_BUTTON_ID
    SEARCH_MODE_TOGGLE_ID = SEARCH_MODE_TOGGLE_ID
    KICK_CATEGORIES_LIST_ID = KICK_CATEGORIES_LIST_ID
```

Also add the two Twitch `ListItem`-building functions' `platform` tagging - modify `_build_stream_item` and `_build_channel_item` to each add one line before their `return item`:

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
    item.setProperty("platform", "twitch")
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
    item.setProperty("platform", "twitch")
    return item
```

Modify `_load_games`:

```python
    def _load_games(self, addon, client_id, token):
        games = api.get_top_games(token["access_token"], client_id)
        self._populate_games(games)
        kick_categories = providers.get_kick_top_categories(addon)
        self._populate_kick_categories(kick_categories)
        # Claim focus on the now-populated games list explicitly rather than
        # leaving it wherever the previous view left it - same race-avoidance
        # as LiveStreamsView._load_and_populate.
        games_list = self._safe_control(self.GAMES_LIST_ID)
        if games_list and games_list.size():
            self.window.setFocusId(self.GAMES_LIST_ID)
```

Add `_populate_kick_categories` right after `_populate_games`:

```python
    def _populate_kick_categories(self, categories):
        control = self._safe_control(self.KICK_CATEGORIES_LIST_ID)
        if control:
            control.reset()
            items = []
            for category in categories:
                item = xbmcgui.ListItem(category["name"])
                item.setProperty("category_id", str(category["id"]))
                items.append(item)
            control.addItems(items)
```

Add `_on_kick_category_selected` right after `_on_game_selected`:

```python
    def _on_kick_category_selected(self):
        control = self._safe_control(self.KICK_CATEGORIES_LIST_ID)
        if not control:
            return
        selected = control.getSelectedItem()
        if selected is None:
            return
        addon = xbmcaddon.Addon()
        category_id = selected.getProperty("category_id")
        results = providers.get_kick_category_streams(addon, category_id)
        self._populate_results([_build_kick_result_item(r) for r in results])
```

Modify `_show_error` to also reset the Kick categories row on a fatal failure:

```python
    def _show_error(self, message):
        """Fatal failure (activate / expired session): the whole screen is
        unusable, so wipe everything and offer the re-login button."""
        games_list = self._safe_control(self.GAMES_LIST_ID)
        if games_list:
            games_list.reset()
        kick_categories_list = self._safe_control(self.KICK_CATEGORIES_LIST_ID)
        if kick_categories_list:
            kick_categories_list.reset()
        results_list = self._safe_control(self.RESULTS_LIST_ID)
        if results_list:
            results_list.reset()
        empty_label = self._safe_control(self.EMPTY_LABEL_ID)
        if empty_label:
            empty_label.setLabel("")
        error_label = self._safe_control(self.ERROR_LABEL_ID)
        if error_label:
            error_label.setLabel(message)
        relogin_btn = self._safe_control(self.RELOGIN_BUTTON_ID)
        if relogin_btn:
            relogin_btn.setVisible(True)
            self.window.setFocusId(self.RELOGIN_BUTTON_ID)
```

Modify `handle_action` to dispatch the new list:

```python
    def handle_action(self, action):
        if action.getId() == xbmcgui.ACTION_SELECT_ITEM:
            focus = self.window.getFocusId()
            if focus == self.RELOGIN_BUTTON_ID:
                self.window._switch_view("login")
            elif focus == self.GAMES_LIST_ID:
                self._on_game_selected()
            elif focus == self.KICK_CATEGORIES_LIST_ID:
                self._on_kick_category_selected()
            elif focus == self.SEARCH_BUTTON_ID:
                self._on_search()
            elif focus == self.SEARCH_MODE_TOGGLE_ID:
                self._toggle_search_mode()
            elif focus == self.RESULTS_LIST_ID:
                self._on_channel_selected()
```

Replace `_on_channel_selected` and `_play_channel` in full (migrating off `lib.twitch.stream` and adding the Kick-selected branch, mirroring `LiveStreamsView`'s Task 9 approach):

```python
    def _on_channel_selected(self):
        control = self._safe_control(self.RESULTS_LIST_ID)
        if not control:
            return
        selected = control.getSelectedItem()
        if selected is None or selected.getProperty("is_live") != "true":
            return
        platform = selected.getProperty("platform") or "twitch"
        broadcaster_login = selected.getProperty("broadcaster_login")
        if platform == "kick":
            self._play_channel("kick", broadcaster_login)
            return
        addon = xbmcaddon.Addon()
        token = auth.load_token(addon)
        if token is None:
            self._show_results_error(_MISSING_TOKEN_MESSAGE)
            return
        client_id = addon.getSetting("client_id")
        self._play_channel("twitch", broadcaster_login, token=token, client_id=client_id)

    def _play_channel(self, platform, broadcaster_login, token=None, client_id=None):
        addon = xbmcaddon.Addon()
        try:
            url = providers.resolve_stream_url(addon, platform, broadcaster_login)
        except providers.StreamUnavailableError:
            self._show_results_error(_PLAYBACK_ERROR_MESSAGE)
            return
        except Exception as exc:
            xbmc.log(
                "script.twitch.center: Discover channel selection failed: " + repr(exc),
                xbmc.LOGERROR,
            )
            self._show_results_error(_PLAYBACK_ERROR_MESSAGE)
            return
        play_kwargs = {"platform": platform}
        if platform == "twitch":
            play_kwargs.update(
                access_token=token["access_token"], client_id=client_id, user_id=token["user_id"]
            )
        if player.play_stream(url, broadcaster_login, **play_kwargs):
            error_label = self._safe_control(self.ERROR_LABEL_ID)
            if error_label:
                error_label.setLabel("")
        else:
            self._show_results_error(_PLAYBACK_ERROR_MESSAGE)
```

- [ ] **Step 5: Update the 4 existing tests that mock `lib.twitch.stream` directly**

Find and replace in `tests/views/test_discover_view.py`:

```python
def test_selecting_a_live_result_plays_it():
    addon = _addon_with_token({"access_token": "tok", "refresh_token": "ref", "user_id": "u1"})
    with patch("xbmcaddon.Addon", return_value=addon), patch.object(
        api, "get_top_games", return_value=TOP_GAMES
    ), patch.object(api, "get_live_streams_by_game", return_value=STREAMS), patch.object(
        providers, "resolve_stream_url", return_value="https://example.invalid/stream.m3u8"
    ) as mock_resolve, patch(
        "lib.views.discover_view.player.play_stream", return_value=True
    ) as mock_play:
        win = DiscoverView(FakeWindow())
        win.activate()
        games_control = win.window.getControl(DiscoverView.GAMES_LIST_ID)
        games_control.selectItem(0)
        win.window.setFocusId(DiscoverView.GAMES_LIST_ID)
        win.handle_action(xbmcgui.Action(xbmcgui.ACTION_SELECT_ITEM))
        results_control = win.window.getControl(DiscoverView.RESULTS_LIST_ID)
        results_control.selectItem(0)
        win.window.setFocusId(DiscoverView.RESULTS_LIST_ID)
        win.handle_action(xbmcgui.Action(xbmcgui.ACTION_SELECT_ITEM))

    call_args = mock_resolve.call_args
    assert call_args.args[1] == "twitch"
    assert call_args.args[2] == STREAMS[0]["user_login"]
    mock_play.assert_called_once_with(
        "https://example.invalid/stream.m3u8",
        STREAMS[0]["user_login"],
        platform="twitch",
        access_token="tok",
        client_id="",
        user_id="u1",
    )


def test_selecting_an_offline_search_result_does_nothing():
    addon = _addon_with_token({"access_token": "tok", "refresh_token": "ref", "user_id": "u1"})
    with patch("xbmcaddon.Addon", return_value=addon), patch.object(
        api, "get_top_games", return_value=TOP_GAMES
    ), patch.object(api, "search_channels", return_value=SEARCH_RESULTS):
        win = DiscoverView(FakeWindow())
        win.activate()
        win.window.getControl(DiscoverView.SEARCH_EDIT_ID).setText("bob")
        win.window.setFocusId(DiscoverView.SEARCH_BUTTON_ID)
        win.handle_action(xbmcgui.Action(xbmcgui.ACTION_SELECT_ITEM))
        results_control = win.window.getControl(DiscoverView.RESULTS_LIST_ID)
        results_control.selectItem(1)  # Carol, offline per SEARCH_RESULTS[1]
        win.window.setFocusId(DiscoverView.RESULTS_LIST_ID)
        with patch.object(providers, "resolve_stream_url") as mock_resolve:
            win.handle_action(xbmcgui.Action(xbmcgui.ACTION_SELECT_ITEM))

    mock_resolve.assert_not_called()


def test_selecting_a_live_result_shows_results_error_when_resolution_fails():
    addon = _addon_with_token({"access_token": "tok", "refresh_token": "ref", "user_id": "u1"})
    with patch("xbmcaddon.Addon", return_value=addon), patch.object(
        api, "get_top_games", return_value=TOP_GAMES
    ), patch.object(api, "get_live_streams_by_game", return_value=STREAMS), patch.object(
        providers, "resolve_stream_url", side_effect=providers.StreamUnavailableError("alice"),
    ):
        win = DiscoverView(FakeWindow())
        win.activate()
        games_control = win.window.getControl(DiscoverView.GAMES_LIST_ID)
        games_control.selectItem(0)
        win.window.setFocusId(DiscoverView.GAMES_LIST_ID)
        win.handle_action(xbmcgui.Action(xbmcgui.ACTION_SELECT_ITEM))
        results_control = win.window.getControl(DiscoverView.RESULTS_LIST_ID)
        results_control.selectItem(0)
        win.window.setFocusId(DiscoverView.RESULTS_LIST_ID)
        win.handle_action(xbmcgui.Action(xbmcgui.ACTION_SELECT_ITEM))

    assert win.window.getControl(DiscoverView.ERROR_LABEL_ID).getLabel() != ""
    # Games row must survive a transient playback failure, same as a transient
    # search/browse failure already does.
    assert games_control.size() == 2


def test_selecting_a_live_result_shows_error_on_unexpected_exception():
    addon = _addon_with_token({"access_token": "tok", "refresh_token": "ref", "user_id": "u1"})
    with patch("xbmcaddon.Addon", return_value=addon), patch.object(
        api, "get_top_games", return_value=TOP_GAMES
    ), patch.object(api, "get_live_streams_by_game", return_value=STREAMS), patch.object(
        providers, "resolve_stream_url", side_effect=RuntimeError("boom"),
    ):
        win = DiscoverView(FakeWindow())
        win.activate()
        games_control = win.window.getControl(DiscoverView.GAMES_LIST_ID)
        games_control.selectItem(0)
        win.window.setFocusId(DiscoverView.GAMES_LIST_ID)
        win.handle_action(xbmcgui.Action(xbmcgui.ACTION_SELECT_ITEM))
        results_control = win.window.getControl(DiscoverView.RESULTS_LIST_ID)
        results_control.selectItem(0)
        win.window.setFocusId(DiscoverView.RESULTS_LIST_ID)
        win.handle_action(xbmcgui.Action(xbmcgui.ACTION_SELECT_ITEM))

    assert win.window.getControl(DiscoverView.ERROR_LABEL_ID).getLabel() != ""
```

Also remove the top-of-file `from lib.twitch import stream` import (line 3 of the original file: `from lib.twitch import stream`) - nothing else in the test file references it after this change (`grep -n "\bstream\." tests/views/test_discover_view.py` to confirm before deleting).

- [ ] **Step 6: Run to verify everything passes**

Run: `pytest tests/views/test_discover_view.py -v`
Expected: PASS (every test in the file, old and new)

- [ ] **Step 7: Run the full relevant test set**

Run: `pytest tests/views/test_discover_view.py tests/test_providers.py tests/windows/test_player.py tests/test_addon_manifest.py -v`
Expected: PASS

- [ ] **Step 8: Commit**

```bash
git add resources/skins/Default/1080i/script-twitch-center-main.xml lib/views/discover_view.py tests/views/test_discover_view.py
git commit -m "feat: add Kick categories row to Discover"
```

---

### Task 11: `SearchView` — merged Twitch + Kick search

**Files:**
- Modify: `lib/views/search_view.py`
- Modify: `tests/views/test_search_view.py`

**Interfaces:**
- Consumes: `providers.normalize_twitch_search_result(item)`, `providers.get_kick_search_results(addon, query)`, `providers.merge_by_viewer_count`, `providers.resolve_stream_url` (Tasks 4, 5), `player.play_stream(..., platform=...)` (Task 8).
- Produces: `SearchView.search_results` becomes a list of normalized dicts (was raw `gql.search` dicts); each rendered result carries a `platform` property; `play_selected` dispatches through the correct platform.

**Design choice on pagination:** Kick's `search_channels` has no cursor/pagination support (confirmed in `lib/kick/api.py`). Kick results are only fetched and merged in on the *first* search (`start_search`); `load_next_page` only ever fetches more Twitch results (via `gql.search`'s existing cursor), so clicking "Next Page" repeatedly never re-adds or duplicates Kick results.

- [ ] **Step 1: Write the failing tests**

Append to `tests/views/test_search_view.py`:

```python
from unittest.mock import patch

import xbmcaddon

from lib import providers
from lib.twitch import gql


def test_start_search_merges_twitch_and_kick_results_by_viewer_count():
    twitch_raw = [
        {"user_id": "1", "user_login": "alice", "user_name": "Alice", "viewer_count": 50, "game_name": "A"},
    ]
    kick_normalized = [
        {
            "platform": "kick",
            "id": "2",
            "login": "kickuser",
            "display_name": "kickuser",
            "is_live": True,
            "viewer_count": 500,
            "game_name": "B",
            "thumbnail_url": "",
        }
    ]
    with patch.object(gql, "search", return_value=(twitch_raw, None)), patch.object(
        providers, "get_kick_search_results", return_value=kick_normalized
    ):
        win = SearchView(FakeWindow())
        win.window.getControl(SearchView.SEARCH_INPUT_ID).setText("query")
        win.start_search()
        win.handle_action(xbmcgui.Action(999))  # drains _update_queue, see handle_action

    assert [r["login"] for r in win.search_results] == ["kickuser", "alice"]
    results_control = win.window.getControl(SearchView.RESULTS_LIST_ID)
    assert results_control.size() == 2
    assert results_control.getListItem(0).getProperty("platform") == "kick"
    assert results_control.getListItem(1).getProperty("platform") == "twitch"


def test_load_next_page_does_not_refetch_or_duplicate_kick_results():
    twitch_page_1 = [{"user_id": "1", "user_login": "alice", "user_name": "Alice", "viewer_count": 50, "game_name": "A"}]
    twitch_page_2 = [{"user_id": "2", "user_login": "bob", "user_name": "Bob", "viewer_count": 10, "game_name": "A"}]
    kick_normalized = [
        {
            "platform": "kick",
            "id": "3",
            "login": "kickuser",
            "display_name": "kickuser",
            "is_live": True,
            "viewer_count": 500,
            "game_name": "B",
            "thumbnail_url": "",
        }
    ]
    with patch.object(gql, "search", return_value=(twitch_page_1, "cursor-1")), patch.object(
        providers, "get_kick_search_results", return_value=kick_normalized
    ) as mock_kick_search:
        win = SearchView(FakeWindow())
        win.window.getControl(SearchView.SEARCH_INPUT_ID).setText("query")
        win.start_search()
        win.handle_action(xbmcgui.Action(999))

    assert mock_kick_search.call_count == 1

    with patch.object(gql, "search", return_value=(twitch_page_2, None)):
        win.load_next_page()
        win.handle_action(xbmcgui.Action(999))

    # Still exactly 1 Kick entry, not re-fetched or duplicated.
    kick_entries = [r for r in win.search_results if r["platform"] == "kick"]
    assert len(kick_entries) == 1
    assert mock_kick_search.call_count == 1
    assert [r["login"] for r in win.search_results] == ["kickuser", "alice", "bob"]


def test_play_selected_dispatches_to_the_selected_results_platform():
    with patch.object(providers, "resolve_stream_url", return_value="https://kick.example/x.m3u8") as mock_resolve, \
         patch("lib.views.search_view.player.play_stream") as mock_play:
        win = SearchView(FakeWindow())
        win.search_results = [
            {"platform": "kick", "login": "kickuser", "display_name": "kickuser"},
        ]
        win.window.getControl(SearchView.RESULTS_LIST_ID).addItem("kickuser")
        win.window.getControl(SearchView.RESULTS_LIST_ID).selectItem(0)
        win.play_selected()

    call_args = mock_resolve.call_args
    assert call_args.args[1] == "kick"
    assert call_args.args[2] == "kickuser"
    mock_play.assert_called_once_with("https://kick.example/x.m3u8", "kickuser", platform="kick")
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest tests/views/test_search_view.py -v -k "merges or duplicate or dispatches"`
Expected: FAIL — `providers.get_kick_search_results` never called, results list unchanged shape, `AttributeError`/`TypeError` on `platform=` kwarg

- [ ] **Step 3: Implement**

Replace `lib/views/search_view.py` in full:

```python
"""Search view: finding Twitch and Kick channels/streams. Not a Window
subclass - see MainWindow."""
import threading
import xbmcaddon
import xbmcgui
from lib import providers
from lib.twitch import gql
from lib.windows import player


class SearchView:
    SEARCH_INPUT_ID = 401
    RESULTS_LIST_ID = 402
    STATUS_LABEL_ID = 403
    NEXT_PAGE_BUTTON_ID = 404

    def __init__(self, window, closed_event=None):
        self.window = window
        self.search_results = []
        self._update_queue = []
        self._next_cursor = None
        # Shared across every view hosted by MainWindow, which bootstraps it.
        self.closed_event = closed_event

    def _safe_control(self, control_id):
        try:
            return self.window.getControl(control_id)
        except Exception:
            return None

    def activate(self):
        self.window.setFocusId(self.SEARCH_INPUT_ID)
        self.window.getControl(self.STATUS_LABEL_ID).setLabel("")
        self._update_next_page_button()

    def handle_click(self, control_id):
        if control_id == self.SEARCH_INPUT_ID:
            self.start_search()
        elif control_id == self.RESULTS_LIST_ID:
            self.play_selected()
        elif control_id == self.NEXT_PAGE_BUTTON_ID:
            self.load_next_page()

    def handle_action(self, action):
        if action.getId() == xbmcgui.ACTION_SELECT_ITEM:
            if self.window.getFocusId() == self.SEARCH_INPUT_ID:
                self.start_search()
            elif self.window.getFocusId() == self.RESULTS_LIST_ID:
                self.play_selected()
            elif self.window.getFocusId() == self.NEXT_PAGE_BUTTON_ID:
                self.load_next_page()
        if self._update_queue:
            self._process_updates()

    def start_search(self):
        query = self.window.getControl(self.SEARCH_INPUT_ID).getLabel()
        if not query:
            return
        self.window.getControl(self.STATUS_LABEL_ID).setLabel("Searching...")
        self.window.getControl(self.RESULTS_LIST_ID).reset()
        self.search_results = []
        self._next_cursor = None
        self._update_next_page_button()

        def search_task():
            twitch_results, cursor = gql.search(query, search_type="all")
            addon = xbmcaddon.Addon()
            kick_results = providers.get_kick_search_results(addon, query)
            self._update_queue.append(("update_results", twitch_results, kick_results, cursor))

        threading.Thread(target=search_task, daemon=True).start()

    def load_next_page(self):
        if not self._next_cursor:
            return
        self.window.getControl(self.STATUS_LABEL_ID).setLabel("Loading more...")
        self.window.getControl(self.NEXT_PAGE_BUTTON_ID).setEnabled(False)

        def search_task():
            twitch_results, cursor = gql.search(
                query=self.window.getControl(self.SEARCH_INPUT_ID).getLabel(),
                search_type="all",
                cursor=self._next_cursor
            )
            # No new Kick fetch on later pages - Kick's search has no
            # pagination, and re-fetching here would duplicate the Kick
            # results already merged in from the first page.
            self._update_queue.append(("update_results", twitch_results, [], cursor))

        threading.Thread(target=search_task, daemon=True).start()

    def _process_updates(self):
        if not self._update_queue:
            return
        action, twitch_results, kick_results, cursor = self._update_queue.pop(0)
        if action == "update_results":
            self._render_results(twitch_results, kick_results, cursor)

    def _render_results(self, twitch_results, kick_results, cursor):
        twitch_normalized = [providers.normalize_twitch_search_result(r) for r in twitch_results]
        merged = providers.merge_by_viewer_count(twitch_normalized, kick_results)
        self.search_results.extend(merged)
        self._next_cursor = cursor
        self.window.getControl(self.STATUS_LABEL_ID).setLabel("")
        list_control = self.window.getControl(self.RESULTS_LIST_ID)
        for normalized in merged:
            item = xbmcgui.ListItem(normalized["display_name"])
            item.setProperty("platform", normalized["platform"])
            list_control.addItem(item)
        self._update_next_page_button()

    def _update_next_page_button(self):
        btn = self._safe_control(self.NEXT_PAGE_BUTTON_ID)
        if btn:
            btn.setVisible(bool(self._next_cursor))
            btn.setEnabled(bool(self._next_cursor))

    def play_selected(self):
        idx = self.window.getControl(self.RESULTS_LIST_ID).getSelectedPosition()
        if idx < 0 or idx >= len(self.search_results):
            return
        result = self.search_results[idx]
        login = result.get("login")
        if not login:
            return
        addon = xbmcaddon.Addon()
        url = providers.resolve_stream_url(addon, result["platform"], login)
        player.play_stream(url, login, platform=result["platform"])
```

- [ ] **Step 4: Run to verify it passes**

Run: `pytest tests/views/test_search_view.py -v`
Expected: PASS (every test in the file, old and new)

- [ ] **Step 5: Run the full relevant test set**

Run: `pytest tests/views/test_search_view.py tests/test_providers.py tests/windows/test_player.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add lib/views/search_view.py tests/views/test_search_view.py
git commit -m "feat: merge Kick into Search results, dispatch playback by platform"
```

---

### Task 12: Full suite check

**Files:** none (verification only)

- [ ] **Step 1: Run the entire test suite**

Run: `pytest`
Expected: all tests pass - every pre-existing test (untouched by this plan) plus every test added or modified across Tasks 1-11.

- [ ] **Step 2: Confirm no stray `xbmc` import crept into `lib/providers.py`**

Run: `pytest tests/test_architecture.py -v`
Expected: PASS

- [ ] **Step 3: Confirm the skin file is well-formed and every control id is still unique**

Run:
```bash
python -c "import xml.dom.minidom; xml.dom.minidom.parse('resources/skins/Default/1080i/script-twitch-center-main.xml'); print('OK')"
pytest tests/test_addon_manifest.py -v
```
Expected: `OK`, all `test_addon_manifest.py` tests PASS

- [ ] **Step 4: Update `tests/test_addon_manifest.py`'s `test_main_skin_xml_declares_all_expected_control_ids`**

This test cross-references every view's declared control-id constants against the skin file. Add the new ones:

```python
    from lib.views.discover_view import (
        EMPTY_LABEL_ID as DISCOVER_EMPTY_LABEL_ID,
        ERROR_LABEL_ID as DISCOVER_ERROR_LABEL_ID,
        GAMES_LIST_ID as DISCOVER_GAMES_LIST_ID,
        KICK_CATEGORIES_LIST_ID as DISCOVER_KICK_CATEGORIES_LIST_ID,
        RELOGIN_BUTTON_ID as DISCOVER_RELOGIN_BUTTON_ID,
        RESULTS_LIST_ID as DISCOVER_RESULTS_LIST_ID,
        SEARCH_BUTTON_ID as DISCOVER_SEARCH_BUTTON_ID,
        SEARCH_EDIT_ID as DISCOVER_SEARCH_EDIT_ID,
        SEARCH_MODE_TOGGLE_ID as DISCOVER_SEARCH_MODE_TOGGLE_ID,
    )
    from lib.views.kick_login_view import KickLoginView
    from lib.views.live_streams_view import (
        CHANNEL_LIST_ID,
        EMPTY_LABEL_ID as LIVE_STREAMS_EMPTY_LABEL_ID,
        ERROR_LABEL_ID as LIVE_STREAMS_ERROR_LABEL_ID,
        GAMES_LIST_ID as LIVE_STREAMS_GAMES_LIST_ID,
        RELOGIN_BUTTON_ID as LIVE_STREAMS_RELOGIN_BUTTON_ID,
        TITLE_LABEL_ID,
    )
    from lib.views.login_view import LoginView
    from lib.views.menu_view import MenuView
    from lib.views.search_view import SearchView

    expected_ids = {
        LoginView.CODE_LABEL_ID,
        LoginView.URL_LABEL_ID,
        LoginView.STATUS_LABEL_ID,
        LoginView.CANCEL_BUTTON_ID,
        MenuView.LIVE_STREAMS_BUTTON_ID,
        MenuView.DISCOVER_BUTTON_ID,
        MenuView.SEARCH_BUTTON_ID,
        MenuView.SETTINGS_BUTTON_ID,
        MenuView.RELOGIN_BUTTON_ID,
        MenuView.KICK_LOGIN_BUTTON_ID,
        KickLoginView.URL_LABEL_ID,
        KickLoginView.STATUS_LABEL_ID,
        KickLoginView.CANCEL_BUTTON_ID,
        CHANNEL_LIST_ID,
        LIVE_STREAMS_EMPTY_LABEL_ID,
        LIVE_STREAMS_ERROR_LABEL_ID,
        LIVE_STREAMS_GAMES_LIST_ID,
        LIVE_STREAMS_RELOGIN_BUTTON_ID,
        TITLE_LABEL_ID,
        DISCOVER_RESULTS_LIST_ID,
        DISCOVER_EMPTY_LABEL_ID,
        DISCOVER_ERROR_LABEL_ID,
        DISCOVER_RELOGIN_BUTTON_ID,
        DISCOVER_GAMES_LIST_ID,
        DISCOVER_SEARCH_EDIT_ID,
        DISCOVER_SEARCH_BUTTON_ID,
        DISCOVER_SEARCH_MODE_TOGGLE_ID,
        DISCOVER_KICK_CATEGORIES_LIST_ID,
        SearchView.SEARCH_INPUT_ID,
        SearchView.RESULTS_LIST_ID,
        SearchView.STATUS_LABEL_ID,
        SearchView.NEXT_PAGE_BUTTON_ID,
    }
    control_ids = set(_main_skin_control_ids())
    assert expected_ids <= control_ids
```

Run: `pytest tests/test_addon_manifest.py -v`
Expected: PASS

No commit for Step 4 alone - fold it into whichever earlier task's commit is still open, or commit it standalone:

```bash
git add tests/test_addon_manifest.py
git commit -m "test: extend addon-manifest control-id coverage for Kick views"
```

No further commit for Steps 1-3 - they're verification checkpoints, not code changes.
