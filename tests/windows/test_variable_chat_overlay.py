from lib.windows.variable_chat_overlay import (
    _block_controls,
    _block_height,
    _build_block,
)


def test_block_height_one_line_no_emotes():
    assert _block_height(1, has_emotes=False) == 68


def test_block_height_three_lines_no_emotes():
    assert _block_height(3, has_emotes=False) == 152


def test_block_height_five_lines_with_emotes():
    assert _block_height(5, has_emotes=True) == 264


def test_build_block_short_message_has_username_and_message_controls():
    event = {"display_name": "Bob", "text": "hi", "emotes": []}
    block = _build_block(event)
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
    block = _build_block(event)
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
    block = _build_block(event)
    controls = _block_controls(block)
    assert len(controls) == 2
    assert block["height"] == _block_height(1, has_emotes=False)


def test_build_block_truncates_five_line_message_and_sizes_for_it():
    long_text = (
        "which upcoming games are you looking forward to for the rest of this year, "
        "modz? asking because I want to plan my backlog around the big releases"
    )
    event = {"display_name": "Bob", "text": long_text, "emotes": []}
    block = _build_block(event)
    controls = _block_controls(block)
    message_label = controls[1]
    lines = message_label.getLabel().split("\n")
    assert len(lines) == 5
    assert lines[-1].endswith("...")
    assert block["height"] == _block_height(5, has_emotes=False)
