import xbmc


def cycle_audio_stream():
    player = xbmc.Player()
    if not player.isPlaying():
        return

    streams = player.getAvailableAudioStreams()
    if not streams:
        xbmc.executebuiltin("Notification(Twitch Center,No audio tracks available)")
        return

    current = player.getAudioStream()
    next_idx = (current + 1) % len(streams)
    player.setAudioStream(next_idx)

    label = streams[next_idx] or "Track {}".format(next_idx + 1)
    xbmc.executebuiltin(
        "Notification(Twitch Center,Audio: {})".format(label.replace(",", ""))
    )
