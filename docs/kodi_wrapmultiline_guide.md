# Kodi Skinning: Troubleshooting `<wrapmultiline>` Issues

When `<wrapmultiline>true</wrapmultiline>` appears to be ignored or broken in Kodi skin development, it is typically caused by one of five common issues:

---

## 1. Syntax: XML Tag vs. XML Attribute
Kodi's GUI engine expects `<wrapmultiline>` as a **child XML tag**, not as an inline attribute. Additionally, XML tags in Kodi are strictly **case-sensitive and lower-case only**.

- ❌ **Incorrect:** `<control type="label" wrapmultiline="true">`
- ❌ **Incorrect:** `<wrapMultiLine>true</wrapMultiLine>`
- ✅ **Correct:**
```xml
<control type="label">
    <width>400</width>
    <height>120</height> <!-- Must accommodate multiple lines -->
    <wrapmultiline>true</wrapmultiline>
    <label>$INFO[ListItem.Plot]</label>
</control>
```

---

## 2. Inadequate `<height>` Allocation
This is the most common reason multi-line wrapping fails silently.
- If `<height>` is set to match a single line of text (e.g., `30`), Kodi wraps the text internally, but any lines below the first line are clipped outside the control bounds and rendered invisible.
- **Fix:** Increase `<height>` to accommodate the expected number of lines (e.g., if font line height is ~30px and 3 lines are expected, set `<height>90</height>` or higher).

---

## 3. Conflict with `<scroll>true</scroll>`
If horizontal text scrolling is active on the label control, Kodi overrides line-wrapping in favor of scrolling on a single line.

- Ensure `<scroll>false</scroll>` is explicitly set (or omitted, as `false` is default) when using `<wrapmultiline>true</wrapmultiline>`.

---

## 4. Unbroken Strings (No Spaces)
Kodi's label wrapping logic splits text **only at space characters**.
- If the incoming InfoLabel returns a continuous string without spaces (such as a long URL, file path, or continuous string), Kodi cannot break the word, causing horizontal overflow.

---

## 5. Label Control vs. Textbox Control
If you are displaying long dynamic text (like movie plot summaries or full biography descriptions) and require vertical scrolling, `<control type="label">` with `<wrapmultiline>` **will not scroll vertically**.

- For long text that needs to wrap **and** scroll vertically, switch to a `<textbox>` control:

```xml
<control type="textbox">
    <width>500</width>
    <height>300</height>
    <label>$INFO[ListItem.Plot]</label>
    <autoscroll time="3000" delay="4000" repeat="5000">true</autoscroll>
</control>
```

---

### Quick Troubleshooting Checklist
1. Is `<wrapmultiline>true</wrapmultiline>` written as a lowercase child element?
2. Is the control's `<height>` tall enough to render multiple lines?
3. Is `<scroll>` set to `false`?
4. Is the text long with vertical scrolling needed? (If so, use `<textbox>`).
