# Twitch Ad-Break Detection and Playback Recovery for Kodi

## Goal

This document describes how to add Twitch ad-break detection and automatic playback recovery to a Kodi-based Twitch media center.

The main problem this is designed to solve is:

1. Kodi is playing a Twitch live stream.
2. Twitch starts a mid-roll advertisement.
3. The HLS stream changes during the ad break.
4. Kodi's player gets stuck, buffers indefinitely, or fails to resume the live stream.
5. The add-on detects the ad break and/or stalled playback.
6. After the expected ad duration, it refreshes the Twitch stream and reconnects Kodi to the live edge.

Twitch provides an EventSub event called `channel.ad_break.begin`. It contains the requested ad duration, start timestamp, whether the ad was automatic, and the broadcaster ID. The subscription requires the `channel:read:ads` authorization scope. See the official Twitch documentation for the current EventSub requirements.

## Recommended Architecture

Do not make Kodi responsible for detecting the Twitch ad itself.

Use a small ad/recovery manager in the Kodi add-on:

```text
                 Twitch
                    |
          EventSub channel.ad_break.begin
                    |
                    v
             Ad Break Manager
                    |
        +-----------+-----------+
        |                       |
        v                       v
   expected ad time       playback watchdog
        |                       |
        +-----------+-----------+
                    |
                    v
             Recovery Manager
                    |
                    v
          obtain fresh Twitch URL
                    |
                    v
             restart Kodi
                    |
                    v
              live edge
```

The important design principle is that an ad break is a **known transition**, while a stuck player is a **failure condition**.

Use both.

---

# 1. Twitch EventSub

Create a Twitch EventSub subscription for:

```text
channel.ad_break.begin
```

Version:

```text
1
```

The subscription condition contains:

```json
{
    "broadcaster_user_id": "BROADCASTER_ID"
}
```

The authorization requires:

```text
channel:read:ads
```

The event contains information similar to:

```json
{
    "duration_seconds": 60,
    "started_at": "2026-08-14T00:00:00Z",
    "is_automatic": true,
    "broadcaster_user_id": "123456",
    "broadcaster_user_login": "streamer"
}
```

The Twitch documentation notes that `started_at` represents when the ad break was requested and that there can be some delay before the viewer actually sees the ads.

Therefore, do **not** assume that the ad begins on the Kodi player at exactly the EventSub timestamp.

---

# 2. Store Ad-Break State

Create a small state object in the add-on.

Example:

```python
class AdBreakState:
    def __init__(self):
        self.active = False
        self.started_at = None
        self.duration = 0
        self.channel = None
        self.is_automatic = False

    def begin(self, event):
        self.active = True
        self.started_at = event["started_at"]
        self.duration = int(event["duration_seconds"])
        self.channel = event["broadcaster_user_login"]
        self.is_automatic = bool(event["is_automatic"])

    def clear(self):
        self.active = False
        self.started_at = None
        self.duration = 0
        self.channel = None
        self.is_automatic = False
```

The state should belong to the currently playing Twitch channel.

Do not use one global ad state if the application can have multiple Twitch sessions.

---

# 3. Do Not Immediately Restart Kodi

An ad break can cause temporary buffering.

Do not do this:

```python
on_ad_break():
    restart_player()
```

Instead:

```text
EventSub ad notification
        |
        v
mark ad as active
        |
        v
continue monitoring playback
        |
        v
wait for expected ad duration
        |
        v
check whether stream recovered
        |
   +----+----+
   |         |
 recovered  stuck
   |         |
 continue   reconnect
```

This prevents unnecessary player restarts.

---

# 4. Add a Playback Watchdog

Kodi provides Python player callbacks such as:

```python
onAVStarted()
onAVChange()
onPlayBackEnded()
onPlayBackStopped()
onPlayBackError()
onPlayBackPaused()
onPlayBackResumed()
```

Use `onAVStarted()` rather than relying exclusively on `onPlayBackStarted()` when you need to know that Kodi actually has an audio/video stream.

Create a watchdog that periodically checks whether playback is making progress.

Recommended initial values:

```text
normal playback stall threshold: 10-15 seconds
ad recovery grace period: 5-10 seconds
maximum reconnect attempts: 3
```

For example:

```python
if ad_break.active:
    if ad_duration_has_elapsed():
        if playback_has_not_recovered():
            recovery_manager.reconnect()
else:
    if playback_stalled_for(15):
        recovery_manager.reconnect()
```

These values should be configurable.

---

# 5. Track Playback Progress

Do not use only Kodi's "playing" state.

A player can report that it is still playing while the actual stream has stopped progressing.

Maintain:

```python
last_position
last_position_change
last_av_started
```

Example logic:

```python
position = player.getTime()

if position != last_position:
    last_position = position
    last_progress_time = time.monotonic()
```

However, live streams require special care because the playback clock can behave differently around HLS discontinuities.

Therefore, combine position monitoring with:

- `onAVStarted()`
- `onAVChange()`
- `onPlayBackError()`
- player state
- network/HLS errors where available
- a timeout

Do not treat a single unchanged position sample as a failure.

---

# 6. Recovery Strategy

Use three recovery levels.

## Level 1: Wait

When an ad break is known:

```text
ad started
    |
    +-- wait for expected duration
    |
    +-- add a small grace period
```

For example:

```python
recovery_time = started_at + duration + 10
```

The extra 10 seconds compensates for the difference between Twitch's EventSub timestamp and the actual viewer playback.

---

## Level 2: Refresh the Twitch Stream URL

If playback has not recovered:

1. Obtain a fresh Twitch playback URL.
2. Do not reuse the old HLS URL.
3. Recreate the Kodi ListItem if necessary.
4. Start playback again.

Conceptually:

```python
stream_url = twitch.get_fresh_stream_url(channel)

list_item = xbmcgui.ListItem()
list_item.setPath(stream_url)

xbmc.Player().play(item=list_item)
```

The exact implementation depends on how the Twitch add-on currently obtains and passes the HLS URL to Kodi.

The important point is:

**refresh the Twitch URL before restarting playback.**

---

# 7. Hard Recovery

If refreshing the stream does not work, completely restart the Kodi player instance.

Conceptually:

```python
player.stop()

time.sleep(1)

stream_url = twitch.get_fresh_stream_url(channel)

start_stream(stream_url)
```

Do not attempt to seek back to the previous live position.

For a live Twitch stream, the correct target is the **current live edge**.

---

# 8. Recovery State Machine

A state machine makes this much easier to maintain.

Recommended states:

```text
PLAYING
    |
    | ad_break.begin
    v
AD_BREAK
    |
    | expected duration elapsed
    v
CHECKING
    |
    +---- playback OK ----> PLAYING
    |
    +---- playback stuck --> RECOVERING
                              |
                              v
                         GET_NEW_URL
                              |
                              v
                         RESTART_PLAYER
                              |
                         +----+----+
                         |         |
                       success    failure
                         |         |
                         v         v
                      PLAYING    RETRY
```

For retries:

```text
RETRY 1: wait 2 seconds
RETRY 2: wait 5 seconds
RETRY 3: wait 10 seconds
```

After three failures, report the problem to the user rather than endlessly restarting Kodi.

---

# 9. Important: Do Not Confuse User Pauses With Failures

The watchdog must know whether the user intentionally paused playback.

For example:

```python
if user_paused:
    return

if player_is_stalled:
    recovery_manager.check()
```

Kodi provides `onPlayBackPaused()` and `onPlayBackResumed()` callbacks that can be used to maintain this state.

---

# 10. Do Not Treat `onPlayBackEnded()` As "Twitch Offline"

A Twitch live stream ending and a broken HLS session can look similar.

Before deciding that the broadcaster went offline:

1. Query Twitch stream status.
2. If the channel is still live, attempt recovery.
3. If the channel is offline, stop normally.

This avoids displaying an incorrect "stream ended" message after an ad-related playback failure.

---

# 11. Recommended EventSub Integration

A separate background service/thread is preferable to performing network operations directly inside Kodi player callbacks.

For example:

```text
Kodi Add-on
│
├── Twitch API Client
│
├── EventSub Client
│      └── channel.ad_break.begin
│
├── AdBreakManager
│
├── PlaybackWatchdog
│
└── RecoveryManager
       ├── refresh stream URL
       ├── stop Kodi player
       ├── start new stream
       └── retry/backoff
```

The EventSub client should update the `AdBreakManager`.

The watchdog should consume the resulting state.

The recovery manager should be the only component responsible for restarting playback.

This prevents multiple components from trying to restart Kodi simultaneously.

---

# 12. Prevent Multiple Recoveries

Use a lock or state flag.

For example:

```python
if recovery_in_progress:
    return

recovery_in_progress = True

try:
    recover_stream()
finally:
    recovery_in_progress = False
```

Without this, the watchdog may detect a stall several times while a reconnect is already underway and launch multiple player instances.

---

# 13. Suggested Configuration

Add these settings to the Kodi add-on:

```text
Enable ad-break detection:       true

Ad recovery grace period:        10 seconds

Playback stall timeout:          15 seconds

Maximum recovery attempts:       3

Recovery retry delay:            5 seconds

Verify Twitch channel is live:   true

Log ad-break events:             true

Log recovery attempts:           true
```

For troubleshooting, make the logging fairly verbose.

Example:

```text
[ Twitch ] Ad break detected
[ Twitch ] Channel: streamer
[ Twitch ] Duration: 60 seconds
[ Twitch ] Automatic: true

[ Twitch ] Waiting for ad break to finish
[ Twitch ] Expected recovery: +70 seconds

[ Twitch ] Playback has not recovered
[ Twitch ] Refreshing Twitch playback URL

[ Twitch ] Restarting Kodi player
[ Twitch ] New stream URL obtained

[ Twitch ] AV started
[ Twitch ] Recovery successful
```

---

# 14. What Not To Do

Avoid:

```text
❌ Restart Kodi immediately when an ad starts
❌ Reuse the old HLS URL
❌ Seek to the old live position
❌ Assume EventSub timing exactly matches viewer playback
❌ Treat every buffering event as a failure
❌ Restart the player repeatedly without a retry limit
❌ Block Kodi callbacks with long HTTP requests
```

Prefer:

```text
✅ EventSub tells you an ad is expected
✅ Watchdog verifies actual playback
✅ Wait for the expected ad duration
✅ Add a configurable grace period
✅ Obtain a fresh Twitch stream URL
✅ Restart from the live edge
✅ Verify the broadcaster is still live
✅ Use bounded retries
```

---

# 15. Implementation Priority

I would implement this in the following order.

### Phase 1

Implement the playback watchdog.

This solves problems even when Twitch does not provide an ad event.

### Phase 2

Implement fresh Twitch URL retrieval.

Make sure a complete player restart actually works.

### Phase 3

Add `channel.ad_break.begin`.

Use it to make the watchdog smarter about expected interruptions.

### Phase 4

Add the recovery state machine.

This prevents race conditions and repeated restarts.

### Phase 5

Add logging and Kodi settings.

Only after the recovery mechanism works reliably.

---

# 16. Important Twitch API Consideration

The `channel.ad_break.begin` EventSub subscription is broadcaster-specific. The subscription uses the broadcaster's user ID and requires the appropriate ads permission.

If your media center is intended to watch arbitrary Twitch channels, you need to consider the authentication model carefully. You cannot simply assume that one generic Twitch token will provide ad-break events for every channel.

For a media center that watches arbitrary public channels, the **playback watchdog should therefore remain the fallback mechanism**.

The architecture should work even when EventSub ad notifications are unavailable.

---

# 17. Best Overall Strategy

For a Kodi Twitch media center, I recommend this final design:

```text
                     Twitch
                       |
             +---------+---------+
             |                   |
          HLS stream          EventSub
             |             ad_break.begin
             |                   |
             v                   v
          Kodi              Ad Manager
             |                   |
             +---------+---------+
                       |
                Playback Watchdog
                       |
                Is playback alive?
                  /                           YES            NO
                 |              |
              continue       Is ad active?
                                /                                   YES      NO
                               |        |
                        wait + grace   recover
                               |
                               v
                           still stuck?
                               |
                              YES
                               |
                               v
                       Fresh Twitch URL
                               |
                               v
                        Restart Kodi
                               |
                               v
                         Current live edge
```

This is considerably more robust than trying to make Kodi itself understand Twitch advertisements.

Kodi's Python player callbacks are suitable for the watchdog/recovery side, while Twitch EventSub supplies the ad-break signal when available. citeturn0search0turn0search3

## References

- Twitch EventSub / `channel.ad_break.begin`: urlTwitch EventSub documentationhttps://dev.twitch.tv/docs/eventsub/eventsub-subscription-types/
- Kodi Python Player callbacks: urlKodi Player callback documentationhttps://xbmc.github.io/docs.kodi.tv/master/kodi-dev-kit/group__python___player_c_b.html
