"""Minimal stand-in for Kodi's built-in xbmcvfs module, for pytest-only use."""


def translatePath(path):
    return path
