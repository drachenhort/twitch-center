"""Non-modal chat overlay shown during playback."""
import threading
import time

import xbmc
import xbmcgui

from lib.twitch.irc import ChatClient

# Caps how often the message list is rebuilt, regardless of message rate -
# a busy channel's chat can arrive several messages/second, and without
# this a full control.reset()+addItems() per message floods the GUI
# thread badly enough to delay it processing input (e.g. Back).
_RENDER_THROTTLE_SECONDS = 0.25


def _build_message_item(event):
    item = xbmcgui.ListItem(event["display_name"])
    item.setLabel2(event["text"])
    return item


class ChatOverlay(xbmcgui.WindowXMLDialog):
    MESSAGE_LIST_ID = 101
    _MAX_MESSAGES = 50

    def __init__(self, *args, channel, chat_client_cls=None, time_fn=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.channel = channel
        self._chat_client_cls = chat_client_cls or ChatClient
        self._time_fn = time_fn or time.time
        self._client = None
        self._messages = []
        self._cancel_event = threading.Event()
        self._thread = None
        self._last_render_at = None

    def onInit(self):
        self._client = self._chat_client_cls(self.channel)
        self._client.connect()
        self._thread = threading.Thread(target=self._pump_messages, daemon=True)
        self._thread.start()

    def _pump_messages(self):
        try:
            for event in self._client.read_messages():
                if self._cancel_event.is_set():
                    break
                if event["type"] != "message":
                    continue
                self._messages.append(event)
                del self._messages[:-self._MAX_MESSAGES]
                now = self._time_fn()
                if self._last_render_at is None or now - self._last_render_at >= _RENDER_THROTTLE_SECONDS:
                    self._render()
                    self._last_render_at = now
            # Flush whatever arrived since the last throttled render, so the
            # overlay never ends up stuck showing a stale message set.
            self._render()
        except Exception as exc:
            xbmc.log(
                "script.twitch.center: chat overlay pump thread failed: " + repr(exc),
                xbmc.LOGERROR,
            )

    def _render(self):
        control = self._safe_control(self.MESSAGE_LIST_ID)
        if control:
            control.reset()
            control.addItems([_build_message_item(event) for event in self._messages])
            if self._messages:
                control.selectItem(len(self._messages) - 1)

    def _safe_control(self, control_id):
        try:
            return self.getControl(control_id)
        except Exception:
            return None

    def close(self):
        self._cancel_event.set()
        if self._client is not None:
            self._client.disconnect()
        super().close()
