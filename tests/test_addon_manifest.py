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
