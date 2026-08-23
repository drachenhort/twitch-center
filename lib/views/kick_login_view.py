"""Kick login view: PKCE flow, displays the authorize URL to open on another
device, waits for the loopback callback. Not a Window subclass - see
MainWindow. Mirrors lib/views/login_view.py's shape (fresh flow per visit,
stale-callback guarding via a per-flow cancel_event) but drives
kick.auth.run_pkce_login instead of twitch.auth.run_device_code_login - see
that module's docstring for how the two callback contracts differ."""
import functools
import threading

import xbmc
import xbmcaddon

from lib.kick import auth

STATUS_MESSAGES = {
    "pending": "Waiting for authorization...",
    "expired": "Timed out waiting for authorization. Reopen this screen to try again.",
    "denied": "Access denied. Reopen this screen to try again.",
    "success": "Logged in!",
    "error": "Connection error. Reopen this screen to try again.",
}


class KickLoginView:
    URL_LABEL_ID = 601
    STATUS_LABEL_ID = 602
    CANCEL_BUTTON_ID = 603
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
        # Same reasoning as LoginView.activate(): a set cancel_event means
        # "the previous visit is over" (MainWindow calls stop() on navigating
        # away), so the guards below only exist to absorb Kodi re-firing
        # onInit/activation WITHIN the current visit, not across visits.
        resuming_after_stop = self._cancel_event.is_set()
        if not resuming_after_stop:
            if self.login_succeeded:
                return
            if self._thread is not None and self._thread.is_alive():
                return
        self.login_succeeded = False
        self._cancel_event = threading.Event()
        cancel_event = self._cancel_event
        on_code = functools.partial(self._on_code, cancel_event)
        on_status = functools.partial(self._on_status, cancel_event)

        addon = xbmcaddon.Addon()
        client_id = addon.getSetting("kick_client_id")
        client_secret = addon.getSetting("kick_client_secret")
        # settings.xml declares a <default>8919</default> for this setting,
        # but the addon-under-test stub (and a real profile that never
        # opened Settings) can still hand back "" - fall back to the same
        # default rather than letting int() blow up.
        redirect_port = int(addon.getSetting("kick_redirect_port") or 8919)
        thread = threading.Thread(
            target=auth.run_pkce_login,
            kwargs={
                "client_id": client_id,
                "client_secret": client_secret,
                "redirect_port": redirect_port,
                "addon": addon,
                "on_code": on_code,
                "on_status": on_status,
                "cancel_event": cancel_event,
                "scopes": auth.SCOPES,
            },
        )
        thread.daemon = True
        thread.start()
        self._thread = thread

    def _on_code(self, cancel_event, url):
        if cancel_event.is_set():
            return
        self.window.getControl(self.URL_LABEL_ID).setLabel(url)
        # Also written to the log so a copy/paste-capable terminal on the
        # same machine can grab it verbatim - the on-screen label alone is
        # painful to transcribe by hand. Safe to log: contains client_id
        # (public), redirect_uri, scope, state, and code_challenge - no
        # secret, per PKCE's design (the challenge is meant to be public).
        xbmc.log("script.twitch.center: Kick authorize URL: " + url, xbmc.LOGINFO)

    def _on_status(self, cancel_event, status, detail=None):
        if cancel_event.is_set():
            return
        if status in ("error", "denied"):
            xbmc.log(
                "script.twitch.center: Kick PKCE login reported status=%s detail=%s" % (status, detail),
                xbmc.LOGERROR,
            )
        message = STATUS_MESSAGES.get(status, "")
        self.window.getControl(self.STATUS_LABEL_ID).setLabel(message)
        if status == "success":
            self.login_succeeded = True

    def handle_action(self, action):
        pass

    def handle_click(self, control_id):
        pass
