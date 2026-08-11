"""Non-modal chat overlay shown during playback."""
import xbmcgui


class ChatOverlay(xbmcgui.WindowXMLDialog):
    def onInit(self):
        """Connect to chat and start rendering incoming messages. Stubbed."""
        pass
