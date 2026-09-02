"""Modal confirm dialog shown when the watched channel raids out to another one - offers
to switch playback there, auto-accepting after a countdown unless declined."""
import threading
import time

import xbmcgui

_DEFAULT_COUNTDOWN_SECONDS = 15


class RaidPromptDialog(xbmcgui.WindowXMLDialog):
    DECLINE_BUTTON_ID = 201
    COUNTDOWN_LABEL_ID = 202

    _DECLINE_ACTIONS = (
        xbmcgui.ACTION_PREVIOUS_MENU,
        xbmcgui.ACTION_NAV_BACK,
    )

    def __init__(self, *args, countdown_seconds=_DEFAULT_COUNTDOWN_SECONDS, sleep_fn=None,
                 **kwargs):
        super().__init__(*args, **kwargs)
        self._countdown_seconds = countdown_seconds
        self._sleep_fn = sleep_fn or time.sleep
        self._accepted = True
        self._display_name = ""
        self._to_channel = ""
        self._viewer_count = 0
        self._thread = None

    def prompt(self, display_name, to_channel, viewer_count):
        self._display_name = display_name
        self._to_channel = to_channel
        self._viewer_count = viewer_count
        self._accepted = True
        self.doModal()
        return self._accepted

    def onInit(self):
        self._update_label(self._countdown_seconds)
        self._thread = threading.Thread(target=self._countdown, daemon=True)
        self._thread.start()

    def _countdown(self):
        remaining = self._countdown_seconds
        while remaining > 0:
            self._sleep_fn(1)
            remaining -= 1
            self._update_label(remaining)
        self._accepted = True
        self.close()

    def _update_label(self, remaining):
        control = self._safe_control(self.COUNTDOWN_LABEL_ID)
        if control is None:
            return
        control.setLabel(
            "%s is raiding to %s (%d viewers) - switching in %ds" % (
                self._display_name, self._to_channel, self._viewer_count, remaining
            )
        )

    def _safe_control(self, control_id):
        try:
            return self.getControl(control_id)
        except Exception:
            return None

    def onClick(self, control_id):
        if control_id == self.DECLINE_BUTTON_ID:
            self._accepted = False
            self.close()

    def onAction(self, action):
        if action.getId() in self._DECLINE_ACTIONS:
            self._accepted = False
            self.close()
            return
        super().onAction(action)
