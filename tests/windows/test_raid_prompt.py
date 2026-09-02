from unittest.mock import patch

import xbmcgui

from lib.windows.raid_prompt import RaidPromptDialog


def _dialog(**kwargs):
    kwargs.setdefault("sleep_fn", lambda seconds: None)
    return RaidPromptDialog(
        "script-twitch-center-raid-prompt.xml", "/tmp", "Default", "1080i", **kwargs
    )


def test_countdown_reaching_zero_auto_accepts_and_closes():
    dialog = _dialog(countdown_seconds=2)
    with patch.object(dialog, "close") as close:
        dialog.onInit()
        dialog._thread.join(timeout=1)
        assert not dialog._thread.is_alive()
        close.assert_called_once()
    assert dialog._accepted is True


def test_decline_button_click_declines_and_closes():
    dialog = _dialog()
    with patch.object(dialog, "close") as close:
        dialog.onClick(RaidPromptDialog.DECLINE_BUTTON_ID)
        close.assert_called_once()
    assert dialog._accepted is False


def test_back_action_declines_and_closes():
    dialog = _dialog()
    with patch.object(dialog, "close") as close:
        dialog.onAction(xbmcgui.Action(xbmcgui.ACTION_NAV_BACK))
        close.assert_called_once()
    assert dialog._accepted is False


def test_other_actions_are_not_treated_as_decline():
    dialog = _dialog()
    with patch.object(dialog, "close") as close:
        dialog.onAction(xbmcgui.Action(999))
        close.assert_not_called()
    assert dialog._accepted is True


def test_countdown_label_shows_raid_details_and_final_second():
    dialog = _dialog(countdown_seconds=2)
    dialog._display_name = "SomeRaider"
    dialog._to_channel = "target"
    dialog._viewer_count = 17
    with patch.object(dialog, "close"):
        dialog.onInit()
        dialog._thread.join(timeout=1)
    label = dialog.getControl(RaidPromptDialog.COUNTDOWN_LABEL_ID).getLabel()
    assert "SomeRaider" in label
    assert "target" in label
    assert "17" in label
    assert "1" in label  # countdown's last update before hitting zero and closing
