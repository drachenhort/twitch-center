# Kick stream watching — design spec

## Context

`lib/kick/` (merged 2026-08-22, v0.21.0) already provides a fully tested,
unwired Kick.com client: OAuth 2.1 PKCE login (`lib/kick/auth.py`), a Public
API client (`lib/kick/api.py`), and stream URL resolution
(`lib/kick/stream.py`) — built to mirror `lib/twitch/`'s shape closely
enough to dispatch through a common interface. Nothing in the running addon
calls it yet.

This spec covers the next sub-project: **getting Kick channels watchable**
through the existing Live Streams / Discover / Search screens, merged with
Twitch results per the user's explicit "unified lists, not a separate menu"
decision (recorded in the original provider-core spec's Context section and
reconfirmed during this spec's brainstorming). **Kick chat is explicitly out
of scope** — the user deprioritized it 2026-08-22 in favor of getting
watching working first (see project memory `project-kick-integration-priority`).
This is what the original provider-core spec called sub-projects 3
("UI unification") and 4 ("playback wiring"), combined and scoped down to
exclude chat.

## Goals

- A user who has logged into both Twitch and Kick sees one merged Live
  Streams list, one merged Search, and Kick's own category-browse row on
  Discover — and can play any Kick channel through Kodi's native player,
  same as Twitch.
- Kick login is fully optional and independent of Twitch login: a user with
  no Kick account continues to see exactly what they see today (Twitch
  results only, no Kick-shaped UI dead ends).
- No chat for Kick channels. `chat_overlay_enabled` never applies to a Kick
  stream.

## Non-goals

- Kick chat (any of it — no chat overlay, no chat client wiring). Revisit
  once watching ships.
- Any change to Twitch's own behavior beyond what's needed to merge Kick in
  (Twitch's own API calls, error messages, and flows are otherwise
  untouched).
- Clips, VODs, following/unfollowing Kick channels via Kick's own graph (it
  doesn't expose one — see below).

## Background: what changed since the provider-core spec

Two real constraints surfaced during brainstorming that the original
4-sub-project outline didn't account for:

1. **Kick's Public API requires `client_secret`** (confirmed against
   docs.kick.com during provider-core's final review) — a Kick login needs
   `kick_client_id` AND `kick_client_secret` set in Settings, not just a
   client id like Twitch's default-shipped one. There is no way to make Kick
   login "just work" out of the box the way Twitch's does.
2. **Kick's Public API has no "followed channels" endpoint at all**
   (confirmed against `docs.kick.com/apis/livestreams` — `/livestreams`
   filters by category/language/broadcaster-id list, `/users/livestreams`
   takes explicit user IDs, neither expresses "who does this user follow").
   Twitch's Live Streams screen is specifically "your followed channels,
   live ones first" — Kick can't replicate that from its own API. This spec
   uses **locally-stored favorites** (channel slugs saved in an addon
   setting, managed by the user from Search/Discover) as Kick's equivalent.

## Architecture: a thin provider-dispatch layer

New module: **`lib/providers.py`** (pure Python, no `xbmc*` imports, follows
the same architectural rule as `lib/twitch/` and `lib/kick/`).

Rather than scattering `if platform == "kick"` branches through every view
and through `player.py`, this module exposes one dict-of-callables per
platform, wrapping each provider's already-existing functions behind a
common shape the views and player can call without knowing which platform
they're talking to:

```python
PROVIDERS = {
    "twitch": {
        "get_live_streams": ...,   # wraps twitch.api.get_live_streams_by_game / get_followed_channels+get_live_status
        "get_top_categories": ...,  # wraps twitch.api.get_top_games
        "search_channels": ...,     # wraps twitch.gql.search (unauthenticated, unlike Kick)
        "resolve_stream_url": ...,  # wraps twitch.stream.resolve_stream_url(login, website_token)
    },
    "kick": {
        "get_live_streams": ...,    # wraps kick.api.get_live_streams
        "get_top_categories": ...,  # wraps kick.api.get_top_categories
        "search_channels": ...,     # wraps kick.api.search_channels
        "resolve_stream_url": ...,  # wraps kick.stream.resolve_stream_url(token, slug)
    },
}
```

Each wrapped function returns a **normalized dict** shape shared across both
platforms, tagged with a `"platform"` key (`"twitch"` or `"kick"`), so a
single merge/interleave/render code path in each view handles both:

```python
{
    "platform": "twitch" | "kick",
    "id": str,                 # broadcaster id / broadcaster_user_id
    "login": str,               # broadcaster_login / slug
    "display_name": str,
    "is_live": bool,
    "viewer_count": int,        # 0 if not live / unknown
    "game_name": str,           # "" if not live / unknown
    "thumbnail_url": str,       # "" if none
}
```

This is the same normalization discipline `lib/kick/api.py` already applies
internally (Kick fields renamed to Twitch's naming) — `lib/providers.py`
just extends it one layer up so **views stop importing `lib.twitch.api` /
`lib.kick.api` directly** and import `lib.providers` instead. `lib/twitch/`
and `lib/kick/` themselves are untouched; `lib/providers.py` is purely an
adapter layer.

**Per-platform token/credential handling is the provider dict's problem, not
the view's.** Each wrapped function internally loads its own platform's
saved token (`twitch.auth.load_token` / `kick.auth.load_token`) and — this
is the key simplification — **returns an empty list / `None` silently if
that platform's token is missing**, rather than raising. A view that calls
`providers.get_live_streams(addon)` (no per-platform branching) gets
whatever's available; Kick's absence is invisible, not an error state. Only
Twitch's own missing-token case keeps its existing behavior (the "You're not
logged in" screen), because that's an existing, deliberate UX for the
primary platform — this spec doesn't change it.

## Kick login: new view, new skin group

Kick's PKCE flow doesn't fit `LoginView`'s shape (device code + separate
verification URL, polling). It needs a new `KickLoginView`
(`lib/views/kick_login_view.py`), mirroring `LoginView`'s structure but
calling `kick.auth.run_pkce_login` instead of `twitch.auth.run_device_code_login`:

- One label showing a single authorize URL (`on_code(url)` — one argument,
  unlike Twitch's `on_code(user_code, verification_uri)`) with on-screen
  instructions to open it on a phone or PC on the same network as this
  Kodi device (the loopback callback server binds to this device's LAN
  address, not just `127.0.0.1`, since the browser doing the authorizing is
  a different device — confirm/adjust `redirect_uri` construction in
  `lib/kick/auth.py` accordingly, or document that same-device browsing to
  `127.0.0.1:<port>` also works when Kodi and the browser share a machine).
- A status label using the same status vocabulary as Twitch's login
  (`pending`/`success`/`expired`/`error` — `run_pkce_login` additionally has
  `"denied"`, needs its own message).
- Cancel button, same shape as `LoginView.CANCEL_BUTTON_ID`.

New skin group in `script-twitch-center-main.xml` (next free group id after
existing 100/200/300/400/500), registered in
`MainWindow.GROUP_IDS["kick_login"]` and `_default_view_classes()`.

**Menu changes** (`lib/views/menu_view.py`, `script-twitch-center-main.xml`
group 500): new "Log in to Kick" button, next free id after
`RELOGIN_BUTTON_ID` (505) — confirm the exact number against the skin file
at implementation time. `MenuView.handle_action` gets a branch:

```python
elif focus == self.KICK_LOGIN_BUTTON_ID:
    addon = xbmcaddon.Addon()
    if not addon.getSetting("kick_client_id") or not addon.getSetting("kick_client_secret"):
        xbmcgui.Dialog().ok("Kick", "Set Kick Client ID and Client Secret in Settings first.")
    else:
        self.window._switch_view("kick_login")
```

(Per the confirmed decision: dialog pointing to Settings, not a hidden menu
entry.)

## Live Streams: favorites + interleave

**Favorites storage:** a new hidden setting `kick_favorite_channels`
(JSON array of slugs, same pattern as `kick_token`), with helper functions
in `lib/providers.py` (`get_kick_favorites(addon)` /
`add_kick_favorite(addon, slug)` / `remove_kick_favorite(addon, slug)`) —
pure JSON list manipulation, no network calls, testable without mocks.

**`lib/views/live_streams_view.py` changes:**
- Twitch side (`_load_and_populate`, `_merge_channels`, `_build_list_item`)
  stays as-is internally, but its output is converted to the normalized
  provider-dict shape before merging.
- Kick side: for each favorited slug, call `providers.PROVIDERS["kick"]["get_live_streams"]`
  filtered/matched against the favorites list (Kick's `/livestreams`
  doesn't take a slug list directly — per-favorite `kick.api.get_channel`
  calls, capped at a reasonable favorites-list size, is the straightforward
  approach; batching is an optimization to revisit if favorites lists turn
  out large in practice).
- **Merge:** combine both platforms' live-only items into one list, sorted
  by `viewer_count` descending (the confirmed "interleaved by viewer count"
  decision) — offline-favorites handling mirrors Twitch's existing
  `show_offline_channels` setting, applied per-platform the same way.
- `_build_list_item` gains a `platform` `ListItem` property so the skin can
  show a small platform badge/icon (image control keyed off
  `ListItem.Property(platform)`, added to `script-twitch-center-main.xml`'s
  `itemlayout`/`focusedlayout` for control 201) and so `_on_channel_selected`
  knows which resolver/player call to make.
- Games filter row (`GAMES_LIST_ID`, 205): stays Twitch-only, unchanged —
  selecting a Twitch game filters out all Kick items from the merged list
  (Kick has no equivalent taxonomy to filter by here; this is an accepted,
  documented limitation, not a bug to fix in this sub-project).

## Discover: Kick categories as a second row

`lib/views/discover_view.py` gains a second category-list control (a new
skin control id, distinct from the existing `301`-`308` range — read
`script-twitch-center-main.xml`'s current id layout fresh at implementation
time rather than assuming a specific free number here), populated from `providers.PROVIDERS["kick"]["get_top_categories"]`,
clearly labeled ("Kick Categories" vs the existing unlabeled Twitch row, or
both rows get labels — implementation detail). Selecting a Kick category
calls `providers.PROVIDERS["kick"]["get_live_streams"](category_id=...)`
and populates the same shared results list as Twitch's game-browse, with the
same `platform` tagging as Live Streams.

Per the confirmed decision, **rows stay separate, not merged** — Kick
categories and Twitch games are different taxonomies with no ID mapping;
presenting them as one interchangeable row would misrepresent that.

Discover's existing channel-name/game-name search toggle
(`SEARCH_MODE_TOGGLE_ID`) is untouched — Discover's search stays Twitch-only,
same as today. (Unified cross-platform search lives on the **Search**
screen, not Discover — see below. This spec doesn't merge Discover's
search, only its category browsing.)

## Search: merged results

`lib/views/search_view.py` currently searches only via
`lib.twitch.gql.search` (unauthenticated). Add a second, parallel call to
`providers.PROVIDERS["kick"]["search_channels"]` (which silently returns
`[]` if no Kick token is saved, per the provider-dispatch contract above),
merge both result lists — same viewer-count interleave as Live Streams —
and tag each rendered item with `platform` so `play_selected` dispatches
correctly. Both searches run on the existing background thread
(`search_task`), fired together, results merged once both return (or
whichever pattern `threading`/`_update_queue` already uses — extend it
rather than replace it).

**Asymmetry to document, not fix:** Twitch search works with no login;
Kick search requires a Kick login (Kick's API has no anonymous/app-token
path — confirmed during provider-core's spec work, User Access Tokens
only). A logged-out-of-Kick user's searches simply never surface Kick
results, with no error shown — consistent with the "Kick absence is
invisible" rule above.

## Playback wiring

`lib/windows/player.py`'s `play_stream` gains a `platform="twitch"` keyword
(default preserves every existing call site and test unmodified). When
`platform == "kick"`:

- Skip the entire `chat_overlay_enabled` branch outright — regardless of
  the setting's value, no `ChatOverlay`/`VariableChatOverlay` is
  constructed for a Kick stream (no Kick chat exists). Play through the
  plain `xbmc.Player().play(url, list_item)` path unconditionally.
- `RecoveryManager` (stall-recovery on ad breaks / URL expiry) currently
  hardcodes `lib.twitch.stream.resolve_stream_url` — this needs to become
  provider-aware too (route through `providers.PROVIDERS[platform]["resolve_stream_url"]`),
  since a Kick stream stalling and recovering must re-resolve via Kick's
  resolver, not Twitch's. `AdBreakState` itself is populated only by
  Twitch's EventSub ad-break events — for a Kick stream it simply never
  activates, which is already correct behavior (no code change needed
  there, just confirm `PlaybackWatchdog`'s stall threshold logic doesn't
  assume Twitch-only state).
- Callers (`LiveStreamsView._play_channel`, `DiscoverView._play_channel`,
  `SearchView.play_selected`) each already know which platform the selected
  item came from (the `platform` property tagged above); they pass it
  through, and use `providers.PROVIDERS[platform]["resolve_stream_url"]`
  instead of importing `lib.twitch.stream` directly.

## Settings

New entries in `resources/settings.xml` / `strings.po` (ids: next free after
`#30025`, confirmed fresh at implementation time the same way provider-core's
Task 9 had to correct its assumed ids):

- `kick_favorite_channels` — hidden string setting, JSON array, default `[]`.

(`kick_client_id`, `kick_client_secret`, `kick_redirect_port`, `kick_token`
already exist from provider-core — no changes needed there.)

## Testing

- `tests/test_providers.py` — new, covers the normalization/merge/interleave
  logic and the "missing token → empty result, no exception" contract for
  each wrapped function, plus the favorites JSON helpers. Mocks
  `lib.twitch.api`/`lib.kick.api` calls, no live network, same discipline as
  every existing test module.
- `tests/views/test_live_streams_view.py`,
  `tests/views/test_discover_view.py`, `tests/views/test_search_view.py`
  (extend existing files) — cover the merged-list rendering, platform
  tagging, and dispatch-on-selection behavior, injecting a fake
  `lib.providers` the same way existing tests inject fake chat/overlay
  classes.
- `tests/windows/test_player.py` (extend) — cover `platform="kick"` skipping
  the chat-overlay branch and routing recovery through the Kick resolver,
  alongside the existing Twitch-path tests (which must keep passing
  unmodified, since `platform` defaults to `"twitch"`).
- `tests/views/test_kick_login_view.py` — new, mirrors
  `tests/views/test_login_view.py`'s structure against `run_pkce_login`'s
  callback contract.
- `tests/test_addon_manifest.py` — extend to cover the new settings entries
  and skin group, same as every prior settings-adding task in this repo.

No live network calls anywhere in tests, consistent with the whole existing
suite.

## Risks / open items

- **Kick's playback-URL source is still unverified.** `lib/kick/stream.py`
  already carries a code comment (added during provider-core's final
  review) flagging that its `channel["stream"]["url"]` assumption
  contradicts `docs/kick-integration-notes.md`'s own research, with a
  documented fallback to the unofficial `SEARCH_BASE`-based endpoint. This
  spec does not resolve that — it's a blocking risk for this sub-project's
  actual playback step, and should be the first thing verified when
  implementation starts (a single manual API call against a real live Kick
  channel settles it before any UI code is written).
- **Per-favorite `get_channel` calls on every Live Streams load** could get
  slow with a large favorites list (no batch-by-slug endpoint confirmed).
  Acceptable for a first version; revisit if it's a real problem in
  practice.
- **Redirect URI / LAN-address handling for `KickLoginView`** needs
  confirming against how Kodi/the addon can discover its own LAN IP
  reliably across platforms (desktop dev machine vs. LibreELEC/kodi.local) —
  flagged in the Kick login section above, not fully resolved here.
- **Skin control id allocation** (new Discover category row, platform-badge
  image control, new group for Kick login, new Menu button) is described by
  purpose here, not by exact id, since `script-twitch-center-main.xml`'s
  current id layout should be read fresh at implementation time rather than
  guessed in this document (same lesson as provider-core's string-id
  collision).
