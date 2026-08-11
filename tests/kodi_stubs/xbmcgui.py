"""Minimal stand-in for Kodi's built-in xbmcgui module, for pytest-only use."""

ACTION_PREVIOUS_MENU = 10
ACTION_NAV_BACK = 92


class Action:
    def __init__(self, action_id):
        self._action_id = action_id

    def getId(self):
        return self._action_id


class ListItem:
    def __init__(self, label=""):
        self._label = label
        self._label2 = ""
        self._art = {}
        self._properties = {}

    def setLabel(self, text):
        self._label = text

    def getLabel(self):
        return self._label

    def setLabel2(self, text):
        self._label2 = text

    def getLabel2(self):
        return self._label2

    def setArt(self, art):
        self._art.update(art)

    def getArt(self, key):
        return self._art.get(key, "")

    def setProperty(self, key, value):
        self._properties[key] = value

    def getProperty(self, key):
        return self._properties.get(key, "")


class ControlLabel:
    def __init__(self):
        self._label = ""
        self._items = []

    def setLabel(self, text):
        self._label = text

    def getLabel(self):
        return self._label

    def addItems(self, items):
        self._items.extend(items)

    def reset(self):
        self._items = []

    def size(self):
        return len(self._items)

    def getSelectedItem(self):
        return self._items[0] if self._items else None


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
