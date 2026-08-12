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

    def __init__(self, *args, closed_event=None, **kwargs):
        super().__init__(*args, **kwargs)
        self._cancel_event = threading.Event()
        self._thread = None
        # Set once _on_status("success") reports success. Kodi can re-fire
        # onInit on this window afterward (the same "window re-activation"
        # behaviour noted below) - by then self._thread has finished, so the
        # is_alive() check alone wouldn't stop a second device-code request
        # from starting on an already-completed login. Also read by
        # lib.main.run() to know when to open Home - _on_status runs on the
        # background polling thread, and xbmcgui window creation must happen
        # on the main thread, so this window can't just open Home itself the
        # way Home/Discover do from their (main-thread) onAction handlers.
        self.login_succeeded = False
        # The whole navigation chain (Login -> Home -> Discover -> Login ...)
        # shares ONE closed_event: main.run() blocks on the FIRST window's
        # event, so a window handing off to another must pass its own event
        # along rather than creating a fresh one, or the script would tear
        # down (destroying the newly-shown window) the moment the parent set
        # its own event.
        self.closed_event = closed_event or threading.Event()

    def onInit(self):
        if self.login_succeeded:
            return
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
            # Don't open Home here: this callback runs on the background
            # polling thread, and creating/showing an xbmcgui window must
            # happen on the main thread. lib.main.run()'s wait loop picks
            # this flag up and does the actual handoff.
            self.login_succeeded = True

    def onAction(self, action):
        if action.getId() in (xbmcgui.ACTION_PREVIOUS_MENU, xbmcgui.ACTION_NAV_BACK):
            self._cancel_event.set()
            self.close()
            self.closed_event.set()
