# Show Offline Channels Setting: Design

Date: 2026-08-12

## What this is

A small opt-in toggle reversing part of the "stop showing offline channels" change: a new
`show_offline_channels` setting lets a user bring offline followed channels back into Home's
channel list, for anyone who preferred seeing their full followed list rather than only live ones.

## Scope decisions (from brainstorming)

- Default `false` (off) — matches what's already shipped; nobody's Home view changes unless they
  opt in.
- When on, offline channels reappear exactly as they used to before the earlier change: appended
  after the live ones, sorted alphabetically — `_merge_channels`'s offline half already computes
  this and is currently discarded (`live, _offline = _merge_channels(...)`), so this is restoring
  use of existing logic, not writing new sorting/filtering.
- Selecting an offline entry still no-ops either way — unrelated to this setting, gated by
  `is_live` at click time, unchanged.

## Components

### `resources/settings.xml` (extended)

New setting, same category/group as `chat_display_mode`:

```xml
<setting id="show_offline_channels" type="boolean" label="30009">
  <level>0</level>
  <default>false</default>
  <control type="toggle"/>
</setting>
```

### `resources/language/resource.language.en_gb/strings.po` (extended)

New string id `30009`: `"Show offline channels on Home"`.

### `lib/settings.py` (extended)

New property on `Settings`, following the existing `chat_display_mode` property's pattern:

```python
    @property
    def show_offline_channels(self):
        return self._addon.getSettingBool("show_offline_channels")
```

### `lib/windows/home.py` (extended)

- `_build_list_item(channel, stream_data=None)` — restore the optional-`stream_data` branch it had
  before the earlier change (offline: `"Offline"` label2, no thumbnail, `is_live` `"false"`), since
  offline items need building again.
- `HomeWindow._populate`: read `Settings().show_offline_channels`; when `true`, append
  `_build_list_item(channel)` for each offline channel after the live items (skip entirely when
  `game_filter` is set, matching the existing behavior where filtering by game only makes sense
  against live channels — an offline channel has no `game_name` to filter on).
- `HomeWindow.__init__` gains a `settings_cls`-style injection point (`settings=None` constructor
  param defaulting to `Settings()`), matching `player.play_stream`'s existing DI convention, so
  tests can control the setting without touching real `xbmcaddon`.

## Data flow

```
HomeWindow._populate(followed, live_list, game_filter=None)
  -> live, offline = _merge_channels(followed, live_list)
  -> apply game_filter to live (unchanged)
  -> items = [live items...]
  -> if settings.show_offline_channels and game_filter is None:
       items += [_build_list_item(channel) for channel in offline]
  -> control.addItems(items)
```

## Error handling

Nothing new — `getSettingBool` on a never-set setting returns the schema default (`false`) per
Kodi's own settings API, no extra handling needed, matching how `chat_display_mode` already relies
on Kodi/the `Settings` wrapper for its own default.

## Testing

- `lib/settings.py`: `Settings.show_offline_channels` tested against the existing
  `tests/kodi_stubs/xbmcaddon.Addon` stub (confirm `getSettingBool` round-trips true/false/unset →
  false).
- `lib/windows/home.py`: `_build_list_item` regains a test for the offline (`stream_data=None`)
  branch, mirroring the one removed in the earlier change. `_populate`/`onInit` tests: with the
  setting off (default), behavior is unchanged from today (existing tests already cover this,
  should need no edits); with the setting on, a new test asserts offline channels appear after live
  ones, alphabetically sorted, is_live=false; a test with both the setting on AND a `game_filter`
  set confirms offline channels are still excluded (game filter takes priority).
- No test hits Twitch's real API or Kodi's real settings dialog.

## Out of scope

- No settings-page change beyond this one new toggle.
- No change to Discover's results list (this addon's "offline" concept doesn't apply there — search
  results already show/hide via their own `is_live` logic, untouched).
