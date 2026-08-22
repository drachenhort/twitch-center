from lib.windows.chat_overlay import ChatOverlay


class _FakeChatClient:
    def __init__(self, channel, **kwargs):
        self.channel = channel

    def connect(self):
        pass

    def read_messages(self):
        return iter([])

    def disconnect(self):
        pass


def test_chat_overlay_constructs():
    overlay = ChatOverlay("chat_overlay.xml", "/tmp", channel="somechannel", chat_client_cls=_FakeChatClient)
    overlay.onInit()
    overlay._thread.join(timeout=1)
