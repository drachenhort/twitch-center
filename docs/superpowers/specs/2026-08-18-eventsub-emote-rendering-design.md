# Render EventSub Emotes as Images: Design

Date: 2026-08-18

## What this is

Chat messages from the EventSub engine (`lib/twitch/eventsub.py`) carry structured `fragments` data
that identifies which parts of a message's text are emotes - Twitch IRC never had this, and
`lib/windows/chat_overlay.py` currently discards it, rendering every message as plain wrapped text
regardless of engine. This adds a small row of real emote images beneath each message's text, sourced
from Twitch's public emote CDN.

Scope: **EventSub only**. `lib/twitch/irc.py`'s `ChatClient` keeps rendering plain text exactly as
today - IRC's raw-line emote data (a separate `emotes` IRCv3 tag with character-offset ranges into
the message, not fragment objects) is a different parsing job entirely and out of scope here. A user
on `chat_engine=irc` sees no change.

## Why this shape

**Text stays plain, images go in a strip below it, not inline.** Kodi's `WindowXMLDialog` label
controls render plain wrapped text only - there is no way to embed an image control mid-paragraph
inside a wrapped label, and Kodi skin item layouts are static per-row definitions (no per-item
dynamic control count). True inline positioning ("the emote sits between these two words") would
mean hand-rolling character-to-pixel layout math across the existing 26-char/5-line wrap
(`chat_overlay.py`'s `_MESSAGE_WRAP_WIDTH`/`_MAX_MESSAGE_LINES`) - a lot of fragile code for a
cosmetic win. A strip of emote icons on the line after the text is a well-understood pattern (several
real Twitch-overlay tools do exactly this), costs a fixed row of image controls in the skin, and
needs zero changes to the existing text-wrapping code.

**No image caching layer.** `lib/views/discover_view.py` and `lib/views/live_streams_view.py`
already pass remote thumbnail URLs straight to `xbmcgui.ListItem.setArt({"thumb": url})` - Kodi's own
texture manager fetches and caches remote-URL art transparently. Emote images use the same
mechanism (`setArt({"emote_0": url, ...})`), so there is nothing new to build or maintain for
fetching/caching.

**Fixed capped slot count, left-packed, no gap.** The skin's per-item layout is static, so a variable
number of emotes per message is handled with a fixed number of image-control "slots" (6) in the skin,
each bound to `ListItem.Art(emote_N)` for `N` in `0..5`. Python always fills slots contiguously from
`emote_0` (never leaves a hole before a later populated slot), and any slot beyond the message's
actual emote count gets no art at all - the skin hides an empty slot
(`<visible>!String.IsEmpty(ListItem.Art(emote_N))</visible>`), and since nothing else is positioned to
the right of the strip, a 2-emote message shows exactly 2 icons with no visible trailing gap. Capped
at 6 per message (mirrors this file's existing truncate-and-move-on style - the 5-line/`...`
message-length cap, the 50-message list cap).

**Static emote images only, dark theme, 1x scale.** Twitch's emote CDN
(`static-cdn.jtvnw.net/emoticons/v2/{id}/{format}/{theme_mode}/{scale}`) serves both `static` and
`animated` (GIF) formats, `light`/`dark` themes, and `1.0`/`2.0`/`3.0` scales. This uses
`static/dark/1.0` (28px native, matching the skin's 28px icon box with no upscale needed) - `dark`
matches the overlay's dark background, `static` avoids relying on Kodi's GIF-in-image-control support
being reliable, and `1.0` keeps the request small. Cheermote (Bits) fragments are a separate Twitch
endpoint with tiered images and are explicitly out of scope - a `cheermote`-type fragment's `text` is
still rendered as part of the plain message text (unchanged), just with no icon.

## Components

### `lib/twitch/eventsub.py`

New module-level constant and function, used by `_handle_payload`'s existing
`channel.chat.message` branch:

```python
EMOTE_IMAGE_URL_TEMPLATE = "https://static-cdn.jtvnw.net/emoticons/v2/{id}/static/dark/1.0"
_MAX_EMOTES_PER_MESSAGE = 6


def _extract_emotes(fragments):
    """Return up to _MAX_EMOTES_PER_MESSAGE {"id", "text", "url"} dicts, one per "emote"-type
    fragment in Twitch's channel.chat.message event.message.fragments list, in order. Never
    raises: a missing/non-list fragments value, or an individual fragment missing "type"/"id"/
    "emote", is treated as contributing no emote (skipped, not fatal) - matches this codebase's
    existing tolerant-parsing style elsewhere in the twitch/* package (e.g. irc.py's raid
    parsing). cheermote/mention/text fragments are not emotes and contribute nothing here; their
    text is already part of the message's plain text and needs no separate handling."""
    if not isinstance(fragments, list):
        return []
    emotes = []
    for fragment in fragments:
        if len(emotes) >= _MAX_EMOTES_PER_MESSAGE:
            break
        if not isinstance(fragment, dict) or fragment.get("type") != "emote":
            continue
        emote = fragment.get("emote")
        if not isinstance(emote, dict):
            continue
        emote_id = emote.get("id")
        if not emote_id:
            continue
        emotes.append({
            "id": emote_id,
            "text": fragment.get("text", ""),
            "url": EMOTE_IMAGE_URL_TEMPLATE.format(id=emote_id),
        })
    return emotes
```

The `"message"` event dict built in `_handle_payload` (currently `{"type": "message", "username",
"display_name", "text", "timestamp"}`) gains one more key:

```python
"emotes": _extract_emotes(event.get("message", {}).get("fragments")),
```

`irc.py`'s message events are untouched and never gain an `"emotes"` key - `chat_overlay.py` treats
its absence as "no emotes" (see below), not as an error.

### `lib/windows/chat_overlay.py`

`_build_message_item` (currently builds an `xbmcgui.ListItem` with `setLabel`/`setLabel2` for
username/wrapped-text) additionally sets art for however many emotes the event has, capped at 6
(defensive re-cap here too, even though `eventsub.py` already caps - `_build_message_item` must not
assume its caller enforced the limit):

```python
_MAX_EMOTE_SLOTS = 6


def _build_message_item(event):
    item = xbmcgui.ListItem(event["display_name"])
    lines = textwrap.wrap(event["text"], _MESSAGE_WRAP_WIDTH)
    if len(lines) > _MAX_MESSAGE_LINES:
        lines = lines[:_MAX_MESSAGE_LINES]
        lines[-1] = lines[-1][: max(0, _MESSAGE_WRAP_WIDTH - 3)].rstrip() + "..."
    item.setLabel2("\n".join(lines))
    emotes = event.get("emotes", [])[:_MAX_EMOTE_SLOTS]
    if emotes:
        item.setArt({"emote_%d" % i: emote["url"] for i, emote in enumerate(emotes)})
    return item
```

Slots beyond `len(emotes)` are left with no art at all (never explicitly cleared to `""`) - the
skin's per-slot `<visible>!String.IsEmpty(ListItem.Art(emote_N))</visible>` binding hides an
unset slot the same as an explicitly-empty one, and `xbmcgui.ListItem` art defaults to unset, so
there is nothing to clean up between items in the same list (each row gets a fresh `ListItem`).

### `resources/skins/Default/1080i/script-twitch-center-chat-overlay.xml`

The message list's `itemlayout`/`focusedlayout` (currently `height="165"`, containing the username
label at `posy=0` and the wrapped-text label at `posy=26 height=140`) grow to `height="197"` to fit
a new row of 6 fixed 28x28 image controls at `posy=168`, spaced 30px apart starting at the same
`posx=10` left margin the text uses, matching the existing duplicated-block-per-layout pattern this
file already uses (no skin includes/templates in this codebase):

```xml
<control type="image" id="110">
  <posx>10</posx>
  <posy>168</posy>
  <width>28</width>
  <height>28</height>
  <aspectratio>keep</aspectratio>
  <texture>$INFO[ListItem.Art(emote_0)]</texture>
  <visible>!String.IsEmpty(ListItem.Art(emote_0))</visible>
</control>
<!-- repeated for id="111".."115", posx 40/70/100/130/160, emote_1".."emote_5" -->
```

Both `itemlayout` and `focusedlayout` get the full set of 6 controls (matching the file's existing
practice of duplicating each control between the two layouts rather than sharing one definition).
Control ids `110`-`115` are new and don't collide with the existing `101` (the list itself).

Growing the item height from 165 to 197 reduces how many messages fit on screen at once within the
list's existing `height="960"` - an accepted, unavoidable side effect of adding a row, not a
regression to guard against.

## Data flow

```
eventsub notification (channel.chat.message)
  -> _handle_payload extracts event["message"]["fragments"]
     -> _extract_emotes(fragments) -> [{"id","text","url"}, ...] (capped at 6, [] on empty/malformed)
  -> enqueued message event: {..., "emotes": [...]}
consumer (chat_overlay.ChatOverlay._pump_messages, unchanged)
  -> _build_message_item(event)
     -> setLabel/setLabel2 exactly as today
     -> setArt({"emote_0": url, ...}) for however many emotes (0-6), left-packed from slot 0
skin itemlayout
  -> username label, wrapped-text label (unchanged)
  -> 6 image controls, each visible only if its ListItem.Art(emote_N) is non-empty
     -> Kodi's texture manager fetches/caches the remote CDN URL itself (no addon-side fetch/cache code)
```

## Error handling

- Malformed/missing `fragments` (unexpected Twitch API shape, or absent entirely) -> `_extract_emotes`
  returns `[]`, never raises - the message still renders as plain text, exactly as it would if this
  feature didn't exist.
- A fragment missing `type`/`id`/`emote` is skipped individually, not treated as a fatal error for
  the whole message.
- A broken/404 CDN image URL is Kodi's problem: the image control renders blank, no crash, no
  addon-side handling needed (same as any other remote-URL art already used in this codebase).
- IRC engine: `event.get("emotes", [])` in `_build_message_item` means an IRC message event (which
  never has an `"emotes"` key) behaves identically to a zero-emote EventSub message - no special
  casing needed to keep IRC unaffected.

## Testing

`tests/twitch/test_eventsub.py` additions:

- `_extract_emotes` unit tests (no threading, no sockets): a fragments list with one `"emote"`
  fragment -> one-entry list with the right `id`/`text`/`url`; a text-only message (no emote
  fragments) -> `[]`; a mix of `text`/`mention`/`cheermote`/`emote` fragments -> only the `emote`
  ones contribute entries, in order; a fragments list with 8 emotes -> capped at 6; a fragment
  missing `"emote"` or with `emote["id"]` missing/falsy -> skipped, not raised; `fragments` itself
  `None`/not-a-list -> `[]`.
- Extend the existing `channel.chat.message`-notification `ChatClient` test (or add a sibling) to
  assert the emitted `"message"` event's `"emotes"` key matches `_extract_emotes`'s output for a
  fragments payload included in the fake notification frame.

`tests/windows/test_chat_overlay.py` additions:

- `_build_message_item` tests: an event with no `"emotes"` key -> `setArt` never called (or called
  with `{}` - assert whichever `_build_message_item` actually does, don't assume); an event with
  1 emote -> `setArt({"emote_0": url})`; an event with 6 emotes -> all six slots set; an event with
  8 emotes -> only `emote_0`..`emote_5` set (defensive re-cap, independent of `eventsub.py`'s own
  cap).

`tests/test_addon_manifest.py` additions (extends the file's existing pattern of parsing
`script-twitch-center-chat-overlay.xml` and asserting control ids/structure, e.g.
`test_chat_overlay_skin_xml_declares_message_list_control_id`):

- A new test asserting both `itemlayout` and `focusedlayout` each contain exactly 6 `image`
  controls with ids `110`-`115`, each with a `texture` referencing `ListItem.Art(emote_N)` matching
  its index and a `visible` condition referencing the same `emote_N` key.
- No test asserts pixel positions/visual layout - that stays unverified by automation, same as
  every other skin file in this codebase; live testing (per this repo's Kodi-testing conventions)
  is how the actual on-screen result gets checked.

## Out of scope for this task

- IRC engine emote rendering (would need parsing IRC's `emotes` tag's character-offset-range
  format - unrelated parsing code, a separate follow-up if ever wanted).
- Inline (mid-text) emote positioning - the strip-below-text layout is the shipped shape; revisit
  only if Kodi's label control model changes in a way that makes true inline rendering tractable.
- Cheermote (Bits) images - `cheermote`-type fragments render as plain text (their `.text` field,
  already part of the message), no icon.
- Animated emotes - `static` format only.
- More than 6 emotes shown per message - silently capped, no "+N more" indicator.
- A `chat_engine=irc`-visible difference of any kind - this task changes zero behavior for IRC.
