"""Persistent shell window: hosts every screen as a toggle-able skin group
instead of ever constructing a second top-level Kodi window, which is what
triggers a native window-manager bug (see
docs/superpowers/specs/2026-08-13-persistent-window-architecture-design.md)."""
import threading

import xbmc
import xbmcgui


class MainWindow(xbmcgui.WindowXML):
    GROUP_IDS = {
        "login": 100,
        "menu": 500,
        "live_streams": 200,
        "discover": 300,
        "search": 400,
    }

    def __init__(self, *args, initial_view="login", closed_event=None, view_classes=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.closed_event = closed_event or threading.Event()
        if not hasattr(self.closed_event, "quit_requested"):
            self.closed_event.quit_requested = False
        self._initial_view = initial_view
        view_classes = view_classes or self._default_view_classes()
        self._views = {
            name: cls(self, closed_event=self.closed_event) for name, cls in view_classes.items()
        }
        self._active_name = None

    @staticmethod
    def _default_view_classes():
        from lib.views.discover_view import DiscoverView
        from lib.views.live_streams_view import LiveStreamsView
        from lib.views.login_view import LoginView
        from lib.views.menu_view import MenuView
        from lib.views.search_view import SearchView

        return {
            "login": LoginView,
            "menu": MenuView,
            "live_streams": LiveStreamsView,
            "discover": DiscoverView,
            "search": SearchView,
        }

    def onInit(self):
        # Kodi can re-fire onInit on an already-active window; resuming the
        # current view keeps a user who's deep in Discover/Search from being
        # snapped back to the initial view.
        self._switch_view(self._active_name or self._initial_view)

    def _switch_view(self, name):
        old_view = self._views.get(self._active_name)
        # Re-switching to the already-active view (Kodi re-firing onInit)
        # must not tear the view down - stopping it would cancel work that
        # is still legitimately in flight, e.g. Login's polling thread.
        if old_view is not None and old_view is not self._views.get(name):
            if hasattr(old_view, "stop"):
                old_view.stop()
        for view_name, group_id in self.GROUP_IDS.items():
            control = self._safe_control(group_id)
            if control:
                control.setVisible(view_name == name)
        self._active_name = name
        view = self._views[name]
        # The skin's <defaultcontrol always="true"> only applies once,
        # natively, before onInit ever runs - every later view switch would
        # otherwise leave focus on a now-hidden control. Claim the view's
        # declared default BEFORE activate(), so any more specific focus the
        # view claims itself (e.g. a freshly populated list) still wins.
        default_focus = getattr(view, "DEFAULT_FOCUS_ID", None)
        if default_focus is not None:
            self.setFocusId(default_focus)
        view.activate()

    def _safe_control(self, control_id):
        try:
            return self.getControl(control_id)
        except Exception:
            return None

    def onAction(self, action):
        if action.getId() in (xbmcgui.ACTION_PREVIOUS_MENU, xbmcgui.ACTION_NAV_BACK):
            if xbmc.Player().isPlaying():
                xbmc.Player().stop()
                return
            if self._active_name == "menu":
                self.closed_event.quit_requested = True
            else:
                self._switch_view("menu")
            return
        if self._active_name is None:
            # Kodi can deliver input before onInit has run - there's no view
            # to delegate to yet.
            return
        self._views[self._active_name].handle_action(action)

    def onClick(self, control_id):
        if self._active_name is None:
            return
        self._views[self._active_name].handle_click(control_id)
