"""Minimal stand-in for Kodi's built-in xbmc module, for pytest-only use."""

LOGDEBUG = 0
LOGINFO = 1
LOGWARNING = 2
LOGERROR = 3
LOGFATAL = 4


def log(msg, level=LOGINFO):
    pass
