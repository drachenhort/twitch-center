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
    assert {101, 102, 103, 104, 105, 106, 107} <= control_ids


def test_home_skin_focusable_controls_are_reachable_by_navigation():
    # The lists used to point only at each other, leaving the Discover and
    # "Log in again" buttons with no incoming nav edge - unreachable with a
    # remote on the normal populated-list path.
    targets = _nav_targets(HOME_SKIN_XML)
    for control_id in (104, 105, 106):
        assert control_id in targets, f"control {control_id} is not a navigation target"


def test_discover_skin_focusable_controls_are_reachable_by_navigation():
    targets = _nav_targets(DISCOVER_SKIN_XML)
    for control_id in (104, 105, 106, 107):
        assert control_id in targets, f"control {control_id} is not a navigation target"
