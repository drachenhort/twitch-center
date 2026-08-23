# Kick live-testing findings — 2026-08-22

**Status (2026-08-23):** Findings 1, 2, 3 fixed in v0.22.2 (see CHANGELOG.md).
Finding 4 resolved by removing Kick from Search (v0.22.2) rather than by
finding a working endpoint - the unofficial `kick.com/api/search` route
exists but its param name couldn't be found live and it appears gated by
browser-session/bot-detection. Finding 5 (misleading "Access denied" message)
still open, low priority.

First real (non-mocked) test of the Kick integration (v0.22.1) against Kick's
live API, using a real Kick account (`drachenhort1`) on the local Kodi
install. Login (PKCE flow) works correctly once the app's registered redirect
URI matches `http://127.0.0.1:8919/callback` exactly (Kick returns
`error=invalid+redirect+uri` on the callback otherwise, which the addon's
current code collapses into the generic, misleading "Access denied" message
— see Finding 5).

Four real bugs found, all traced to unconfirmed field-name/endpoint guesses
made during implementation (exactly the risk the original plan flagged and
asked to correct against a live request — this never happened before now).

## Finding 1 — Crash: `thumbnail` field shape guessed wrong (Critical)

Kick's real API returns `thumbnail` as a **flat URL string**, not
`{"url": "..."}` as guessed everywhere in `lib/providers.py`.

Confirmed via real requests:

```
GET https://api.kick.com/public/v1/livestreams?limit=20
-> {"data": [{..., "thumbnail": "https://images.kick.com/video_thumbnails/.../480.webp", ...}]}

GET https://api.kick.com/public/v1/channels?slug=korekore_ch
-> {"data": [{..., "stream": {..., "thumbnail": "https://images.kick.com/.../480.webp", ...}, ...}]}
```

Both `_normalize_kick_channel` (`lib/providers.py:79-98`, reads
`stream_info.get("thumbnail") or {}` then `.get("url", "")`) and
`_normalize_kick_live_stream_entry` (`lib/providers.py:143-161`, same
pattern on `entry.get("thumbnail")`) do:

```python
thumbnail = stream_info.get("thumbnail") or {}   # real value: a non-empty string
...
"thumbnail_url": thumbnail.get("url", ""),        # AttributeError: 'str' object has no attribute 'get'
```

Since the real value is a non-empty string, `or {}` never fires (truthy), so
`thumbnail` ends up being the raw URL string, and `.get("url", "")` raises
`AttributeError: 'str' object has no attribute 'get'`.

**Blast radius (confirmed no exception handling anywhere in the call chain):**
- `LiveStreamsView` — crashes as soon as the user has ≥1 live Kick favorite
  (`_load_and_populate` → `providers.get_kick_live_favorites` →
  `_normalize_kick_channel`, uncaught).
- `DiscoverView._on_kick_category_selected` (`lib/views/discover_view.py:280-290`)
  — crashes as soon as a Kick category is selected (no try/except around
  `providers.get_kick_category_streams`, unlike every other playback/network
  call in that file). `MainWindow.onAction` has no wrapper either, so this is
  an unhandled exception all the way up.

**Fix:** in both normalizers, read the thumbnail directly as a string:
`"thumbnail_url": stream_info.get("thumbnail", "")` / `entry.get("thumbnail", "")`
— drop the `{"url": ...}` unwrapping entirely.

## Finding 2 — Silent wrong data: `category` nesting guessed wrong

`_normalize_kick_channel` (`lib/providers.py:79-98`) reads:

```python
stream_info = channel.get("stream") or {}
category = stream_info.get("category") or {}   # WRONG: category isn't under "stream"
```

Real `/channels` response has `category` as a **top-level key of the channel
dict**, not nested under `stream`:

```json
{"broadcaster_user_id": 58166499, "slug": "korekore_ch", "stream": {...no category key...},
 "category": {"id": 15, "name": "Just Chatting", "thumbnail": "..."}, ...}
```

Since `stream_info.get("category")` always misses, this doesn't crash (the
`or {}` fallback saves it) — it silently makes `game_name` always `""` for
every Kick favorite on Live Streams. Was masked by Finding 1's crash (never
got this far before now).

**Fix:** read `category = channel.get("category") or {}` (top-level, not
`stream_info.get(...)`).

Note: `_normalize_kick_live_stream_entry` (used for Discover's category
browsing) reads `entry.get("category")` at the top level already — that one
is correct, per the `/livestreams` sample above where `category` **is**
top-level in that response shape. Only the `/channels`-shaped normalizer
(`_normalize_kick_channel`) has this bug.

## Finding 3 — Discover's "Kick categories" feature can't work as designed

`get_top_categories` (`lib/kick/api.py:58-60`) calls:

```
GET https://api.kick.com/public/v1/categories?limit=20
```

Real response: `400 Bad Request`, `{"data":{},"message":"Invalid request"}`.

Per Kick's own docs (docs.kick.com), `GET /public/v1/categories`:
- Requires a **mandatory** `q` (search query) string param — there is no
  "list all / top categories" mode.
- Has no `limit` param at all (the actual param for the pagination page count is `page`).
- Is marked **deprecated** in the docs.

**This means "browse Kick's top categories" (Task 3 / Task 10 of the
original plan) is not something Kick's public API supports at all.** There
is no browse-without-a-search-term capability to build against. The feature
as speced (a populated "top categories" row on Discover, browsable without
typing anything) cannot be built against this endpoint.

Needs a design decision before any fix, options to consider next session:
- Drop the Kick-categories-row idea entirely (Discover keeps Kick out,
  Live Streams' favorites + Search remain the two Kick entry points).
- Repurpose the row into something the deprecated, query-required endpoint
  *can* do — e.g. seed it with a fixed set of popular search terms
  (fragile, arbitrary).
- Investigate whether `/public/v1/livestreams` (which works, confirmed
  Finding 1's sample) can be sorted/grouped by `category` client-side instead
  of relying on a dedicated categories-listing endpoint — i.e. fetch a page
  of top live streams and derive a "categories seen" list from their
  `category` fields, rather than calling `/categories` at all.

Since `get_kick_top_categories` (`lib/providers.py`) wraps the call in
`except Exception: return []`, this currently degrades to a silently-empty
row (no crash, no visible symptom besides "nothing ever shows up there") —
consistent with the "Kick failures are silent" global constraint, but hides
that the feature is fundamentally non-functional, not just "no categories
today."

## Finding 4 — Kick search endpoint returns 404 (silently broken, no crash)

`search_channels` (`lib/kick/api.py:75-83`) calls:

```
GET https://kick.com/api/v2/search/channels?searchQuery=...&limit=...
```

Real response: `404`, `{"message": ""}` — wrong URL/path (function's own
docstring already flagged this as an unconfirmed guess needing live
verification: "Unofficial endpoint - confirm against docs.kick.com / kick.com's
own web client at implementation time").

`get_kick_search_results` (`lib/providers.py`) wraps this in
`except Exception: return []`, so `SearchView` never crashes — Kick results
just never appear in Search, silently. Needs the correct endpoint found (or
confirmation that kick.com's own web client uses a different one now) before
this is fixable.

## Finding 5 — "Access denied" is a misleading catch-all for any OAuth error

`run_pkce_login` (`lib/kick/auth.py`, around line 209-216) maps *any*
non-empty `error` query param from Kick's redirect to the generic `"denied"`
status:

```python
if status == "error":
    on_status("denied")   # shown to the user as "Access denied. Reopen this screen to try again."
    return False
```

Confirmed live: a misconfigured redirect URI produces
`?error=invalid+redirect+uri` from Kick, which the addon shows to the user
as "Access denied" — indistinguishable from the user actually clicking Deny
on Kick's consent screen. The real error string (`result["error"]`) is
available in `result` at that point but is discarded before reaching
`on_status`.

Not a functional bug (login still works once the actual config problem is
fixed), but a real diagnosability gap — worth improving so a future
mis-registered app doesn't read as "you denied it" when it's actually a
config mismatch. Low priority relative to Findings 1-4.

## What's confirmed working

- PKCE login flow end-to-end (once redirect URI is correctly registered):
  `run_pkce_login` → loopback callback → token exchange → `get_current_user`
  → token saved. `get_current_user` (`lib/kick/api.py:25-33`) — field names
  correct as-is (`user_id`, `name` → login/display_name mapping verified
  correct against a real response).
- `GET /public/v1/livestreams` — confirmed working, 200, correct shape
  matching `_normalize_kick_live_stream_entry`'s field names EXCEPT the
  thumbnail shape (Finding 1).
- `GET /public/v1/channels?slug=...` — confirmed working, 200, correct shape
  matching `_normalize_kick_channel`'s field names except thumbnail (Finding 1)
  and category nesting (Finding 2).

## Suggested order for next session

1. Fix Finding 1 (crash) — mechanical, small, test against the real shapes
   captured above (can write regression tests using these exact real
   response bodies as fixtures instead of guessed shapes).
2. Fix Finding 2 (silent wrong data) alongside Finding 1 — same file, same
   function.
3. Decide + implement a direction for Finding 3 (categories row redesign or
   removal).
4. Investigate the correct Kick search endpoint for Finding 4, or drop Kick
   from Search if no working endpoint is found.
5. Consider Finding 5 as a small polish pass (surface the real error reason,
   distinguish config errors from user-denied).

## Test credentials used (local Kodi install only, not committed anywhere)

- Kick app client_id: `01M0NF1C41VN6SX6X6HY6F17D6` (registered by the user at
  dev.kick.com; redirect URI corrected to `http://127.0.0.1:8919/callback`
  during this session)
- Logged-in Kick account: `drachenhort1`
- These live only in `~/.kodi/userdata/addon_data/script.twitch.center/settings.xml`
  on this machine, not in the repo.
