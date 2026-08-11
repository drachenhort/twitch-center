"""Minimal stand-in for Kodi's built-in xbmcgui module, for pytest-only use."""


class WindowXML:
    def __init__(self, xml_filename, script_path, default_skin="Default", default_res="1080i"):
        self.xml_filename = xml_filename
        self.script_path = script_path

    def show(self):
        pass

    def close(self):
        pass


class WindowXMLDialog(WindowXML):
    def doModal(self):
        pass
