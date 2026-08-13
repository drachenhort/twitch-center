# tests/test_addon_manifest.py
import xml.etree.ElementTree as ET
from pathlib import Path

ADDON_XML = Path(__file__).resolve().parent.parent / "addon.xml"
SETTINGS_XML = Path(__file__).resolve().parent.parent / "resources" / "settings.xml"
CHAT_OVERLAY_SKIN_XML = (
    Path(__file__).resolve().parent.parent
    / "resources"
    / "skins"
    / "Default"
    / "1080i"
    / "script-twitch-center-chat-overlay.xml"
)
MAIN_SKIN_XML = (
    Path(__file__).resolve().parent.parent
    / "resources"
    / "skins"
    / "Default"
    / "1080i"
    / "script-twitch-center-main.xml"
)

def test_addon_xml_parses_with_expected_id():
    tree = ET.parse(ADDON_XML)
    root = tree.getroot()
    assert root.tag == "addon"
    assert root.attrib["id"] == "script.twitch.center"
    assert root.attrib["name"] == "Twitch Center"


def test_addon_xml_declares_script_extension():
    tree = ET.parse(ADDON_XML)
    root = tree.getroot()
    extensions = root.findall("extension")
    points = [ext.attrib.get("point") for ext in extensions]
    assert "xbmc.python.script" in points


def test_settings_xml_declares_show_offline_channels_defaulting_to_false():
    tree = ET.parse(SETTINGS_XML)
    root = tree.getroot()
    setting_ids = {s.attrib["id"]: s for s in root.iter("setting")}
    assert "show_offline_channels" in setting_ids
    default = setting_ids["show_offline_channels"].find("default")
    assert default is not None
    assert default.text == "false"


def test_settings_xml_declares_client_id_with_default():
    tree = ET.parse(SETTINGS_XML)
    root = tree.getroot()
    setting_ids = {s.attrib["id"]: s for s in root.iter("setting")}
    assert "client_id" in setting_ids
    default = setting_ids["client_id"].find("default")
    assert default is not None
    assert default.text == "f6exkvelsf4gmy83b8zat5i10t3gy6"


def test_settings_xml_declares_twitch_token_setting():
    tree = ET.parse(SETTINGS_XML)
    root = tree.getroot()
    setting_ids = {s.attrib["id"]: s for s in root.iter("setting")}
    assert "twitch_token" in setting_ids


def test_settings_xml_empty_default_string_settings_allow_empty():
    # A string setting with an empty <default></default> and no
    # <constraints><allowempty>true</allowempty></constraints> fails to
    # parse in real Kodi (CSettingString errors reading the default value,
    # and CSettingGroup then drops the setting entirely - it silently never
    # appears in the settings dialog, with no error visible to the user).
    # Confirmed live: twitch_token and website_token both hit this before
    # allowempty was added, verified fixed after.
    tree = ET.parse(SETTINGS_XML)
    root = tree.getroot()
    for setting in root.iter("setting"):
        if setting.attrib.get("type") != "string":
            continue
        default = setting.find("default")
        if default is None or not (default.text or "").strip():
            allowempty = setting.find("constraints/allowempty")
            assert allowempty is not None and allowempty.text == "true", (
                f"{setting.attrib['id']}: empty <default> needs "
                "<constraints><allowempty>true</allowempty></constraints> or Kodi "
                "silently drops this setting from the settings dialog"
            )


def test_addon_xml_requires_requests_module():
    tree = ET.parse(ADDON_XML)
    root = tree.getroot()
    requires = root.find("requires")
    assert requires is not None
    imports = requires.findall("import")
    addon_ids = [imp.attrib.get("addon") for imp in imports]
    assert "script.module.requests" in addon_ids


def test_settings_xml_hides_client_id_and_twitch_token():
    tree = ET.parse(SETTINGS_XML)
    root = tree.getroot()
    setting_ids = {s.attrib["id"]: s for s in root.iter("setting")}
    for setting_id in ("client_id", "twitch_token"):
        visible = setting_ids[setting_id].find("visible")
        assert visible is not None, f"{setting_id} should have a <visible> element"
        assert visible.text == "false"


def test_settings_xml_website_token_is_visible_and_unmasked():
    tree = ET.parse(SETTINGS_XML)
    root = tree.getroot()
    setting_ids = {s.attrib["id"]: s for s in root.iter("setting")}
    setting = setting_ids["website_token"]
    assert setting.find("visible") is None, "website_token should not be hidden"
    assert setting.find("control/hidden") is None, "website_token should not be masked"


def test_addon_xml_requires_inputstreamhelper_module():
    tree = ET.parse(ADDON_XML)
    root = tree.getroot()
    requires = root.find("requires")
    assert requires is not None
    imports = requires.findall("import")
    addon_ids = [imp.attrib.get("addon") for imp in imports]
    assert "script.module.inputstreamhelper" in addon_ids


def test_chat_overlay_skin_xml_declares_message_list_control_id():
    tree = ET.parse(CHAT_OVERLAY_SKIN_XML)
    root = tree.getroot()
    control_ids = {
        int(control.attrib["id"])
        for control in root.iter("control")
        if "id" in control.attrib
    }
    assert 101 in control_ids


def _main_skin_control_ids():
    """Every control id declared anywhere in the merged skin file, including
    inside nested <group> blocks - Kodi resolves ids window-wide regardless
    of group nesting (see the persistent-window-architecture design spec),
    so this deliberately does not scope by group."""
    root = ET.parse(MAIN_SKIN_XML).getroot()
    return [
        int(control.attrib["id"])
        for control in root.iter("control")
        if "id" in control.attrib
    ]


def _control_type(root, control_id):
    for control in root.iter("control"):
        if control.attrib.get("id") == str(control_id):
            return control.attrib.get("type")
    return None


def test_main_skin_defaultcontrol_is_not_a_data_dependent_list():
    # <defaultcontrol always="true"> forces Kodi to focus that control the
    # moment the window activates - natively, before Python's onInit ever
    # runs. If that control is a "list" that's still empty at skin-parse
    # time (populated later, by onInit), the focus attempt fails and Kodi's
    # window manager reverts the whole activation back to the previous
    # window (CGUIWindowManager::PreviousWindow) - confirmed live, pre-merge,
    # on both Home and Discover, with zero error logged and onInit never
    # called. No amount of Python-side setFocusId() can fix this, since it
    # happens before Python gets a chance to run at all - the skin must
    # target an always-valid control (a button, not a data-populated list).
    # This is the exact bug class the whole persistent-window-architecture
    # migration exists to eliminate, so it's covered here even though the
    # window is now a single merged file instead of five separate ones.
    root = ET.parse(MAIN_SKIN_XML).getroot()
    defaultcontrol = root.find("defaultcontrol")
    assert defaultcontrol is not None
    control_id = int(defaultcontrol.text)
    control_type = _control_type(root, control_id)
    assert control_type != "list", (
        f"defaultcontrol {control_id} is a list, which is empty at "
        "skin-parse time and will abort window activation"
    )


def test_main_skin_control_ids_are_unique_across_all_groups():
    # Kodi resolves control ids window-wide, even for controls nested inside
    # different <group> blocks - two views' controls sharing an id would
    # make getControl()/onClick() ambiguous or wrong, and merging five
    # formerly-separate skin files into one made this newly possible where
    # it wasn't before. See the design spec's id-renumbering note.
    control_ids = _main_skin_control_ids()
    duplicates = {cid for cid in control_ids if control_ids.count(cid) > 1}
    assert not duplicates, f"duplicate control ids across merged skin groups: {duplicates}"


def test_main_skin_xml_declares_all_expected_control_ids():
    # The Kodi stub auto-creates a fake control for any id on demand, so a
    # control genuinely missing from the skin XML would stay green in tests
    # but crash real Kodi at runtime. Cross-reference every view's declared
    # control-id constants against what the skin file actually declares.
    from lib.views.discover_view import (
        EMPTY_LABEL_ID as DISCOVER_EMPTY_LABEL_ID,
        ERROR_LABEL_ID as DISCOVER_ERROR_LABEL_ID,
        GAMES_LIST_ID as DISCOVER_GAMES_LIST_ID,
        RELOGIN_BUTTON_ID as DISCOVER_RELOGIN_BUTTON_ID,
        RESULTS_LIST_ID as DISCOVER_RESULTS_LIST_ID,
        SEARCH_BUTTON_ID as DISCOVER_SEARCH_BUTTON_ID,
        SEARCH_EDIT_ID as DISCOVER_SEARCH_EDIT_ID,
        SEARCH_MODE_TOGGLE_ID as DISCOVER_SEARCH_MODE_TOGGLE_ID,
    )
    from lib.views.live_streams_view import (
        CHANNEL_LIST_ID,
        EMPTY_LABEL_ID as LIVE_STREAMS_EMPTY_LABEL_ID,
        ERROR_LABEL_ID as LIVE_STREAMS_ERROR_LABEL_ID,
        GAMES_LIST_ID as LIVE_STREAMS_GAMES_LIST_ID,
        TITLE_LABEL_ID,
    )
    from lib.views.login_view import LoginView
    from lib.views.menu_view import MenuView
    from lib.views.search_view import SearchView

    expected_ids = {
        LoginView.CODE_LABEL_ID,
        LoginView.URL_LABEL_ID,
        LoginView.STATUS_LABEL_ID,
        MenuView.LIVE_STREAMS_BUTTON_ID,
        MenuView.DISCOVER_BUTTON_ID,
        MenuView.SEARCH_BUTTON_ID,
        MenuView.SETTINGS_BUTTON_ID,
        MenuView.RELOGIN_BUTTON_ID,
        CHANNEL_LIST_ID,
        LIVE_STREAMS_EMPTY_LABEL_ID,
        LIVE_STREAMS_ERROR_LABEL_ID,
        LIVE_STREAMS_GAMES_LIST_ID,
        TITLE_LABEL_ID,
        DISCOVER_RESULTS_LIST_ID,
        DISCOVER_EMPTY_LABEL_ID,
        DISCOVER_ERROR_LABEL_ID,
        DISCOVER_RELOGIN_BUTTON_ID,
        DISCOVER_GAMES_LIST_ID,
        DISCOVER_SEARCH_EDIT_ID,
        DISCOVER_SEARCH_BUTTON_ID,
        DISCOVER_SEARCH_MODE_TOGGLE_ID,
        SearchView.SEARCH_INPUT_ID,
        SearchView.RESULTS_LIST_ID,
        SearchView.STATUS_LABEL_ID,
        SearchView.NEXT_PAGE_BUTTON_ID,
    }
    control_ids = set(_main_skin_control_ids())
    assert expected_ids <= control_ids
