from unittest.mock import patch

import xbmcgui

from lib.windows.raid_prompt import RaidPromptDialog


def _dialog(**kwargs):
    kwargs.setdefault("sleep_fn", lambda seconds: None)
    return RaidPromptDialog(
        "script-twitch-center-raid-prompt.xml", "/tmp", "Default", "1080i", **kwargs
    )


def test_prompt_shows_non_modally_instead_of_domodal():
    # doModal() blocks the calling thread inside Kodi's own modal wait loop - calling it from
    # ChatOverlay's background pump thread (rather than the addon's single main/invoker
    # thread, which already runs its own persistent doModal() loop for MainWindow) left
    # Kodi's window manager permanently stuck thinking a modal dialog was active, confirmed
    # live via kodi.log ("Activate of window '10000' refused because there are active modal
    # dialogs", still true 27+ minutes after the dialog should have closed). show()/close()
    # is the same non-modal pattern ChatOverlay itself already uses safely from background
    # threads elsewhere in this codebase.
    dialog = _dialog()
    with patch.object(dialog, "show") as show, patch.object(dialog, "doModal") as do_modal:
        dialog.prompt(display_name="X", to_channel="target", viewer_count=5, on_result=lambda a: None)
    show.assert_called_once()
    do_modal.assert_not_called()


def test_countdown_reaching_zero_invokes_on_result_true_and_closes():
    # The WindowXML stub's show() is a no-op and never calls onInit() the way real Kodi
    # does - call it explicitly, same as ChatOverlay's own tests do for the same reason.
    results = []
    dialog = _dialog(countdown_seconds=2)
    with patch.object(dialog, "close") as close:
        dialog.prompt(
            display_name="X", to_channel="target", viewer_count=5, on_result=results.append
        )
        dialog.onInit()
        dialog._thread.join(timeout=1)
        assert not dialog._thread.is_alive()
        close.assert_called_once()
    assert results == [True]


def test_decline_button_invokes_on_result_false_and_closes():
    results = []
    dialog = _dialog()
    with patch.object(dialog, "close") as close:
        dialog.prompt(
            display_name="X", to_channel="target", viewer_count=5, on_result=results.append
        )
        dialog.onClick(RaidPromptDialog.DECLINE_BUTTON_ID)
        close.assert_called_once()
    assert results == [False]


def test_back_action_invokes_on_result_false_and_closes():
    results = []
    dialog = _dialog()
    with patch.object(dialog, "close") as close:
        dialog.prompt(
            display_name="X", to_channel="target", viewer_count=5, on_result=results.append
        )
        dialog.onAction(xbmcgui.Action(xbmcgui.ACTION_NAV_BACK))
        close.assert_called_once()
    assert results == [False]


def test_other_actions_do_not_finish_the_prompt():
    results = []
    dialog = _dialog()
    with patch.object(dialog, "close") as close:
        dialog.prompt(
            display_name="X", to_channel="target", viewer_count=5, on_result=results.append
        )
        dialog.onAction(xbmcgui.Action(999))
        close.assert_not_called()
    assert results == []


def test_decline_after_countdown_already_finished_does_not_invoke_on_result_twice():
    # Guards the race between the countdown thread finishing and a Decline click landing at
    # nearly the same moment - on_result must fire exactly once either way.
    results = []
    dialog = _dialog(countdown_seconds=1)
    with patch.object(dialog, "close"):
        dialog.prompt(
            display_name="X", to_channel="target", viewer_count=5, on_result=results.append
        )
        dialog.onInit()
        dialog._thread.join(timeout=1)
        dialog.onClick(RaidPromptDialog.DECLINE_BUTTON_ID)
    assert results == [True]


def test_countdown_label_shows_raid_details_and_final_second():
    dialog = _dialog(countdown_seconds=2)
    with patch.object(dialog, "close"):
        dialog.prompt(
            display_name="SomeRaider", to_channel="target", viewer_count=17,
            on_result=lambda accepted: None,
        )
        dialog.onInit()
        dialog._thread.join(timeout=1)
    label = dialog.getControl(RaidPromptDialog.COUNTDOWN_LABEL_ID).getLabel()
    assert "SomeRaider" in label
    assert "target" in label
    assert "17" in label
    assert "1" in label  # countdown's last update before hitting zero and closing
