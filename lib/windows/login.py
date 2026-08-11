"""Device-code login screen: displays the code + verification URL, polls for auth."""
import threading

import xbmc
import xbmcaddon
import xbmcgui

from lib.twitch import auth

STATUS_MESSAGES = {
    "pending": "Waiting for authorization...",
    "expired": "Code expired. Reopen the addon to try again.",
    "success": "Logged in!",
    "error": "Connection error. Reopen the addon to try again.",
}


class LoginWindow(xbmcgui.WindowXML):
    CODE_LABEL_ID = 101
    URL_LABEL_ID = 102
    STATUS_LABEL_ID = 103

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._cancel_event = threading.Event()
        self._thread = None
        self.closed_event = threading.Event()

    def onInit(self):
        if self._thread is not None and self._thread.is_alive():
            # Kodi can re-fire onInit (e.g. window re-activation); avoid
            # spawning a second polling thread.
            return
        self._cancel_event = threading.Event()
        addon = xbmcaddon.Addon()
        client_id = addon.getSetting("client_id")
        thread = threading.Thread(
            target=auth.run_device_code_login,
            kwargs={
                "client_id": client_id,
                "scopes": auth.SCOPES,
                "addon": addon,
                "on_code": self._on_code,
                "on_status": self._on_status,
                "cancel_event": self._cancel_event,
            },
        )
        thread.daemon = True
        thread.start()
        self._thread = thread

    def _on_code(self, user_code, verification_uri):
        if self._cancel_event.is_set():
            return
        self.getControl(self.CODE_LABEL_ID).setLabel(user_code)
        self.getControl(self.URL_LABEL_ID).setLabel(verification_uri)

    def _on_status(self, status):
        if self._cancel_event.is_set():
            return
        if status == "error":
            xbmc.log("script.twitch.center: device-code login reported an error", xbmc.LOGERROR)
        message = STATUS_MESSAGES.get(status, "")
        self.getControl(self.STATUS_LABEL_ID).setLabel(message)
        if status == "success":
            self.close()
            self.closed_event.set()

    def onAction(self, action):
        if action.getId() in (xbmcgui.ACTION_PREVIOUS_MENU, xbmcgui.ACTION_NAV_BACK):
            self._cancel_event.set()
            self.close()
            self.closed_event.set()
