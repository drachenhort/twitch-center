# TODO

- ~~Tackle chat~~ DONE (v0.10.0): `lib/twitch/irc.py`'s `ChatClient` and `lib/windows/chat_overlay.py`
  are real and live-tested (Quin69, busy chat). `chat_display_mode`'s "overlay"/"both" show it
  automatically during playback; auto-reconnects, auto-scrolls, throttled rendering, closes on
  stop/end/error. Remaining gap: "standalone" mode does nothing - `lib/windows/chat_window.py` is
  still a stub.

- Picture-in-picture: no system-level PiP (small floating video while browsing OTHER Kodi
  screens/menus) - not a thing Kodi's addon API supports.

  What the user actually wants: video playing in a SMALL BOX with chat laid out around/beside it
  in the SAME screen, when chat is toggled on - not fullscreen video with a dialog on top. Would be
  a new 4th `chat_display_mode` value (e.g. "pip"), separate from and not touching the already-
  shipped "overlay"/"standalone"/"both" - video large on the left, chat strip on the right, Back
  stops playback and returns to Home (same as today's fullscreen Back behavior).

  **Blocked on an unresolved core-mechanism question, live-tested 2026-08-12, not solved:**
  - A custom `WindowXMLDialog` with a `<control type="videowindow">` sized as a box, with
    `xbmc.Player().play(url, listitem)` called while that window is active, does NOT confine
    playback to the box - it renders fullscreen, ignoring the control's geometry entirely
    (confirmed via screenshot).
  - `xbmc.Player().play(url, listitem, windowed=True)` DOES produce genuinely boxed (non-
    fullscreen) video (confirmed via screenshot) - but it appears to kick the active window back
    to Kodi's own system Home screen underneath the box, not stay on our own custom skin/window
    with its own chat-list layout beside it.
  - Neither combination alone gives "our own skin, video box + our own chat list beside it in the
    same window." Something's missing - possibly re-asserting/re-activating our own window after
    the `windowed=True` call, a different control/window-type combination entirely, or a
    fundamentally different mechanism than either tried so far. Needs more live-Kodi spike
    investigation before a real design/plan can be written - don't start implementation planning
    on an assumed mechanism again.

- Follow current streamer from the addon: NOT possible - Twitch removed the Create/Delete User
  Follow endpoints from the Helix API in Feb 2023. Third-party apps can no longer follow/unfollow
  programmatically; only Twitch's own web/app UI can. Dead end, don't attempt.

- Follow raids: feasible. When a streamer raids out, Twitch IRC sends a `USERNOTICE` with
  `msg-id=raid` naming the target channel. `lib/twitch/irc.py` already holds a chat connection -
  parse that message and prompt/auto-switch playback to the raided-into channel. No EventSub
  needed, just handling a message type that's already flowing through chat.

- Playback resolution was low on one stream after the v0.6.5 anonymous-playback-token fix, but
  fine on another (DatModz) - confirmed per-streamer difference (source bitrate/quality choice),
  not a regression from going anonymous. Anonymous requests are still capped at FULL_HD/12500kbps
  by Twitch (`AUTHZ_NOT_LOGGED_IN` blocks QUAD_HD/ULTRA_HD) - fine for now, revisit only if a
  streamer's own source is above 1080p and that cap becomes the actual limiter.
