# Top Categories grid - design

Date: 2026-11-18
Status: approved 2026-11-18

## Intent

Discover's Twitch "top games" row is a horizontal, text-only strip of 20
names. On a TV remote it is hard to browse: you scroll sideways one item
at a time, with no cover art to recognise a category at a glance. The user
wants a full-screen box-art grid of Twitch's top categories that is easy to
move through with up/down/left/right, where picking a category shows its
live streams.

## Goals

- A full-screen grid of Twitch's top 100 categories, ranked by viewers, as
  box-art tiles with the category name under each.
- Picking a tile opens a page with that category's live streams. Picking a
  stream plays it, the same as everywhere else.
- Back from the streams page returns to the grid with focus on the same tile.
- Reached from Discover.

## Non-goals

- Kick categories. The Kick row on Discover stays as it is. Kick's
  `/public/v2/categories` order is not known to be popularity-ranked.
- Viewer counts per category. Helix `/games/top` doesn't return them, and
  computing them costs one call per category.
- Pagination past 100 categories.
- Changes to Discover's search.

## Anti-goals

- Sideways-only navigation, or any layout that recreates the long-strip
  problem.
- Losing the user's place in the grid after they look at a category's
  streams.

## Approaches considered

- **A (picked): two new views.** A `top_categories` grid view and a
  `category_streams` view, following the existing two-level
  `vod_clips_channels` then `vod_clips` pattern. It costs two views and two
  skin groups, and it is the only option that fixes remote browsing fully
  and keeps your place on Back.
- **B: grid view that fills Discover's results panel.** Less code, but Back
  from the streams lands on Discover rather than the grid, so the user loses
  their place.
- **C: upgrade the existing Discover row in place.** Cheapest, but it stays
  a sideways strip, which is the core complaint.

## Design

### Data

- `lib/twitch/api.py:get_top_games` keeps its signature but also returns
  `box_art_url` for each game. Helix returns a template URL with
  `{width}x{height}` placeholders. Fill it with a fixed size suited to the
  tile, for example 285x380 (Twitch's own 3:4 aspect). Existing callers
  ignore the extra key.
- The grid view calls it with `first=100`.
- The streams view reuses `api.get_live_streams_by_game(game_id)` and
  `view_utils.build_stream_item`, as Discover does today.

### Views and navigation

- **Discover:** the Twitch top-games text row (control 305 and its heading)
  is replaced by a single "Browse Categories" button that switches to
  `top_categories`. The Kick categories row, search and results panel are
  unchanged. *My call:* the grid makes the 20-name text row redundant, and
  removing it frees vertical space. The user can ask to keep it.
- **`top_categories` view:** `BACK_TARGET = "discover"`. It shows a title,
  the grid, an empty label and an error label. On activate it loads the top
  100 categories and focuses the grid. When it is re-entered from the
  streams page it restores focus to the last selected position and does not
  refetch if it already has data. On click it switches to
  `category_streams` with context `{"game_id", "game_name"}`.
- **`category_streams` view:** `BACK_TARGET = "top_categories"`. It shows the
  category name as the title, then a streams panel laid out like Discover's
  results panel, plus empty and error labels. Clicking a stream plays it
  through the same playback path Discover uses. Context-menu handling
  matches Discover's results (favorites and the rest), where that applies.
- Both views follow the existing conventions: `_safe_control`,
  `DEFAULT_FOCUS_ID`, and `TokenExpiredError` handling with refresh-and-retry
  and the relogin message. Both are registered in `MainWindow` with their own
  `GROUP_IDS` entry.

### Skin

- New groups in `script-twitch-center-main.xml` for both views, using unused
  ID ranges.
- The grid is a `panel` with vertical scrolling and about 6 columns at
  1080p. Each tile is a cover image about 230x307 (3:4) with the name label
  below it, and focus shows a highlight frame like other tiles in the skin.
  Plain hex colours only (see the `$VAR` limitation memory).
- The streams panel copies Discover's results panel item layout.

### Errors and empty states

- No token or expired token: same messages and relogin flow as Discover.
- Network failure: an error label in the view, logged with an
  `script.twitch.center:` prefix.
- No categories, or no live streams in a category: an empty label ("No
  categories right now." / "Nobody's live in this category right now.").

### Release

- Minor version bump to 0.32.0 in `addon.xml`, a `CHANGELOG.md` entry and a
  dated `<news>` line, all in the same commit as the feature.
- Tests under `tests/views/` for both views (load, empty, error, token
  refresh, click-through context, focus restore), and for the
  `get_top_games` box-art change under `tests/twitch/`.

## Left to the builder

- Exact control IDs, pixel sizes and colours, within the constraints above.
- Whether Discover's playback and context-menu helpers get shared through
  `lib/views/utils.py`, or `category_streams` reuses them some other way.
  Don't copy-paste large blocks.
- Whether the grid caches its list for the rest of the session or only
  until Discover is re-entered.
