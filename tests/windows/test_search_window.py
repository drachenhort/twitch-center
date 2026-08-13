import xbmcgui

from lib.windows.search import SearchWindow


def test_oninit_does_not_raise_and_focuses_search_input():
    # Regression test: onInit used to call
    # self.getControl(SEARCH_INPUT_ID).setFocus(True), but Kodi's
    # xbmcgui.ControlEdit has no setFocus method (only Window.setFocusId
    # exists for this) - the resulting uncaught AttributeError crashed
    # onInit, which Kodi's window manager reacted to by silently reverting
    # to the previous window. Symptom looked like "search flashes open then
    # bounces back to Home".
    win = SearchWindow("script-twitch-center-search.xml", "/tmp")
    win.onInit()
    assert win.getFocusId() == SearchWindow.SEARCH_INPUT_ID
    assert win.getControl(SearchWindow.STATUS_LABEL_ID).getLabel() == ""


def test_back_requests_quit():
    win = SearchWindow("script-twitch-center-search.xml", "/tmp")
    win.onAction(xbmcgui.Action(xbmcgui.ACTION_NAV_BACK))
    assert win.closed_event.quit_requested is True
