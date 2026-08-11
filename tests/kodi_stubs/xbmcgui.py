"""Minimal stand-in for Kodi's built-in xbmcgui module, for pytest-only use."""

ACTION_PREVIOUS_MENU = 10
ACTION_NAV_BACK = 92


class Action:
    def __init__(self, action_id):
        self._action_id = action_id

    def getId(self):
        return self._action_id


class ControlLabel:
    def __init__(self):
        self._label = ""

    def setLabel(self, text):
        self._label = text

    def getLabel(self):
        return self._label


class WindowXML:
    def __init__(self, xml_filename, script_path, default_skin="Default", default_res="1080i"):
        self.xml_filename = xml_filename
        self.script_path = script_path
        self._controls = {}

    def show(self):
        pass

    def close(self):
        pass

    def getControl(self, control_id):
        if control_id not in self._controls:
            self._controls[control_id] = ControlLabel()
        return self._controls[control_id]


class WindowXMLDialog(WindowXML):
    def doModal(self):
        pass
