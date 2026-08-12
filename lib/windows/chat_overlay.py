"""Non-modal chat overlay shown during playback."""
import threading

import xbmcgui

from lib.twitch.irc import ChatClient


def _build_message_item(event):
    item = xbmcgui.ListItem(event["display_name"])
    item.setLabel2(event["text"])
    return item


class ChatOverlay(xbmcgui.WindowXMLDialog):
    MESSAGE_LIST_ID = 101
    _MAX_MESSAGES = 50

    def __init__(self, *args, channel, chat_client_cls=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.channel = channel
        self._chat_client_cls = chat_client_cls or ChatClient
        self._client = None
        self._messages = []
        self._cancel_event = threading.Event()
        self._thread = None

    def onInit(self):
        self._client = self._chat_client_cls(self.channel)
        self._client.connect()
        self._thread = threading.Thread(target=self._pump_messages, daemon=True)
        self._thread.start()

    def _pump_messages(self):
        for event in self._client.read_messages():
            if self._cancel_event.is_set():
                break
            if event["type"] != "message":
                continue
            self._messages.append(event)
            del self._messages[:-self._MAX_MESSAGES]
            self._render()

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
