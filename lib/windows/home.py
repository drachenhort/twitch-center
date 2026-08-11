"""Home screen: the user's followed channels, live ones surfaced first."""
import threading

import xbmcgui


class HomeWindow(xbmcgui.WindowXML):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.closed_event = threading.Event()

    def onInit(self):
        """Load and render followed channels. Stubbed."""
        pass

    def onAction(self, action):
        if action.getId() in (xbmcgui.ACTION_PREVIOUS_MENU, xbmcgui.ACTION_NAV_BACK):
            self.close()
            self.closed_event.set()
