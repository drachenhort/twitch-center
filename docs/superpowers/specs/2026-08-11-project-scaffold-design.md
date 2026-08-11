# twitch-center: Project Scaffold Design

Date: 2026-08-11

## What this is

`twitch-center` is a Kodi *script* addon (`script.twitch.center`) for viewing Twitch streams and
their paired IRC chat, launched from within Kodi so Kodi's own player handles video playback.
Architecture follows the same pattern as [jellyfin-kodi-plex](https://github.com/drachenhort/jellyfin-kodi-plex):
a script addon (not `plugin.video.*`) that opens its own `WindowXML`/`WindowXMLDialog` windows,
independent of the active Kodi skin, with a strict split between pure-Python logic (testable under
plain `pytest`) and the thin `xbmc*`-dependent UI layer.

This document scopes the **initial scaffold**: directory layout, module boundaries, and stubbed
(not fully implemented) entry points for auth, API access, stream resolution, chat, and the
Home/Discover screens. It is not a plan for the full first working version — that follows as a
separate implementation plan (`writing-plans`) once this scaffold is approved.

## Goals for this scaffold

- Establish the addon skeleton (`addon.xml`, settings, language strings) so it's installable/
  launchable in Kodi as a no-op.
- Establish `lib/` package boundaries matching the features already scoped (auth, API, stream
  resolution, chat, Home, Discover) with stub functions/classes and docstrings, not working logic.
- Establish the `tests/kodi_stubs/` test harness so `lib/twitch/*` (pure Python) is pytest-testable
  from day one, mirroring jellyfin-kodi-plex.
- Get one smoke test passing (`pytest` runs green against the stub package).

Out of scope for this scaffold: implementing the device-code OAuth flow, the GraphQL/usher stream
resolution, the IRC client, or any real UI rendering. Those are follow-up specs/plans.

## Feature scope driving the layout

Captured from brainstorming, to justify the module boundaries below:

- **Login:** Twitch OAuth device-code flow (user enters a code at twitch.tv/activate on another
  device) — no browser/webview needed inside Kodi, no client secret stored on-device.
- **Stream playback:** resolved via direct calls to Twitch's GraphQL + `usher.ttvnw.net` access
  token endpoints (no `streamlink` dependency), producing a direct HLS URL handed to Kodi's player.
- **Chat:** connects to `irc.chat.twitch.tv`, rendered either as a non-modal overlay during
  playback or as a standalone full-screen chat view — user's choice via a setting, both supported.
- **Home screen:** the user's followed channels (Twitch's free Follow list, Helix
  `/channels/followed`), live ones surfaced first.
- **Discover screen:** two ways to find something else to watch —
  - *Browse by game*: game categories derived from what followed channels currently/recently
    play (no "follow a game" Twitch API exists) → live channels streaming that game.
  - *Search*: free-text channel search (Helix `/search/channels`) for any streamer by name.

## Directory layout

```
addon.xml
resources/
  settings.xml
  language/resource.language.en_gb/strings.po
  skins/Default/1080i/          # WindowXML .xml layouts (placeholders in this scaffold)
lib/
  twitch/
    __init__.py
    auth.py        # device-code OAuth flow, token storage/refresh (stub)
    api.py          # Helix calls: followed channels, live status, games per channel,
                     # live streams by game, channel search (stub)
    stream.py       # GraphQL + usher access-token dance -> playable HLS URL (stub)
    irc.py          # IRC chat client against irc.chat.twitch.tv, pure socket-based (stub)
  windows/
    __init__.py
    login.py        # device-code display + polling UI (stub)
    home.py         # followed-channels list UI (stub)
    discover.py     # browse-by-game + search UI (stub)
    player.py       # launches Kodi playback for a resolved stream URL (stub)
    chat_overlay.py  # non-modal WindowXMLDialog shown during playback (stub)
    chat_window.py   # standalone full-screen chat view (stub)
  settings.py        # typed wrapper over xbmcaddon settings, incl. chat display mode (stub)
  main.py            # entry point / routing (stub)
tests/
  kodi_stubs/         # xbmc/xbmcgui/xbmcaddon stand-ins, registered via conftest.py
    __init__.py
    xbmc.py
    xbmcgui.py
    xbmcaddon.py
  conftest.py          # registers kodi_stubs into sys.modules before lib/windows imports run
  test_smoke.py         # imports lib.twitch.* and lib.main, asserts they load
requirements-dev.txt     # already present: pytest, requests
```

## Module boundary (carried over from jellyfin-kodi-plex)

`lib/twitch/*` must have **zero** `xbmc*` imports, so it runs under plain `pytest` with no Kodi
environment. `lib/windows/*`, `lib/player.py`-equivalent (`lib/windows/player.py`), and
`lib/settings.py` are the only modules touching `xbmcgui`/`xbmc`/`xbmcaddon`; they're exercised
under pytest via `tests/kodi_stubs/`, registered into `sys.modules` by `tests/conftest.py`, exactly
as jellyfin-kodi-plex does it.

## Error handling

Not applicable at scaffold stage — stub functions raise `NotImplementedError` or return empty
placeholder data; no real error paths exist yet. Error handling (auth failures, unreachable Twitch
API, stream resolution failures, IRC disconnects) is designed in the follow-up implementation spec
for each subsystem.

## Testing

- `tests/kodi_stubs/` + `tests/conftest.py`: minimal stand-ins for `xbmc`, `xbmcgui`, `xbmcaddon`,
  enough to import `lib/windows/*` and `lib/settings.py` without a real Kodi environment.
- `tests/test_smoke.py`: imports every `lib/twitch/*` module and `lib/main.py`, asserting they
  import cleanly — the scaffold's baseline "does this even load" check.
- `pip install -r requirements-dev.txt && pytest` must pass after scaffolding.

## Follow-up specs (not part of this scaffold)

1. Device-code auth flow implementation.
2. GraphQL/usher stream resolution implementation.
3. IRC chat client implementation + overlay/standalone rendering.
4. Home screen (followed channels) implementation.
5. Discover screen (browse-by-game + search) implementation.
