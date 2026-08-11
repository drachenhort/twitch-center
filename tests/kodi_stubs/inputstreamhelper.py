"""Minimal stand-in for script.module.inputstreamhelper, for pytest-only use."""


class Helper:
    def __init__(self, protocol, drm=None):
        self.protocol = protocol
        self.drm = drm
        self.inputstream_addon = "inputstream.adaptive"

    def check_inputstream(self):
        return True
