# tests/test_addon_manifest.py
import xml.etree.ElementTree as ET
from pathlib import Path

ADDON_XML = Path(__file__).resolve().parent.parent / "addon.xml"
SETTINGS_XML = Path(__file__).resolve().parent.parent / "resources" / "settings.xml"


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
