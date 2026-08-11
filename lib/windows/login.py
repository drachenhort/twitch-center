"""Device-code login screen: displays the code + verification URL, polls for auth."""
import xbmcgui


class LoginWindow(xbmcgui.WindowXML):
    def onInit(self):
        """Populate the device code / verification URL and start polling. Stubbed."""
        pass
