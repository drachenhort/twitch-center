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
    label = xbmcgui.FakeListControl()
    label.setLabel("hello")
    assert label.getLabel() == "hello"


def test_xbmcgui_stub_windowxml_getcontrol_returns_label_and_persists():
    import xbmcgui
    win = xbmcgui.WindowXML("dummy.xml", "/tmp")
    control = win.getControl(101)
    control.setLabel("world")
    assert win.getControl(101).getLabel() == "world"
    assert win.getControl(102).getLabel() == ""


def test_xbmcgui_stub_listitem_label_and_label2():
    import xbmcgui
    item = xbmcgui.ListItem("Channel Name")
    assert item.getLabel() == "Channel Name"
    item.setLabel2("playing Foo")
    assert item.getLabel2() == "playing Foo"


def test_xbmcgui_stub_listitem_art_and_properties():
    import xbmcgui
    item = xbmcgui.ListItem("Channel Name")
    item.setArt({"thumb": "https://example.invalid/thumb.jpg"})
    assert item.getArt("thumb") == "https://example.invalid/thumb.jpg"
    assert item.getArt("missing") == ""
    item.setProperty("broadcaster_id", "12345")
    assert item.getProperty("broadcaster_id") == "12345"
    assert item.getProperty("missing") == ""


def test_xbmcgui_stub_control_additems_reset_size_and_selection():
    import xbmcgui
    win = xbmcgui.WindowXML("dummy.xml", "/tmp")
    control = win.getControl(101)
    assert control.size() == 0
    assert control.getSelectedItem() is None
    item1 = xbmcgui.ListItem("First")
    item2 = xbmcgui.ListItem("Second")
    control.addItems([item1, item2])
    assert control.size() == 2
    assert control.getSelectedItem() is item1
    control.reset()
    assert control.size() == 0
    assert control.getSelectedItem() is None


def test_xbmcgui_stub_control_selectitem_changes_selected_item():
    import xbmcgui
    win = xbmcgui.WindowXML("dummy.xml", "/tmp")
    control = win.getControl(101)
    item1 = xbmcgui.ListItem("First")
    item2 = xbmcgui.ListItem("Second")
    control.addItems([item1, item2])
    assert control.getSelectedItem() is item1
    control.selectItem(1)
    assert control.getSelectedItem() is item2


def test_xbmcgui_stub_control_reset_clears_selection():
    import xbmcgui
    win = xbmcgui.WindowXML("dummy.xml", "/tmp")
    control = win.getControl(101)
    control.addItems([xbmcgui.ListItem("A"), xbmcgui.ListItem("B")])
    control.selectItem(1)
    control.reset()
    assert control.getSelectedItem() is None
    control.addItems([xbmcgui.ListItem("C")])
    assert control.getSelectedItem().getLabel() == "C"


def test_xbmcgui_stub_control_settext_gettext_round_trip():
    import xbmcgui
    win = xbmcgui.WindowXML("dummy.xml", "/tmp")
    control = win.getControl(106)
    assert control.getText() == ""
    control.setText("elden ring")
    assert control.getText() == "elden ring"


def test_xbmc_stub_player_play_does_not_raise():
    import xbmc
    player = xbmc.Player()
    player.play("https://example.invalid/stream.m3u8")


def test_xbmcgui_stub_listitem_path_and_playback_properties():
    import xbmcgui
    item = xbmcgui.ListItem(path="https://example.invalid/stream.m3u8")
    assert item.getPath() == "https://example.invalid/stream.m3u8"
    item.setPath("https://example.invalid/other.m3u8")
    assert item.getPath() == "https://example.invalid/other.m3u8"
    item.setMimeType("application/x-mpegURL")
    assert item.getMimeType() == "application/x-mpegURL"
    item.setContentLookup(False)
    assert item.getContentLookup() is False


def test_inputstreamhelper_stub_helper_check_inputstream():
    import inputstreamhelper
    helper = inputstreamhelper.Helper("hls")
    assert helper.inputstream_addon == "inputstream.adaptive"
    assert helper.check_inputstream() is True
