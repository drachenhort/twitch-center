"""Minimal stand-in for Kodi's built-in xbmc module, for pytest-only use."""

LOGDEBUG = 0
LOGINFO = 1
LOGWARNING = 2
LOGERROR = 3
LOGFATAL = 4


def log(msg, level=LOGINFO):
    pass


class Monitor:
    """Minimal stand-in for xbmc.Monitor; real Kodi blocks until abort or timeout."""

    def waitForAbort(self, timeout=None):
        return False

    def abortRequested(self):
        return False


class Player:
    """Minimal stand-in for xbmc.Player; real Kodi starts playback."""

    def play(self, item=None, listitem=None, windowed=False, startpos=-1):
        pass

    def isPlaying(self):
        return False

    def stop(self):
        pass
