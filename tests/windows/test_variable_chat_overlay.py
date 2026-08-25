from lib.windows.variable_chat_overlay import (
    _block_controls,
    _block_height,
    _build_block,
    _message_metrics,
)


def _build_block_for(event):
    lines, emotes, height = _message_metrics(event)
    return _build_block(event, lines, emotes, height)


def test_block_height_one_line_no_emotes():
    assert _block_height(1, has_emotes=False) == 100


def test_block_height_three_lines_no_emotes():
    assert _block_height(3, has_emotes=False) == 188


def test_block_height_five_lines_with_emotes():
    assert _block_height(5, has_emotes=True) == 312


def test_build_block_short_message_has_username_and_message_controls():
    event = {"display_name": "Bob", "text": "hi", "emotes": []}
    block = _build_block_for(event)
    controls = _block_controls(block)
    assert len(controls) == 2
    username_label, message_label = controls
    assert username_label.getLabel() == "Bob"
    assert message_label.getLabel() == "hi"
    assert block["height"] == _block_height(1, has_emotes=False)


def test_build_block_includes_emote_images_positioned_below_message():
    event = {
        "display_name": "Bob",
        "text": "hi",
        "emotes": [{"id": "1", "text": "Kappa", "url": "https://example.invalid/1.png"}],
    }
    block = _build_block_for(event)
    controls = _block_controls(block)
    assert len(controls) == 3
    emote_control = controls[2]
    assert emote_control.getFileName() == "https://example.invalid/1.png"
    assert block["height"] == _block_height(1, has_emotes=True)


def test_build_block_skips_emotes_with_no_url():
    event = {
        "display_name": "Bob",
        "text": "hi",
        "emotes": [{"id": "1", "text": "Kappa", "url": None}],
    }
    block = _build_block_for(event)
    controls = _block_controls(block)
    assert len(controls) == 2
    assert block["height"] == _block_height(1, has_emotes=False)


def test_build_block_allows_up_to_nine_lines():
    long_text = (
        "which upcoming games are you looking forward to for the rest of this year, "
        "modz? asking because I want to plan my backlog around the big releases"
    )
    event = {"display_name": "Bob", "text": long_text, "emotes": []}
    block = _build_block_for(event)
    controls = _block_controls(block)
    message_label = controls[1]
    lines = message_label.getLabel().split("\n")
    assert len(lines) == 6
    assert not lines[-1].endswith("...")
    assert block["height"] == _block_height(6, has_emotes=False)


def test_build_block_truncates_beyond_nine_lines():
    long_text = " ".join("word%d" % i for i in range(80))
    event = {"display_name": "Bob", "text": long_text, "emotes": []}
    block = _build_block_for(event)
    controls = _block_controls(block)
    message_label = controls[1]
    lines = message_label.getLabel().split("\n")
    assert len(lines) == 9
    assert lines[-1].endswith("...")
    assert block["height"] == _block_height(9, has_emotes=False)


from unittest.mock import patch

from lib.windows.variable_chat_overlay import (
    _COLUMN_HEIGHT,
    _COLUMN_Y,
    VariableChatOverlay,
)


class FakeChatClient:
    instances = []

    def __init__(self, channel, access_token=None, client_id=None, broadcaster_user_id=None,
                 user_id=None):
        self.channel = channel
        self.connected = False
        self.disconnected = False
        self._events = []
        FakeChatClient.instances.append(self)

    def connect(self):
        self.connected = True

    def read_messages(self):
        return iter(self._events)

    def disconnect(self):
        self.disconnected = True


def _message_event(username, text, index=0):
    return {
        "type": "message",
        "username": username,
        "display_name": username.capitalize(),
        "text": text,
        "timestamp": index,
    }


def _make_overlay(events):
    class ClientWithEvents(FakeChatClient):
        def __init__(self, channel, **kwargs):
            super().__init__(channel, **kwargs)
            self._events = events

    win = VariableChatOverlay(
        "script-twitch-center-chat-overlay.xml",
        "/tmp",
        "Default",
        "1080i",
        channel="somechannel",
        chat_client_cls=ClientWithEvents,
    )
    win.onInit()
    win._thread.join(timeout=1)
    assert not win._thread.is_alive()
    return win


def test_single_message_block_is_positioned_at_the_bottom_of_the_column():
    FakeChatClient.instances.clear()
    win = _make_overlay([_message_event("bob", "hi", 1)])

    assert len(win._blocks) == 1
    block = win._blocks[0]
    username_control = block["items"][0][0]
    expected_top = _COLUMN_Y + _COLUMN_HEIGHT - block["height"]
    assert username_control.getPosition()[1] == expected_top


def test_newer_message_is_positioned_below_older_message():
    FakeChatClient.instances.clear()
    win = _make_overlay([
        _message_event("bob", "hi", 1),
        _message_event("carol", "hello there", 2),
    ])

    assert len(win._blocks) == 2
    older_block, newer_block = win._blocks
    older_y = older_block["items"][0][0].getPosition()[1]
    newer_y = newer_block["items"][0][0].getPosition()[1]
    assert newer_y > older_y


def test_controls_from_earlier_render_are_repositioned_not_recreated():
    FakeChatClient.instances.clear()
    win = _make_overlay([
        _message_event("bob", "hi", 1),
        _message_event("carol", "hello there", 2),
    ])

    first_call_controls = win._blocks[0]["items"][0][0]
    win._render()
    second_call_controls = win._blocks[0]["items"][0][0]
    assert first_call_controls is second_call_controls


def test_old_blocks_are_evicted_once_total_height_exceeds_the_column():
    FakeChatClient.instances.clear()
    # Each of these wraps to 6 lines with no emotes - block height 40 + 6*44 + 16 = 320px. Three
    # of them (960px) exactly fill the 960px column, so the two oldest should be evicted.
    long_text = (
        "which upcoming games are you looking forward to for the rest of this year, "
        "modz? asking because I want to plan my backlog around the big releases"
    )
    events = [_message_event("user%d" % i, long_text, i) for i in range(5)]
    win = _make_overlay(events)

    assert len(win._blocks) == 3
    usernames = [block["items"][0][0].getLabel() for block in win._blocks]
    assert usernames == ["User2", "User3", "User4"]


def test_burst_of_messages_never_adds_a_control_only_to_evict_it_same_tick():
    # A message that would be evicted in the same _render() call that creates it must never
    # be handed to addControl() at all - see _render()'s comment on why an add-then-remove
    # within one call can leave an orphaned control on some Kodi builds. Bypasses the pump
    # thread/throttle entirely and calls _render() directly once, over a burst of messages
    # that together overflow the column, to force everything through a single call.
    FakeChatClient.instances.clear()
    long_text = (
        "which upcoming games are you looking forward to for the rest of this year, "
        "modz? asking because I want to plan my backlog around the big releases"
    )
    win = VariableChatOverlay(
        "script-twitch-center-chat-overlay.xml",
        "/tmp",
        "Default",
        "1080i",
        channel="somechannel",
        chat_client_cls=FakeChatClient,
    )
    win._messages = [_message_event("user%d" % i, long_text, i) for i in range(5)]
    win._render()

    assert len(win._blocks) == 3
    usernames = [block["items"][0][0].getLabel() for block in win._blocks]
    assert usernames == ["User2", "User3", "User4"]
    # Every control ever added is still a live, surviving block's control - none of the
    # evicted users' controls ever touched _added_controls.
    surviving_controls = set()
    for block in win._blocks:
        surviving_controls.update(_block_controls(block))
    assert set(win._added_controls) == surviving_controls


def test_a_single_message_taller_than_the_column_is_still_shown():
    # With real constants, a single block (max 312px, 5 lines + emotes) can never exceed the
    # real 960px column - this patches the column height down so the overflow-safety branch
    # (newest block always kept, even if it alone doesn't fit) is actually exercised.
    FakeChatClient.instances.clear()
    with patch("lib.windows.variable_chat_overlay._COLUMN_HEIGHT", 50):
        win = _make_overlay([_message_event("bob", "hi", 1)])

    assert len(win._blocks) == 1
    assert win._blocks[0]["items"][0][0].getLabel() == "Bob"


def test_close_removes_all_remaining_controls():
    FakeChatClient.instances.clear()
    win = _make_overlay([_message_event("bob", "hi", 1)])
    controls = win._blocks[0]["items"]
    controls = [control for control, _x, _rel_y in controls]
    assert controls
    for control in controls:
        assert control in win._added_controls

    win.close()

    assert win._blocks == []
    for control in controls:
        assert control not in win._added_controls
