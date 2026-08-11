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
