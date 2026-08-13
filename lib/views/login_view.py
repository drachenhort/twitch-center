"""Login view: device-code login screen, displays the code + verification
URL, polls for auth. Not a Window subclass - see MainWindow."""
import functools
import threading

import xbmc
import xbmcaddon

from lib.twitch import auth

STATUS_MESSAGES = {
    "pending": "Waiting for authorization...",
    "expired": "Code expired. Reopen the addon to try again.",
    "success": "Logged in!",
    "error": "Connection error. Reopen the addon to try again.",
}


class LoginView:
    CODE_LABEL_ID = 101
    URL_LABEL_ID = 102
    STATUS_LABEL_ID = 103
    CANCEL_BUTTON_ID = 104
    # Matches the skin's <defaultcontrol always="true">104</defaultcontrol>,
    # so the native first-activation focus and every later switch to Login
    # agree on the same control.
    DEFAULT_FOCUS_ID = CANCEL_BUTTON_ID

    def __init__(self, window, closed_event=None):
        self.window = window
        self.closed_event = closed_event
        self._cancel_event = threading.Event()
        self._thread = None
        self.login_succeeded = False

    def stop(self):
        self._cancel_event.set()

    def activate(self):
        # This view is constructed once and reused for the whole session, so
        # every visit must be able to start a genuinely fresh device-code
        # flow. MainWindow calls stop() when it navigates away, which sets
        # _cancel_event - a set cancel event therefore means "the previous
        # visit is over", and the guards below (which only exist to absorb
        # Kodi re-firing onInit/activation WITHIN the current visit) are
        # deliberately skipped so re-login works any number of times.
        resuming_after_stop = self._cancel_event.is_set()
        if not resuming_after_stop:
            if self.login_succeeded:
                return
            if self._thread is not None and self._thread.is_alive():
                return
        self.login_succeeded = False
        self._cancel_event = threading.Event()
        # Bind this flow's callbacks to the cancel event that was just
        # created for it, via functools.partial, instead of letting them
        # read the mutable self._cancel_event attribute at call time. A
        # still-running previous flow's callbacks must keep checking the
        # event THEY were started (and cancelled) with - if they read
        # self._cancel_event instead, it would already have been rebound
        # above to the new flow's event, so the old flow's own cancellation
        # would go unnoticed and it could write stale data over the fresh
        # login screen.
        cancel_event = self._cancel_event
        on_code = functools.partial(self._on_code, cancel_event)
        on_status = functools.partial(self._on_status, cancel_event)

        addon = xbmcaddon.Addon()
        client_id = addon.getSetting("client_id")
        thread = threading.Thread(
            target=auth.run_device_code_login,
            kwargs={
                "client_id": client_id,
                "scopes": auth.SCOPES,
                "addon": addon,
                "on_code": on_code,
                "on_status": on_status,
                "cancel_event": cancel_event,
            },
        )
        thread.daemon = True
        thread.start()
        self._thread = thread

    def _on_code(self, cancel_event, user_code, verification_uri):
        if cancel_event.is_set():
            return
        self.window.getControl(self.CODE_LABEL_ID).setLabel(user_code)
        self.window.getControl(self.URL_LABEL_ID).setLabel(verification_uri)

    def _on_status(self, cancel_event, status):
        if cancel_event.is_set():
            return
        if status == "error":
            xbmc.log("script.twitch.center: device-code login reported an error", xbmc.LOGERROR)
        message = STATUS_MESSAGES.get(status, "")
        self.window.getControl(self.STATUS_LABEL_ID).setLabel(message)
        if status == "success":
            self.login_succeeded = True

    def handle_action(self, action):
        pass

    def handle_click(self, control_id):
        pass
