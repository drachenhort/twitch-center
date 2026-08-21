# Variable-Height Chat Overlay: Design

Date: 2026-08-22

## What this is

`lib/windows/chat_overlay.py`'s `ChatOverlay` renders chat via a Kodi `<list>` control with a fixed
per-row `itemlayout` (270px, sized to fit the maximum 5-line message - see
`docs/superpowers/specs/2026-08-18-eventsub-emote-rendering-design.md` and the v0.16.4/v0.16.5
CHANGELOG entries). Short messages (the common case) leave unused vertical space below their text
before the next row starts, since every row reserves the same fixed height regardless of actual
content.

This adds a second overlay implementation, `VariableChatOverlay`, that sizes each message's on-screen
space to its actual line count instead of a fixed maximum, built from individually placed Kodi
controls rather than Kodi's `<list>` item-recycling. It is opt-in via a new setting, and only ever
used when the EventSub chat engine is also selected.

Scope: **EventSub only, opt-in**. `ChatOverlay` (the existing fixed-box, `<list>`-based renderer)
is untouched and stays the default for both chat engines. A user must both select
`chat_engine=eventsub` and enable the new setting to see `VariableChatOverlay`. IRC users never see
a behavior change.

## Why this shape

**Kodi's `<list>` control cannot vary row height per item.** This was verified empirically before
writing this spec: a `<itemlayout condition="String.IsEqual(ListItem.Property(layout_size),small)">`
approach was implemented and tested live against a real Twitch channel - every row rendered at the
same (larger) size regardless of the per-item property. Cross-checking against Kodi's own bundled
Estuary skin confirms why: every real usage of `itemlayout condition="..."` in Estuary keys off
container/window-level state (`Container.Content(...)`, `Window.IsActive(...)`), never a per-row
`ListItem.Property`. The condition is evaluated once for the whole list, not per row. This rules out
any approach that keeps using the `<list>` control - variable height requires manual control
placement.

**Individually placed controls, not a single `<textbox>`.** A single auto-scrolling `<textbox>` with
all messages concatenated into one text blob (using `[COLOR]` tags for usernames) was considered and
would be substantially simpler - no manual position math, no eviction bookkeeping. It was rejected
because it cannot embed the per-message emote-image row, which must be kept (per-message emote images
were an explicitly requested requirement, see the EventSub emote rendering design). This is the
deciding factor that selects the heavier approach.

**Controls persist across render ticks; never destroyed and recreated wholesale.** `ChatOverlay`
already had to solve this once (see the incremental-rendering fix in the v0.16.2 CHANGELOG entry and
`lib/windows/chat_overlay.py`'s `_render()` comment): recreating a message's controls every render
tick re-triggers Kodi's async emote-art loading for messages already on screen, visible as emote
images popping in several renders after the message first appeared. `VariableChatOverlay` must
preserve this property - a message's controls are created once, then only ever repositioned
(`setPosition()`) or removed (`removeControl()`), never rebuilt while still visible.

**Reposition the whole visible column on every new message, not just on eviction.** The overlay must
keep matching today's visual behavior: newest message pinned to the bottom of the 960px column,
older messages pushed upward. Under a fixed-row `<list>`, Kodi did this shifting internally for free.
Under hand-placed controls, every visible block's Y must be recomputed and `setPosition()`-ed each
time a new message is appended, not only when something gets evicted. This is more per-tick work
than the `<list>`-based renderer, but the number of simultaneously visible blocks is small (order
10-20, since even at minimum message height several fit in 960px), so a full reposition pass every
throttled tick (existing `_RENDER_THROTTLE_SECONDS = 0.25`) is cheap.

## Architecture

`VariableChatOverlay` is a new sibling class in `lib/windows/chat_overlay.py` (or a new
`lib/windows/variable_chat_overlay.py` module - decided during implementation planning), reusing
`ChatOverlay`'s chat-client connection and pump-thread logic (constructor args, `onInit`,
`_pump_messages`, `close()` structure) but replacing the Kodi-`<list>`-based `_render()` with
hand-built control placement. The skin file gains no new controls for this - `VariableChatOverlay`
does not reference the skin's `<list id="101">` at all; it builds every control it needs directly in
Python via `self.addControl(...)`.

`lib/windows/player.py`'s `play_stream` selects between `ChatOverlay` and `VariableChatOverlay`:
after the existing EventSub-availability check (which can silently fall back `engine` to `"irc"` if
the broadcaster id can't be resolved), the variable-height renderer is chosen only when
`chat_display_mode` includes `"overlay"`, the new setting is enabled, **and** `engine == "eventsub"`
at that point - so a silent EventSub-to-IRC fallback still gets the normal fixed-box `ChatOverlay`,
never the variable one.

## Data flow

Python-side state, per `VariableChatOverlay` instance:

- `self._blocks`: ordered list of `{"controls": [...], "height": int}`, oldest first, mirroring
  `ChatOverlay._messages`'s eviction order.
- Each block's `controls` list holds the `xbmcgui.ControlLabel` (username), `ControlLabel` (message
  text, same `textwrap` + `_MAX_MESSAGE_LINES` wrapping as `ChatOverlay._build_message_item`), and
  0-6 `ControlImage` (emotes, same `_MAX_EMOTE_SLOTS` cap) built for that message.
- A block's `height` is computed once at creation: `24` (username row) + `line_count × <line-pitch
  constant>` (message row, sized to actual wrapped line count instead of the fixed 5-line
  allocation) + `28` (emote row) if the message has any emotes, else no emote-row addition.

Each throttled render tick (reusing `_RENDER_THROTTLE_SECONDS`):

1. **Build new blocks.** For every message that arrived since the last tick: wrap its text, compute
   its height, build its controls at a not-yet-final Y (corrected in step 2), `addControl()` them,
   append the block to `self._blocks`.
2. **Reposition pass.** Walk `self._blocks` newest-to-oldest with a cursor starting at the column's
   bottom edge (`y=960`, the list control's height in the current skin). For each block: cursor -=
   block height; call `setPosition()` (not recreate) on every control in that block, offsetting each
   control's fixed relative layout (username at block-top, message below it, emotes below that) by
   the cursor's Y. This runs even for blocks whose position didn't change, since the check-if-changed
   bookkeeping isn't worth it at this block count.
3. **Evict.** Once the cursor would go negative for a block, that block and every older one are
   off-screen: `removeControl()` every control in them and drop them from `self._blocks`.

`close()` (called from `_ChatAwarePlayer._teardown()`, same as today) must `removeControl()` every
control in every remaining block before calling `super().close()`, so controls don't leak into the
window if the overlay is closed mid-stream.

## Settings

New `Settings` field, e.g. `chat_overlay_variable_height` (default `False`), backed by a new
checkbox entry in `resources/settings.xml`. Always visible regardless of `chat_engine` (per prior
discussion, simpler than conditional `<visible>` logic in settings.xml), with help text noting it
only takes effect when the EventSub chat engine is also selected. Enabling it with `chat_engine=irc`
selected has no visible effect until the user also switches engines.

## Testing

- `tests/kodi_stubs/xbmcgui.py` gains `ControlLabel`/`ControlImage` stub classes (tracking position,
  size, label/art) and `WindowXMLDialog.addControl`/`removeControl` stubs that track a live control
  set on the fake window, mirroring the existing `ListItem`/list-control stub support.
- New `tests/windows/test_variable_chat_overlay.py`, parallel to `test_chat_overlay.py`, covering:
  - Block height computed correctly for 1-line, 3-line, and 5-line (truncated) messages, with and
    without emotes.
  - Newest message ends up at the bottom of the column; older messages positioned above it in order.
  - Once total block height exceeds the column height, the oldest block(s) are evicted
    (`removeControl` called, dropped from `self._blocks`).
  - A message still on screen across multiple render ticks keeps the *same* control objects
    (identity-checked) - only `setPosition()` is called on it, it is never rebuilt - verifying the
    emote-art-reload regression from v0.16.2 can't reappear here.
  - `close()` removes every remaining block's controls.
- Existing `test_chat_overlay.py` and `ChatOverlay` are untouched by this work - `VariableChatOverlay`
  is additive, not a modification of the existing class.

## Error handling / edge cases

- A single message taller than the entire 960px column (a pathological 5-line message at a small
  skin scale) must not be left stuck on screen forever or crash `addControl`/`setPosition` - if a
  lone newest block's height alone exceeds the column height, it is still shown (never evicted purely
  for being tall - it's the newest message), but every older block is evicted immediately to make
  room, same as the normal eviction path just triggered in one pass.
- Same threading caveat as `ChatOverlay._render()` today: this runs off the pump thread, calling GUI
  methods (`addControl`/`removeControl`/`setPosition`) directly, same as the existing renderer does
  via `control.addItems()`/`removeItem()`. Not a new risk, not newly mitigated - out of scope here.
- If `VariableChatOverlay` fails to construct or errors during `onInit` (e.g. a future Kodi build
  changes control-placement APIs), the failure mode should match `ChatOverlay`'s existing
  `_pump_messages` exception handling (log via `xbmc.log(..., xbmc.LOGERROR)`, don't crash the
  player) - no new error-handling design needed beyond reusing that pattern.
