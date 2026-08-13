# Material-styled stream browser for twitch-center

## What's here

```
resources/skins/Default/1080i/colors.xml       Material 3 dark color tokens
resources/skins/Default/1080i/Font.xml          Roboto-based type scale
design/StreamBrowser.xml                        Card-grid window definition
```

## Wiring it up in Python

Custom windows are opened via `xbmcgui.WindowXMLDialog` (or `WindowXML` if
it's not a dialog), not through the standard `xbmcplugin` directory listing.
Rough shape for `stream_browser.py`:

```python
import xbmcgui
import xbmcaddon

ADDON = xbmcaddon.Addon()
ADDON_PATH = ADDON.getAddonInfo('path')

class StreamBrowser(xbmcgui.WindowXMLDialog):
    PANEL_ID = 3000

    def onInit(self):
        streams = fetch_live_streams()  # your existing Twitch/Kick logic
        self.panel = self.getControl(self.PANEL_ID)
        for s in streams:
            item = xbmcgui.ListItem(label=s['title'])
            item.setArt({'thumb': s['thumbnail_url']})
            item.setProperty('viewer_count', str(s['viewer_count']))
            item.setProperty('game_name', s['game_name'])
            item.setProperty('is_live', 'true' if s['is_live'] else '')
            self.panel.addItem(item)

    def onClick(self, controlId):
        if controlId == self.PANEL_ID:
            item = self.panel.getSelectedItem()
            play_stream(item)

    def onAction(self, action):
        if action.getId() in (xbmcgui.ACTION_PREVIOUS_MENU,
                               xbmcgui.ACTION_NAV_BACK):
            self.close()


win = StreamBrowser('StreamBrowser.xml', ADDON_PATH, 'Default', '1080i')
win.doModal()
del win
```

The `getControl(3000).addItem(...)` pattern is what feeds the `<panel
id="3000">` control in the XML — the `id` in the XML and the `PANEL_ID` in
Python have to match.

## Texture assets you still need to create

Kodi has no native rounded-corner or box-shadow property, so "elevation" is
faked with pre-rendered PNGs. Six small images, all referenced in
`StreamBrowser.xml`:

| File | What it is |
|---|---|
| `card_surface.png` | *(Optional)* Flat rounded-rect (12dp radius), fill `#211F26` (Surface Container), no shadow. The implementation now falls back to `colors/white.png` + `colordiffuse` so this is only needed if you want rounded corners. |
| `card_surface_focus.png` | *(Optional)* Same shape, fill `#2B2930` (Surface Container High), soft drop shadow baked in. The implementation now falls back to `colors/white.png` + `colordiffuse`. |
| `badge_live.png` | *(Optional)* Small rounded pill, fill `#E64980`. The implementation now falls back to `colors/white.png` + `colordiffuse`. |
| `name_box.png` | *(Optional)* Flat rounded-rect strip, fill `#2B2930` (Surface Container High). The implementation now falls back to `colors/white.png` + `colordiffuse`. |
| `card_border.png` | *(Optional)* Hollow rounded-rect frame. The implementation now draws the focus border with two overlapping `colors/white.png` rectangles instead. |
| `thumb_mask.png` | Referenced in the notes above but not yet used in the XML — optional, for rounding thumbnail corners if you want that polish later (needs a multiply-blend overlay, slightly more setup). |

Build these as **9-patch-style textures**: draw the shape once at a size
larger than the smallest usable size (e.g. 96×64px canvas for a rounded
rect with 12px corners), leave the flat center transparent-safe to
stretch, and Kodi will scale them cleanly via the `border="16"` attribute
on the `<texture>` tag — that value tells Kodi how many pixels from each
edge are the "don't stretch this part" corner/edge region.

Any vector tool (Inkscape, Figma, even a quick script with Pillow +
`ImageDraw.rounded_rectangle` and a Gaussian blur pass for the shadow) works
for generating these — happy to write a Pillow script that generates all
four from the color tokens above if that's easier than hand-drawing them.

## Fonts

Grab `Roboto-Regular.ttf` and `Roboto-Medium.ttf` (Apache 2.0 licensed,
Google Fonts) and drop them in `resources/skins/Default/fonts/`. Kodi finds
fonts by filename match against what's declared in `Font.xml`.

## Next steps

- Generate the texture PNGs (I can script this with Pillow if useful)
- Wire `fetch_live_streams()` to your existing Kick/Twitch API integration
- Add a second focused-state variant for the LIVE badge if you want it to
  pulse/highlight further on focus (would need an animation block in the
  XML, e.g. `<animation type="Focus">Zoom(...)</animation>`)
