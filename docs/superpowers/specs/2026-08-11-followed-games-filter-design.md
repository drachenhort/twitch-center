# Followed Games Filter Row: Design

Date: 2026-08-11

## What this is

Adds a row of the user's real followed games (Twitch's own "Kategorien" under "Du folgst", not an
approximation) above the Home screen's channel list. Selecting a game filters the channel list to
live followed channels playing it; an "All" entry (default-selected) clears the filter.

## Why this needs an unofficial API call

Twitch's public Helix API has no endpoint for a user's followed games — the private REST API that
exposed this was shut down in 2019 (confirmed via search, no Helix replacement exists). Twitch's
own website still shows this list, backed by its internal GraphQL API
(`https://gql.twitch.tv/gql`) — the same "unofficial, same risk tier as the GQL/usher playback
resolution already planned for `lib/twitch/stream.py`" category the original scaffold spec
anticipated. This is best-effort by design: if Twitch changes the persisted-query hash or response
shape, the games row silently disappears rather than breaking the rest of Home.

## How the request was verified

Captured directly from Twitch's own web client (not guessed) by hooking `fetch`/`XMLHttpRequest` in
a real logged-in browser session on `twitch.tv/directory/following/games` and triggering an
in-app (client-side-routed) refetch of that tab:

- **Operation name:** `FollowingGames_CurrentUser`
- **Persisted query hash:** `f3c5d45175d623ed3d5ff4ca4c7de379ea6a1a4852236087dc1b81b7dbfd3114`
- **Variables:** `{"limit": 100, "type": "LIVE"}`
- **Endpoint:** `POST https://gql.twitch.tv/gql`
- **Auth:** `Client-Id: kimne78kx3ncx6brgo4mv6wki5h1ko` (Twitch's public web client ID, not our
  registered Helix `client_id`) — community-documented pattern for authenticated Twitch GQL calls
  is `Authorization: OAuth <access_token>` using the user's own token (our existing device-code
  token, scope `user:read:follows`, already covers reading follow data).

`type: "LIVE"` matches this feature's actual need — only followed games with currently-live
viewers are relevant for a "filter to what's live right now" row — so no further investigation into
other possible `type` values was needed (confirmed with you directly).

**Known limitation — response shape is unverified.** Capturing the actual JSON response was
blocked (replaying the authenticated call via injected JS was refused by a safety classifier, as a
reasonable precaution against scripted use of session credentials). The response field names below
(`data.currentUser.followedGames.nodes[].{id,name,displayName}`) are inferred from Twitch's typical
GraphQL naming conventions used elsewhere in community documentation, **not independently
confirmed**. Parsing must be defensive — any `KeyError`/`TypeError`/`IndexError`/`ValueError` while
walking the response results in an empty list, so a wrong guess degrades to "games row doesn't
show" rather than crashing. This is consistent with the already-approved best-effort posture and
should be corrected against a real captured response the first time this is manually verified in
practice (e.g., during the real-Kodi verification pass this plan will need before merge).

## Components

### `lib/twitch/gql.py` (new)

Separate from `lib/twitch/api.py` (official Helix) — different client ID, different trust tier,
matches the original scaffold's intended split between "official" and "unofficial/GQL" surfaces.

- `GQL_URL = "https://gql.twitch.tv/gql"`
- `WEB_CLIENT_ID = "kimne78kx3ncx6brgo4mv6wki5h1ko"`
- `get_followed_live_games(access_token, limit=100) -> list[dict]` — POSTs the persisted query
  above. Returns `[{"id": ..., "name": ..., "displayName": ...}, ...]` on success. Returns `[]` on
  *any* failure: network error, non-200 response, or the response not matching the expected shape.
  Never raises — this function's entire contract is "best-effort, empty list on any doubt."

### `lib/windows/home.py` (extended)

- `onInit` (or `_load_and_populate`) additionally calls `gql.get_followed_live_games(token["access_token"])`
  after the existing followed-channels/live-status fetch succeeds. This call's failure is NOT
  treated as a Home-screen error — an empty games list just means the games row doesn't render;
  the channel list still populates normally from the existing official-Helix data path.
- Fetched followed/live/games data is cached on `self` (e.g. `self._live`, `self._followed`,
  `self._games`) so selecting a game re-filters in-memory rather than refetching from Twitch.
- New games-row list control (`GAMES_LIST_ID`) populated with "All" (default-selected) plus one
  `ListItem` per followed live game (label = `displayName`, a `game_name` property storing `name`
  for matching against stream data's `game_name` field from Helix).
- `onAction` gains handling for `ACTION_SELECT_ITEM` while focused on the games list: reads the
  selected item, re-runs channel-list population with that game as a filter (or clears the filter
  for "All"). Filtering operates on already-cached `self._followed`/`self._live` — matches stream
  `game_name` against the selected game's `name`.
- Filtering only affects the live portion of the channel list (offline channels have no known
  current game) — selecting a specific game hides the offline section entirely while filtered;
  selecting "All" restores the full live+offline list as today.

### Skin XML

New horizontal list control above the existing channel list (window reflows: title → games row →
channel list, each shifted down/height-adjusted to fit within the existing 1920×1080 layout).
Item layout is text-only (game `displayName`) — box art would need a separate Helix `/games` call
per `game_id`, out of scope here.

## Data flow

```
HomeWindow._load_and_populate
  -> api.get_followed_channels(...) -> api.get_live_status(...)   [existing, official, must succeed]
  -> gql.get_followed_live_games(access_token)                     [new, best-effort, [] on failure]
  -> cache followed/live/games on self
  -> populate games row (All + games, "All" selected)
  -> populate channel list (unfiltered)

User selects a game in the games row (ACTION_SELECT_ITEM, focus == games list)
  -> re-populate channel list filtered to live channels whose game_name matches the selected game
User selects "All"
  -> re-populate channel list unfiltered (as today)
```

## Error handling

- `gql.get_followed_live_games` network/HTTP/parse failure: returns `[]`, games row simply doesn't
  appear. No error message shown for this specifically — it's decoration, not a core feature; a
  visible error here would be noisy for something expected to be best-effort/fragile.
- This call is NOT retried, NOT subject to the existing `TokenExpiredError`/refresh machinery
  (that's Helix-specific; a 401-equivalent failure from the GQL endpoint just falls into the
  generic `[]`-on-any-failure path). If the user's token is expired, both the official Helix calls
  AND this call would fail around the same time — the existing refresh-then-reprompt flow already
  handles the Helix side; the games row will simply also come back empty until the user is
  logged in with a valid token again, no separate handling needed.

## Testing

- `lib/twitch/gql.py`: tested with mocked `requests` — success (a synthetic response matching the
  assumed shape), 401/non-200, network error, and a response that doesn't match the assumed shape
  (missing keys) — all should return `[]`, never raise.
- `lib/windows/home.py`: games-row population and the select-to-filter/select-All-to-clear behavior
  tested via `tests/kodi_stubs/`, with `gql.get_followed_live_games` injected/faked (no real
  network). Covers: games row populated correctly, selecting a game filters the channel list to
  matching live channels only, selecting "All" restores the full list, and `gql` returning `[]`
  (simulating its failure) still lets the rest of Home populate normally.
- No test hits Twitch's real API (neither Helix nor GQL).

## Out of scope for this task

- Verifying/correcting the GQL response field names against a real captured response (deferred to
  manual real-Kodi verification, per the "Known limitation" section above).
- Game box art in the games row (text-only for now).
- Any `type` value other than `"LIVE"` (e.g. a hypothetical full followed-games list including
  offline-followed games) — not needed for this feature's scope.
- Filtering by anything other than the games row (e.g. free-text search) — that's the
  already-deferred Discover screen.
