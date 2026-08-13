import xbmcgui

from lib.views.search_view import SearchView


class FakeWindow:
    def __init__(self):
        self._controls = {}
        self._focus_id = None

    def getControl(self, control_id):
        from xbmcgui import ControlLabel

        if control_id not in self._controls:
            self._controls[control_id] = ControlLabel()
        return self._controls[control_id]

    def setFocusId(self, control_id):
        self._focus_id = control_id

    def getFocusId(self):
        return self._focus_id


def test_activate_does_not_raise_and_focuses_search_input():
    # Regression test: onInit used to call
    # self.getControl(SEARCH_INPUT_ID).setFocus(True), but Kodi's
    # xbmcgui.ControlEdit has no setFocus method (only Window.setFocusId
    # exists for this) - the resulting uncaught AttributeError crashed
    # onInit, which Kodi's window manager reacted to by silently reverting
    # to the previous window. Symptom looked like "search flashes open then
    # bounces back to Home".
    win = SearchView(FakeWindow())
    win.activate()
    assert win.window.getFocusId() == SearchView.SEARCH_INPUT_ID
    assert win.window.getControl(SearchView.STATUS_LABEL_ID).getLabel() == ""


def test_back_is_a_no_op_pass_through():
    win = SearchView(FakeWindow())
    win.handle_action(xbmcgui.Action(xbmcgui.ACTION_NAV_BACK))
    # No assertion beyond "doesn't raise" - Back is centralized in
    # MainWindow now; SearchView never sees ACTION_NAV_BACK in practice.
