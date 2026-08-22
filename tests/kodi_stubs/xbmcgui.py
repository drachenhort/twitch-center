"""Minimal stand-in for Kodi's built-in xbmcgui module, for pytest-only use."""

ACTION_PREVIOUS_MENU = 10
ACTION_NAV_BACK = 92
ACTION_SELECT_ITEM = 7


class Action:
    def __init__(self, action_id):
        self._action_id = action_id

    def getId(self):
        return self._action_id


class ListItem:
    def __init__(self, label="", path=""):
        self._label = label
        self._label2 = ""
        self._art = {}
        self._properties = {}
        self._path = path
        self._mimetype = ""
        self._content_lookup = True

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

    def setPath(self, path):
        self._path = path

    def getPath(self):
        return self._path

    def setMimeType(self, mimetype):
        self._mimetype = mimetype

    def getMimeType(self):
        return self._mimetype

    def setContentLookup(self, enabled):
        self._content_lookup = enabled

    def getContentLookup(self):
        return self._content_lookup


class FakeListControl:
    def __init__(self):
        self._label = ""
        self._items = []
        self._visible = True
        self._selected_index = 0

    def setLabel(self, text):
        self._label = text

    def getLabel(self):
        return self._label

    def setText(self, text):
        self._label = text

    def getText(self):
        return self._label

    def addItems(self, items):
        self._items.extend(items)

    def reset(self):
        self._items = []
        self._selected_index = 0

    def removeItem(self, index):
        del self._items[index]

    def size(self):
        return len(self._items)

    def getSelectedItem(self):
        if not self._items:
            return None
        index = min(self._selected_index, len(self._items) - 1)
        return self._items[index]

    def selectItem(self, index):
        self._selected_index = index

    def setVisible(self, visible):
        self._visible = visible

    def isVisible(self):
        return self._visible

    def setEnabled(self, enabled):
        self._enabled = enabled

    def isEnabled(self):
        return getattr(self, "_enabled", True)


class WindowXML:
    def __init__(self, xml_filename, script_path, default_skin="Default", default_res="1080i"):
        self.xml_filename = xml_filename
        self.script_path = script_path
        self._controls = {}
        self._focus_id = None

    def show(self):
        pass

    def close(self):
        pass

    def getControl(self, control_id):
        if control_id not in self._controls:
            self._controls[control_id] = FakeListControl()
        return self._controls[control_id]

    def setFocusId(self, control_id):
        self._focus_id = control_id

    def getFocusId(self):
        return self._focus_id


class WindowXMLDialog(WindowXML):
    def doModal(self):
        pass
