"""Variable-height chat overlay: an opt-in, EventSub-only alternative to ChatOverlay.

ChatOverlay reserves the same fixed-height slot (skin <itemlayout>) for every message, sized
for the worst case (5 wrapped lines) - see chat_overlay.py's _MAX_MESSAGE_LINES and the
v0.16.4/v0.16.5 CHANGELOG entries. VariableChatOverlay instead sizes each message's on-screen
space to its actual wrapped line count, by placing xbmcgui controls directly rather than using
Kodi's <list> control (which can't vary row height per item - see
docs/superpowers/specs/2026-08-22-variable-height-chat-overlay-design.md for why)."""
import xbmcgui

from lib.windows.chat_overlay import _MAX_EMOTE_SLOTS, _wrap_message_lines

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
# Offset from a message block's top to its message-text row, matching the skin's label2 posy=26.
_USERNAME_ROW_HEIGHT = 26
# Skin px per wrapped message line - same value ChatOverlay's fixed label2 box is sized from
# (210px / 5 lines; see the v0.16.5 CHANGELOG entry for how it was measured against live
# rendering on a real Kodi build).
_LINE_PITCH = 42
_EMOTE_ROW_HEIGHT = 28
_EMOTE_SIZE = 28
_EMOTE_X_OFFSETS = (10, 40, 70, 100, 130, 160)


def _block_height(line_count, has_emotes):
    height = _USERNAME_ROW_HEIGHT + line_count * _LINE_PITCH
    if has_emotes:
        height += _EMOTE_ROW_HEIGHT
    return height


def _build_block(event):
    """Build one message's controls at a placeholder y=0 - _position_block() sets the real
    position once the block's place in the column is known."""
    lines = _wrap_message_lines(event["text"])
    emotes = [
        emote for emote in (event.get("emotes") or [])[:_MAX_EMOTE_SLOTS] if emote.get("url")
    ]
    message_height = len(lines) * _LINE_PITCH
    height = _block_height(len(lines), has_emotes=bool(emotes))

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
