"""Variable-height chat overlay: an opt-in, EventSub-only alternative to ChatOverlay.

ChatOverlay reserves the same fixed-height slot (skin <itemlayout>) for every message, sized
for the worst case (5 wrapped lines) - see chat_overlay.py's _MAX_MESSAGE_LINES and the
v0.16.4/v0.16.5 CHANGELOG entries. VariableChatOverlay instead sizes each message's on-screen
space to its actual wrapped line count, by placing xbmcgui controls directly rather than using
Kodi's <list> control (which can't vary row height per item - see
docs/superpowers/specs/2026-08-22-variable-height-chat-overlay-design.md for why)."""
import textwrap
import xbmcgui

from lib.windows.chat_overlay import ChatOverlay, _MAX_EMOTE_SLOTS, _MESSAGE_WRAP_WIDTH

# VariableChatOverlay allows longer messages than the fixed-box ChatOverlay.
_MAX_MESSAGE_LINES = 9

def _wrap_message_lines(text):
    lines = textwrap.wrap(text, _MESSAGE_WRAP_WIDTH)
    if len(lines) > _MAX_MESSAGE_LINES:
        lines = lines[:_MAX_MESSAGE_LINES]
        lines[-1] = lines[-1][: max(0, _MESSAGE_WRAP_WIDTH - 3)].rstrip() + "..."
    return lines

# Column geometry, matching resources/skins/Default/1080i/script-twitch-center-chat-overlay.xml's
# <list id="101"> position/size - this overlay doesn't use that control, but keeps the same
# on-screen footprint so it's a drop-in visual replacement.
_COLUMN_X = 1500
_COLUMN_Y = 60
_COLUMN_WIDTH = 380
_COLUMN_HEIGHT = 960

_FONT = "font13"
_USERNAME_HEIGHT = 24
_USERNAME_COLOR = "ff9146ff"
# Offset from a message block's top to its message-text row. Deliberately larger than
# ChatOverlay's skin-declared label2 posy=26: this renderer places controls directly rather
# than through a skin-parsed <list> control, and live testing (see CHANGELOG) found real text
# renders taller on some Kodi builds/platforms than on others even at the same declared font
# size, enough to overlap adjacent message blocks when using tight spacing. Because each
# block's position is computed from the cumulative height of the blocks above it (unlike
# ChatOverlay's independently-sized fixed rows), any per-line underestimate compounds across
# the handful of blocks simultaneously visible - so these constants carry a large deliberate
# margin rather than the tightest value that worked on any single device.
_USERNAME_ROW_HEIGHT = 40
# Generously-padded skin px per wrapped message line - see _USERNAME_ROW_HEIGHT for why this
# is padded well past the tightest value measured on any one Kodi build. Trimmed 60->44
# (2026-08-25, live-tested on kodi.local) after the original margin left a visible trailing
# blank-line gap below short/single-line messages - still padded above the tightest value seen,
# not shrunk to it.
_LINE_PITCH = 44
_EMOTE_ROW_HEIGHT = 36
_EMOTE_SIZE = 28
_EMOTE_X_OFFSETS = (10, 40, 70, 100, 130, 160)
# Extra fixed padding added to every block's height on top of its content, as a further
# cross-build safety margin against the compounding-overlap failure mode above. Trimmed 34->16
# alongside _LINE_PITCH above, same reasoning.
_BLOCK_MARGIN = 16


def _block_height(line_count, has_emotes):
    height = _USERNAME_ROW_HEIGHT + line_count * _LINE_PITCH + _BLOCK_MARGIN
    if has_emotes:
        height += _EMOTE_ROW_HEIGHT
    return height


def _message_metrics(event):
    """Wrapped lines, filtered emotes, and resulting block height for a message - computed
    once and shared between the eviction-cutoff pre-pass and _build_block, so a message's
    height is never calculated one way for the cutoff decision and another way for the
    control actually built."""
    lines = _wrap_message_lines(event["text"])
    emotes = [
        emote for emote in (event.get("emotes") or [])[:_MAX_EMOTE_SLOTS] if emote.get("url")
    ]
    return lines, emotes, _block_height(len(lines), has_emotes=bool(emotes))


def _build_block(event, lines, emotes, height):
    """Build one message's controls at a placeholder y=0 - _position_block() sets the real
    position once the block's place in the column is known. lines/emotes/height come from
    _message_metrics(event), computed by the caller as part of the eviction-cutoff decision."""
    message_height = len(lines) * _LINE_PITCH

    items = []
    username_label = xbmcgui.ControlLabel(
        _COLUMN_X + 10, 0, _COLUMN_WIDTH - 20, _USERNAME_HEIGHT,
        event["display_name"], font=_FONT, textColor=_USERNAME_COLOR,
    )
    items.append((username_label, _COLUMN_X + 10, 0))

    message_label = xbmcgui.ControlLabel(
        _COLUMN_X + 10, 0, _COLUMN_WIDTH - 20, message_height,
        "\n".join(lines), font=_FONT,
    )
    items.append((message_label, _COLUMN_X + 10, _USERNAME_ROW_HEIGHT))

    emote_rel_y = _USERNAME_ROW_HEIGHT + message_height
    for i, emote in enumerate(emotes):
        image = xbmcgui.ControlImage(
            _COLUMN_X + _EMOTE_X_OFFSETS[i], 0, _EMOTE_SIZE, _EMOTE_SIZE, emote["url"],
            aspectRatio=2,
        )
        items.append((image, _COLUMN_X + _EMOTE_X_OFFSETS[i], emote_rel_y))

    return {"items": items, "height": height}


def _block_controls(block):
    return [control for control, _x, _rel_y in block["items"]]


def _position_block(block, top_y):
    for control, x, rel_y in block["items"]:
        control.setPosition(x, top_y + rel_y)


class VariableChatOverlay(ChatOverlay):
    """Opt-in alternative renderer - see module docstring. Reuses ChatOverlay's chat-client
    connection and pump-thread scaffolding (__init__/onInit/_pump_messages, and close()'s
    cancel/disconnect steps), overriding only _render() (and extending close()) to place
    controls by hand instead of using the skin's <list> control."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._blocks = []
        self._blocks_built = 0

    def _render(self):
        # self._total_evicted + len(self._messages) is the total number of messages ever
        # appended (ChatOverlay._pump_messages trims self._messages to the last _MAX_MESSAGES,
        # tracking how many were dropped in _total_evicted) - comparing that running total
        # against how many we've already turned into blocks tells us what's new, without
        # re-scanning messages we've already built controls for.
        total_seen = self._total_evicted + len(self._messages)
        new_count = total_seen - self._blocks_built
        new_events = self._messages[-new_count:] if new_count > 0 else []

        new_metrics = [_message_metrics(event) for event in new_events]

        # Find the eviction cutoff across existing blocks + not-yet-materialized new messages
        # together (oldest-to-newest, matching self._messages order), BEFORE creating any new
        # controls for the new messages. This matters: if several messages arrive in one
        # throttled tick and together they overflow the column, building a control for one
        # that this same call would then immediately evict again (addControl followed by
        # removeControl within one _render() call) can leave an orphaned control behind on at
        # least one tested Kodi build/platform - Kodi's addControl() appears to complete
        # asynchronously there, so the same-tick removeControl() can run before the add has
        # actually taken effect, leaving a control nothing references rendered at its stale
        # creation position. Visible as garbled text blended from a message that was supposed
        # to have been evicted. Skipping control creation entirely for messages that would be
        # evicted in this same tick avoids ever hitting that add-then-remove pattern. See
        # CHANGELOG for the live-testing history behind this.
        combined_heights = [block["height"] for block in self._blocks] + [
            height for _lines, _emotes, height in new_metrics
        ]
        cursor = _COLUMN_HEIGHT
        keep_from = len(combined_heights)
        for i in range(len(combined_heights) - 1, -1, -1):
            cursor -= combined_heights[i]
            if cursor < 0 and keep_from != len(combined_heights):
                break
            keep_from = i

        existing_count = len(self._blocks)
        evict_existing = min(keep_from, existing_count)
        for evicted in self._blocks[:evict_existing]:
            for control in _block_controls(evicted):
                self.removeControl(control)
        self._blocks = self._blocks[evict_existing:]

        skip_new = max(0, keep_from - existing_count)
        for event, (lines, emotes, height) in zip(new_events[skip_new:], new_metrics[skip_new:]):
            block = _build_block(event, lines, emotes, height)
            for control in _block_controls(block):
                self.addControl(control)
            self._blocks.append(block)

        # Position every surviving block, newest at the bottom - eviction already decided who
        # survives, so this pass never needs to remove anything.
        cursor = _COLUMN_Y + _COLUMN_HEIGHT
        for block in reversed(self._blocks):
            cursor -= block["height"]
            _position_block(block, cursor)

        self._blocks_built = total_seen

    def close(self):
        for block in self._blocks:
            for control in _block_controls(block):
                self.removeControl(control)
        self._blocks = []
        super().close()
