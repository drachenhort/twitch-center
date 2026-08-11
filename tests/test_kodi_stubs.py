def test_xbmc_stub_importable():
    import xbmc
    assert xbmc.LOGINFO is not None
    xbmc.log("hello", level=xbmc.LOGINFO)  # must not raise


def test_xbmcgui_stub_windowxml_constructible():
    import xbmcgui
    win = xbmcgui.WindowXML("dummy.xml", "/tmp")
    win.show()
    win.close()


def test_xbmcgui_stub_windowxmldialog_constructible():
    import xbmcgui
    dlg = xbmcgui.WindowXMLDialog("dummy.xml", "/tmp")
    dlg.doModal()
    dlg.close()


def test_xbmcaddon_stub_addon_getters():
    import xbmcaddon
    addon = xbmcaddon.Addon()
    assert addon.getSetting("chat_display_mode") == ""
    assert addon.getSettingBool("does_not_exist") is False
    assert addon.getAddonInfo("id") == "script.twitch.center"


def test_xbmcgui_stub_action_constants_and_getid():
    import xbmcgui
    assert xbmcgui.ACTION_PREVIOUS_MENU == 10
    assert xbmcgui.ACTION_NAV_BACK == 92
    action = xbmcgui.Action(92)
    assert action.getId() == 92


def test_xbmcgui_stub_control_label_set_and_get():
    import xbmcgui
    label = xbmcgui.ControlLabel()
    label.setLabel("hello")
    assert label.getLabel() == "hello"


def test_xbmcgui_stub_windowxml_getcontrol_returns_label_and_persists():
    import xbmcgui
    win = xbmcgui.WindowXML("dummy.xml", "/tmp")
    control = win.getControl(101)
    control.setLabel("world")
    assert win.getControl(101).getLabel() == "world"
    assert win.getControl(102).getLabel() == ""
