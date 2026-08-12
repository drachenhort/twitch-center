# tests/test_addon_manifest.py
import xml.etree.ElementTree as ET
from pathlib import Path

ADDON_XML = Path(__file__).resolve().parent.parent / "addon.xml"
SETTINGS_XML = Path(__file__).resolve().parent.parent / "resources" / "settings.xml"
HOME_SKIN_XML = (
    Path(__file__).resolve().parent.parent
    / "resources"
    / "skins"
    / "Default"
    / "1080i"
    / "script-twitch-center-home.xml"
)
DISCOVER_SKIN_XML = (
    Path(__file__).resolve().parent.parent
    / "resources"
    / "skins"
    / "Default"
    / "1080i"
    / "script-twitch-center-discover.xml"
)
CHAT_OVERLAY_SKIN_XML = (
    Path(__file__).resolve().parent.parent
    / "resources"
    / "skins"
    / "Default"
    / "1080i"
    / "script-twitch-center-chat-overlay.xml"
)

_NAV_TAGS = ("onup", "ondown", "onleft", "onright")


def _nav_targets(skin_xml):
    """Every control id referenced as the destination of a directional-nav
    element anywhere in the skin file."""
    root = ET.parse(skin_xml).getroot()
    targets = set()
    for tag in _NAV_TAGS:
        for element in root.iter(tag):
            if element.text and element.text.strip().isdigit():
                targets.add(int(element.text.strip()))
    return targets


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


def test_home_skin_xml_declares_all_expected_control_ids():
    # The Kodi stub auto-creates a fake control for any id on demand, so a
    # control genuinely missing from the skin XML would stay green in tests
    # but crash real Kodi at runtime. Verify the skin file itself declares
    # every control id the home window code references.
    tree = ET.parse(HOME_SKIN_XML)
    root = tree.getroot()
    control_ids = {
        int(control.attrib["id"])
        for control in root.iter("control")
        if "id" in control.attrib
    }
    assert {101, 102, 103, 104, 105, 106, 107} <= control_ids


def test_discover_skin_xml_declares_all_expected_control_ids():
    tree = ET.parse(DISCOVER_SKIN_XML)
    root = tree.getroot()
    control_ids = {
        int(control.attrib["id"])
        for control in root.iter("control")
        if "id" in control.attrib
    }
    assert {201, 202, 203, 204, 205, 206, 207, 208} <= control_ids


def test_discover_skin_control_ids_do_not_overlap_home():
    # Two non-modal script windows can be "resident" in Kodi's window manager
    # at once (Home stays alive, non-destroyed, while Discover is shown on
    # top of it). Non-overlapping IDs turned out NOT to be the fix for the
    # window-revert bug (that was <defaultcontrol> targeting an empty list -
    # see test_..._defaultcontrol_is_not_a_data_dependent_list below) but
    # distinct ID ranges between simultaneously-resident windows remains good
    # practice regardless, so this stays as a guard.
    home_ids = {
        int(control.attrib["id"])
        for control in ET.parse(HOME_SKIN_XML).getroot().iter("control")
        if "id" in control.attrib
    }
    discover_ids = {
        int(control.attrib["id"])
        for control in ET.parse(DISCOVER_SKIN_XML).getroot().iter("control")
        if "id" in control.attrib
    }
    assert not (home_ids & discover_ids)


def _defaultcontrol_id(skin_path):
    tree = ET.parse(skin_path)
    return int(tree.getroot().find("defaultcontrol").text)


def _control_type(skin_path, control_id):
    tree = ET.parse(skin_path)
    for control in tree.getroot().iter("control"):
        if control.attrib.get("id") == str(control_id):
            return control.attrib.get("type")
    return None


def test_home_and_discover_defaultcontrol_is_not_a_data_dependent_list():
    # <defaultcontrol always="true"> forces Kodi to focus that control the
    # moment the window activates - natively, before Python's onInit ever
    # runs. If that control is a "list" that's still empty at skin-parse
    # time (populated later, by onInit), the focus attempt fails and Kodi's
    # window manager reverts the whole activation back to the previous
    # window (CGUIWindowManager::PreviousWindow) - confirmed live, on both
    # Home and Discover, with zero error logged and onInit never called.
    # No amount of Python-side setFocusId() can fix this, since it happens
    # before Python gets a chance to run at all - the skin must target an
    # always-valid control (a button, not a data-populated list).
    for skin_path in (HOME_SKIN_XML, DISCOVER_SKIN_XML):
        control_id = _defaultcontrol_id(skin_path)
        control_type = _control_type(skin_path, control_id)
        assert control_type != "list", (
            f"{skin_path}: defaultcontrol {control_id} is a list, which is "
            "empty at skin-parse time and will abort window activation"
        )


def test_home_skin_focusable_controls_are_reachable_by_navigation():
    # The lists used to point only at each other, leaving the Discover and
    # "Log in again" buttons with no incoming nav edge - unreachable with a
    # remote on the normal populated-list path.
    targets = _nav_targets(HOME_SKIN_XML)
    for control_id in (104, 105, 106):
        assert control_id in targets, f"control {control_id} is not a navigation target"


def test_discover_skin_focusable_controls_are_reachable_by_navigation():
    targets = _nav_targets(DISCOVER_SKIN_XML)
    for control_id in (204, 205, 206, 207):
        assert control_id in targets, f"control {control_id} is not a navigation target"


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
