# Settings Re-login Button & Token Visibility: Design

Date: 2026-08-12

## What this is

Two small settings-page changes:
1. A "Re-login to Twitch" button in Settings, letting the user re-run the device-code login flow
   on demand (e.g. after using the same account on two machines, whose single-use refresh tokens
   can invalidate each other) without waiting for an actual session-expired error.
2. `twitch_token` and `website_token` become plain, visible, unmasked text fields in the settings
   dialog, for direct visual verification when pasting/editing values (including via the
   direct-file-edit workflow established this session).

## Scope decisions (from brainstorming)

- **No second addon process.** The natural way to reach Settings (`HomeWindow`'s own "Settings"
  button) calls `openSettings()`, which blocks that Home instance while the dialog is open. A
  naive `RunScript(...)` action button would spawn a *second* addon instance on top of the first —
  exactly the class of bug behind this session's still-open window-revert issue and the documented
  orphaned-invoker crash risk. Ruled out.
- **Flag + existing safe transition instead.** The button sets a plain hidden boolean setting
  (`relogin_requested`) via Kodi's `SetAddonSetting` builtin — no process spawned, no new window
  created from inside the settings dialog itself. `HomeWindow._open_addon_settings` (which already
  reloads Home after `openSettings()` returns) checks the flag and, if set, clears it and calls the
  already-existing `_open_login_window()` — the same safe in-process Home→Login transition already
  used by the "Log in again" button, proven and shipped.
- **Current session untouched unless the new login succeeds.** `auth.save_token` only fires on a
  successful device-code login, unchanged — backing out of the new login screen leaves the old
  token exactly as it was.
- `twitch_token` stays at `level 2` (Advanced) — visible now, but not cluttering the basic
  settings view. `website_token` stays at `level 0` (Basic), as today.

## Components

### `resources/settings.xml` (extended)

New hidden flag setting and action button, same group:

```xml
<setting id="relogin_requested" type="boolean" label="">
  <level>0</level>
  <default>false</default>
  <control type="toggle"/>
  <visible>false</visible>
</setting>
<setting id="relogin_action" type="action" label="30010" help="30011">
  <level>0</level>
  <control type="button" format="action">
    <data>SetAddonSetting(script.twitch.center,relogin_requested,true)</data>
  </control>
</setting>
```

`website_token`'s control loses its `<hidden>true</hidden>`:

```xml
<control type="edit" format="string"/>
```

`twitch_token` loses its `<visible>false</visible>` element entirely (stays `level 2`).

### `resources/language/resource.language.en_gb/strings.po` (extended)

- `#30010`: `"Re-login to Twitch"`
- `#30011`: `"Opens the device-code login screen again, without affecting your current session unless you actually complete a new login. Useful if you're using the same account on another device and your session here stops refreshing."`

### `lib/settings.py` (extended)

```python
    @property
    def relogin_requested(self):
        return self._addon.getSettingBool("relogin_requested")

    def clear_relogin_requested(self):
        self._addon.setSettingBool("relogin_requested", False)
```

### `lib/windows/home.py` (extended)

`_open_addon_settings` gains a check after the existing `closed_event` guard, before falling back
to `self.onInit()`:

```python
    def _open_addon_settings(self):
        xbmcaddon.Addon().openSettings()
        if self.closed_event.is_set():
            return
        if self._settings.relogin_requested:
            self._settings.clear_relogin_requested()
            self._open_login_window()
            return
        self.onInit()
```

`_open_login_window` is unchanged — already exists, already handles this transition safely (used
today by the relogin-on-expiry button).

## Data flow

```
User: Settings button on Home -> xbmcaddon.Addon().openSettings() (blocks Home's script thread)
  -> user presses "Re-login to Twitch" inside the dialog
       -> builtin SetAddonSetting(script.twitch.center, relogin_requested, true)
          (writes directly to this addon's settings.xml, no process spawned)
  -> user closes the settings dialog -> openSettings() returns, Home's thread resumes
  -> HomeWindow._open_addon_settings:
       if closed_event is set -> return (unchanged)
       elif relogin_requested -> clear flag, _open_login_window() (existing, safe transition)
       else -> self.onInit() (existing reload-Home behavior, unchanged)
```

## Error handling

Nothing new — `_open_login_window()` already exists and is already exercised by the relogin-on-
expiry path; no new failure modes introduced. If the user presses the button and then closes
Settings without actually completing a new login (backs out of the login screen via Back, which
`LoginWindow.onAction` already handles), the shared `closed_event` chain behaves exactly as it
already does for that existing flow — untouched by this change.

## Testing

- `lib/settings.py`: `relogin_requested`/`clear_relogin_requested` tested against the
  `tests/kodi_stubs/xbmcaddon.Addon` stub (round-trip true → clear → false).
- `lib/windows/home.py`: `_open_addon_settings` tests, mirroring the existing
  `test_selecting_settings_button_opens_addon_settings_and_reloads` test's pattern —
  - flag not set: behavior unchanged (existing test already covers this).
  - flag set: asserts `LoginWindow` gets constructed/shown (mocked, same pattern as the existing
    relogin-button test) and the flag is cleared afterward (`addon.getSettingBool("relogin_requested")
    is False`).
- No test exercises Kodi's real settings dialog or the `SetAddonSetting` builtin itself (that part
  is Kodi's own tested behavior, outside this addon's test surface — this addon's tests cover
  everything from `openSettings()` returning onward).

## Out of scope

- No change to the "Log in again" button's own existing behavior (still shown only on
  missing/expired-token error states).
- No UI feedback inside the settings dialog itself confirming the button was pressed (Kodi's own
  action-button convention doesn't provide one beyond the button existing).
