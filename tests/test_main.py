from lib import main


class FakeAddon:
    def __init__(self, token=None):
        self._token = token

    def getSetting(self, id):
        if id == "twitch_token":
            return '{"access_token": "tok"}' if self._token else ""
        return ""

    def getAddonInfo(self, id):
        if id == "path":
            return "/fake/addon/path"
        return ""


class FakeWindow:
    def __init__(self, xml_filename, script_path):
        self.xml_filename = xml_filename
        self.script_path = script_path
        self.shown = False

    def show(self):
        self.shown = True


class FakeLoginWindow(FakeWindow):
    instances = []

    def __init__(self, xml_filename, script_path):
        super().__init__(xml_filename, script_path)
        FakeLoginWindow.instances.append(self)


class FakeHomeWindow(FakeWindow):
    instances = []

    def __init__(self, xml_filename, script_path):
        super().__init__(xml_filename, script_path)
        FakeHomeWindow.instances.append(self)


def test_run_opens_login_window_when_no_token_saved():
    FakeLoginWindow.instances.clear()
    FakeHomeWindow.instances.clear()
    main.run(
        [],
        addon=FakeAddon(token=None),
        login_window_cls=FakeLoginWindow,
        home_window_cls=FakeHomeWindow,
    )
    assert len(FakeLoginWindow.instances) == 1
    assert FakeLoginWindow.instances[0].shown is True
    assert len(FakeHomeWindow.instances) == 0


def test_run_opens_home_window_when_token_saved():
    FakeLoginWindow.instances.clear()
    FakeHomeWindow.instances.clear()
    main.run(
        [],
        addon=FakeAddon(token={"access_token": "tok"}),
        login_window_cls=FakeLoginWindow,
        home_window_cls=FakeHomeWindow,
    )
    assert len(FakeHomeWindow.instances) == 1
    assert FakeHomeWindow.instances[0].shown is True
    assert len(FakeLoginWindow.instances) == 0
