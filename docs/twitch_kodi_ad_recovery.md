# Twitch Media Center — Kodi Ad-Break Recovery

## Purpose

This document describes the recommended Python/Kodi architecture for reliable Twitch live playback, especially the case where Kodi fails to recover after a Twitch ad break.

The key design principle is:

> Kodi/InputStream Adaptive handles video playback. Python supervises the Twitch HLS stream, detects ad/discontinuity transitions, monitors health, and performs graduated recovery when playback gets stuck.

---

## 1. Architecture

```text
                   ┌────────────────────┐
                   │     Twitch API     │
                   └─────────┬──────────┘
                             │
                             ▼
                    ┌─────────────────┐
                    │ TwitchClient    │
                    │ get_stream_url()│
                    └────────┬────────┘
                             │
                             ▼
                    ┌─────────────────┐
                    │ StreamManager   │
                    └───────┬─────────┘
                            │
             ┌──────────────┼──────────────┐
             ▼              ▼              ▼
       HLSMonitor      AdDetector     KodiPlayer
             │              │              │
             └──────────────┼──────────────┘
                            ▼
                    ┌─────────────────┐
                    │    Watchdog     │
                    └────────┬────────┘
                             │
                             ▼
                    ┌─────────────────┐
                    │ RecoveryManager │
                    └────────┬────────┘
                             │
                 ┌───────────┼───────────┐
                 ▼           ▼           ▼
              refresh      restart    new URL
```

Do not implement HLS playback yourself. Use Kodi's `inputstream.adaptive` for HLS playback and keep the Python code focused on supervision and recovery.

---

## 2. Recommended project structure

```text
plugin.video.twitchcenter/
│
├── addon.py
├── default.py
│
├── resources/
│   └── settings.xml
│
└── lib/
    ├── twitch.py
    ├── hls.py
    ├── ads.py
    ├── player.py
    ├── watchdog.py
    ├── recovery.py
    └── models.py
```

### Responsibilities

| Module | Responsibility |
|---|---|
| `twitch.py` | Twitch API/authentication and fresh playback URLs |
| `hls.py` | Download and parse Twitch HLS playlists |
| `ads.py` | Detect ad/splice markers |
| `player.py` | Kodi/InputStream Adaptive integration |
| `watchdog.py` | Monitor HLS and Kodi playback health |
| `recovery.py` | Graduated recovery actions |
| `models.py` | Dataclasses/state models |
| `stream manager` | Coordinate the components |

---

## 3. Stream state machine

Use an explicit state machine instead of simply checking `xbmc.Player().isPlaying()`.

```text
STARTING
    │
    ▼
PLAYING
    │
    ├────────────────┐
    │                │
    ▼                ▼
AD_BREAK         PLAYBACK_ERROR
    │                │
    ▼                ▼
RECOVERING ◄─────────┘
    │
    ├── success ──► PLAYING
    │
    └── timeout ──► RECONNECTING
                         │
                         ▼
                      PLAYING
```

Suggested states:

```python
class StreamState:
    STARTING = "starting"
    PLAYING = "playing"
    AD_BREAK = "ad_break"
    RECOVERING = "recovering"
    RECONNECTING = "reconnecting"
    FAILED = "failed"
```

---

## 4. HLS monitoring

The Python layer should periodically retrieve the Twitch HLS media playlist.

Track at minimum:

- `EXT-X-MEDIA-SEQUENCE`
- `EXT-X-TARGETDURATION`
- latest segment URI
- segment duration
- `EXT-X-DISCONTINUITY`
- ad markers
- playlist update time

Suggested models:

```python
@dataclass
class HLSSegment:
    uri: str
    duration: float
    sequence: int
    discontinuity: bool = False


@dataclass
class HLSPlaylist:
    media_sequence: int
    target_duration: float
    segments: list
    ad_break: bool
    ad_duration: float | None
```

The most important health indicator is whether the media sequence/segment list continues advancing.

---

## 5. Ad-break detection

Support several HLS marker types rather than relying on one marker.

Recognize at least:

```text
#EXT-X-CUE-OUT
#EXT-X-CUE-OUT-CONT
#EXT-X-CUE-IN

#EXT-X-DATERANGE

#EXT-X-DISCONTINUITY
```

Example detector:

```python
class AdBreakDetector:

    def __init__(self):
        self.in_ad = False
        self.started = None
        self.expected_duration = None

    def process(self, playlist):

        if playlist.cue_out:
            self.in_ad = True
            self.started = time.monotonic()
            self.expected_duration = playlist.ad_duration
            return "AD_START"

        if playlist.cue_in:
            if self.in_ad:
                self.in_ad = False
                return "AD_END"

        return None
```

Important: **ad detection must not be the only recovery mechanism**. Twitch may change how markers are exposed. The HLS progression watchdog should still detect a stalled playlist.

---

## 6. Kodi/InputStream Adaptive integration

Kodi should play the HLS stream using InputStream Adaptive.

Example:

```python
class KodiPlayer(xbmc.Player):

    def __init__(self):
        super().__init__()

    def play_stream(self, url):

        item = xbmcgui.ListItem(path=url)

        item.setProperty(
            "inputstream",
            "inputstream.adaptive"
        )

        item.setProperty(
            "inputstream.adaptive.manifest_type",
            "hls"
        )

        self.play(url, item)
```

Before playback, optionally verify that InputStream Adaptive is installed:

```python
if not xbmc.getCondVisibility(
    "System.HasAddon(inputstream.adaptive)"
):
    raise RuntimeError(
        "InputStream Adaptive is not installed"
    )
```

Avoid implementing the HLS player in Python.

---

## 7. HLS stall detection

Do not immediately restart Kodi when `isPlaying()` becomes false.

Track:

```text
last_media_sequence
last_segment
last_playlist_update
```

Example:

```python
def playback_is_stuck(self, playlist):

    now = time.monotonic()

    sequence_changed = (
        playlist.media_sequence != self.last_media_sequence
    )

    if sequence_changed:
        self.last_media_sequence = playlist.media_sequence
        self.last_progress = now
        return False

    return (
        now - self.last_progress
        > self.stall_timeout
    )
```

Make the timeout depend on the playlist's segment duration:

```python
stall_timeout = max(
    15,
    playlist.target_duration * 3
)
```

For example, with a 6-second target duration:

```text
6 × 3 = 18 seconds
```

before declaring the HLS stream stalled.

---

## 8. Ad-break recovery

The normal ad transition should be:

```text
PLAYING
   ↓
AD_BREAK
   ↓
RECOVERING
   ↓
PLAYING
```

Not:

```text
PLAYING
   ↓
Kodi stopped
   ↓
restart
   ↓
Kodi stopped
   ↓
restart
   ↓
failure
```

When an ad is detected:

1. Enter `AD_BREAK`.
2. Do not immediately restart Kodi.
3. Continue monitoring the HLS playlist.
4. Wait for the ad to end or the playlist to return to normal.
5. Confirm that media segments continue advancing.
6. Return to `PLAYING`.

---

## 9. Recovery ladder

Recovery should become increasingly aggressive.

### Level 0 — Wait

For the first ~10 seconds of a transition:

```text
Do nothing.
```

Temporary pauses are normal during HLS/ad transitions.

### Level 1 — HLS refresh

If the playlist remains stalled:

```python
monitor.refresh()
```

Obtain/re-read the current playlist.

### Level 2 — Restart Kodi player

If HLS is healthy but Kodi is not playing:

```python
player.stop()
```

Then reopen the stream.

### Level 3 — Get a fresh Twitch playback URL

Do not endlessly reuse an old HLS URL.

Ask the Twitch client for a fresh playback URL/token and reopen Kodi.

### Level 4 — Fail gracefully

After several complete recovery failures, stop retrying indefinitely and report the stream as unavailable.

---

## 10. Recovery manager

Suggested structure:

```python
class RecoveryManager:

    def __init__(self, player, twitch):
        self.player = player
        self.twitch = twitch
        self.failures = 0

    def recover(self):

        self.failures += 1

        if self.failures == 1:
            return self.refresh()

        if self.failures == 2:
            return self.restart_player()

        if self.failures == 3:
            return self.new_stream_url()

        return self.fail()
```

The recovery manager should reset its failure counter after successful stable playback.

---

## 11. Three independent health signals

The watchdog should combine three different signals:

```text
                    Twitch HLS
                         │
                  ┌──────▼──────┐
                  │ HLS health  │
                  └──────┬──────┘
                         │
                    media sequence
                         │
                         ▼
                  ┌─────────────┐
                  │ Stream      │
                  │ Supervisor  │
                  └──────┬──────┘
                         │
             ┌───────────┼────────────┐
             ▼           ▼            ▼
        HLS watchdog  Kodi state   Player time
```

### HLS health

Is the playlist/media sequence advancing?

### Kodi state

Is Kodi reporting that the player is active?

### Player time

Is:

```python
player.getTime()
```

actually advancing?

This catches cases where Kodi reports `PLAYING` but the decoder/video is effectively frozen.

---

## 12. Kodi playback-time watchdog

Periodically record `player.getTime()`.

```python
current_time = player.getTime()

if current_time == last_player_time:
    stalled_player_time += 3
else:
    stalled_player_time = 0
```

If playback time remains unchanged for roughly 30 seconds while the HLS playlist is healthy, treat this as a Kodi/player stall and restart the player.

---

## 13. Watchdog

The watchdog can run in a background thread:

```python
class StreamWatchdog(threading.Thread):

    POLL_INTERVAL = 3

    def __init__(self, monitor, player, recovery):
        super().__init__(daemon=True)

        self.monitor = monitor
        self.player = player
        self.recovery = recovery
        self.running = True

    def run(self):

        while self.running:

            try:
                self.check()

            except Exception as exc:
                log("Watchdog error: %s" % exc)

            time.sleep(self.POLL_INTERVAL)
```

However, keep Kodi API calls centralized. The watchdog should preferably signal the main Kodi/plugin loop instead of performing complicated Kodi operations directly from its worker thread.

For example:

```python
class PlayerController:

    def request_restart(self):
        self.restart_requested = True
```

The main loop then performs the actual Kodi player restart.

---

## 14. Suggested timing values

Start with these values and make them configurable:

| Condition | Action |
|---|---|
| HLS unchanged < 10 s | Ignore |
| Ad marker detected | Enter `AD_BREAK` |
| Ad ended | Enter `RECOVERING` |
| HLS advancing | Return to `PLAYING` |
| HLS stalled ~15–20 s | Refresh playlist |
| HLS healthy but Kodi stopped | Reopen player |
| Kodi playback time stuck ~30 s | Restart player |
| Restart still fails | Request fresh Twitch URL |
| 3–4 complete failures | Mark stream failed |

These values should be tuned using real Twitch logs.

---

## 15. Live-edge safety margin

Avoid forcing Kodi to operate exactly at the live edge.

Start with approximately:

```text
15–20 seconds live delay
```

The extra buffer gives Twitch/Kodi room to handle playlist changes and ad transitions.

Expose live delay as a Kodi setting so it can be tuned.

---

## 16. Kodi settings

Recommended settings:

```text
Stream
├── Quality
├── Low latency
└── Live delay

Recovery
├── Enable automatic recovery
├── HLS stall timeout
├── Player stall timeout
├── Maximum recovery attempts
└── Reconnect delay

Ads
├── Detect HLS ad markers
├── Ad recovery timeout
└── Show ad notification

Debug
├── Enable debug logging
└── Save HLS playlists
```

---

## 17. Debug playlist capture

This is especially valuable during development.

When an ad transition occurs, optionally save:

```text
playlist-before-ad.m3u8
playlist-during-ad.m3u8
playlist-after-ad.m3u8
```

This lets you determine exactly what Twitch changes during the problematic transition.

Do not assume that Twitch always uses the same ad markers.

---

## 18. Event logging

Use structured, timestamped logging.

Normal transition:

```text
01:14:02 [PLAY] channel=example
01:14:03 [HLS] sequence=18492301
01:14:09 [HLS] sequence=18492302
01:14:15 [HLS] sequence=18492303

01:14:18 [AD] CUE-OUT duration=30
01:14:21 [HLS] discontinuity detected
01:14:39 [HLS] sequence advancing
01:14:48 [AD] CUE-IN
01:14:51 [RECOVERY] stream healthy
01:14:52 [PLAY] normal playback
```

Failed transition:

```text
01:14:18 [AD] CUE-OUT duration=30
01:14:24 [HLS] sequence stopped
01:14:39 [WATCHDOG] HLS stalled 15s
01:14:40 [RECOVERY] refresh playlist
01:14:45 [WATCHDOG] HLS still stalled
01:14:46 [RECOVERY] restart Kodi player
01:14:52 [HLS] sequence advancing
01:14:53 [RECOVERY] successful
```

Logging should make it possible to answer:

- Did Twitch stop advancing the playlist?
- Did Twitch change the playlist?
- Did Kodi stop playing?
- Did Kodi's playback clock stop?
- Did a player restart fix the problem?
- Was a new Twitch URL required?

---

## 19. Important implementation rule

Do **not** build the system around:

```python
if not player.isPlaying():
    player.play(url)
```

This is too aggressive and can create restart loops during legitimate HLS/ad transitions.

Instead, use:

```text
HLS progression
+
ad state
+
Kodi player state
+
Kodi playback time
```

to decide whether playback is genuinely broken.

---

## 20. Recommended implementation phases

### Phase 1 — Basic playback

```text
Twitch playback URL
        ↓
Kodi InputStream Adaptive
        ↓
working live playback
```

### Phase 2 — HLS monitoring

Implement:

- playlist fetching
- media sequence tracking
- segment tracking
- target duration tracking

### Phase 3 — Ad detection

Implement:

- CUE-OUT
- CUE-OUT-CONT
- CUE-IN
- DATERANGE
- DISCONTINUITY

### Phase 4 — Watchdog

Implement:

- HLS stall detection
- Kodi player state monitoring
- playback-time monitoring

### Phase 5 — Recovery

Implement:

1. wait
2. refresh playlist
3. restart Kodi player
4. request a fresh Twitch playback URL
5. fail gracefully

### Phase 6 — Production hardening

Add:

- Kodi settings
- structured logging
- playlist capture
- configurable timeouts
- recovery statistics
- rate limiting/retry backoff

---

## 21. Final recommended design

The most important part of the implementation is the separation of responsibilities:

```text
TwitchClient
    │
    └── obtains current playback information

HLSMonitor
    │
    └── determines whether Twitch's stream is advancing

AdDetector
    │
    └── determines whether a splice/ad transition is occurring

KodiPlayer
    │
    └── lets Kodi/InputStream Adaptive handle playback

Watchdog
    │
    └── combines HLS + Kodi health signals

RecoveryManager
    │
    └── performs graduated recovery

StreamManager
    │
    └── coordinates everything
```

The primary recovery strategy should therefore be:

```text
              Twitch HLS
                  │
                  ▼
          detect ad transition
                  │
                  ▼
            wait for resume
                  │
                  ▼
       is HLS media sequence moving?
             /             \
           YES              NO
            │                │
            ▼                ▼
       is Kodi moving?    refresh HLS
          /    \               │
        YES     NO              ▼
         │       │         still stalled?
         ▼       ▼             │
       normal  restart       YES
       playback  player        │
                                ▼
                         fresh Twitch URL
                                │
                                ▼
                         restart playback
```

This design should be the foundation for a reliable Twitch media-center addon without tightly coupling Twitch's changing HLS/ad behavior to Kodi's player implementation.
