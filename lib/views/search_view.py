"""Search view: finding Twitch channels and streams. Not a Window subclass -
see MainWindow."""
import threading
import xbmcaddon
import xbmcgui
from lib.twitch import gql, stream
from lib.windows import player


class SearchView:
    SEARCH_INPUT_ID = 401
    RESULTS_LIST_ID = 402
    STATUS_LABEL_ID = 403
    NEXT_PAGE_BUTTON_ID = 404

    def __init__(self, window, closed_event=None):
        self.window = window
        self.search_results = []
        self._update_queue = []
        self._next_cursor = None
        # Shared across the whole window-navigation chain - see LoginWindow.
        self.closed_event = closed_event or threading.Event()
        if not hasattr(self.closed_event, "quit_requested"):
            self.closed_event.quit_requested = False

    def _safe_control(self, control_id):
        try:
            return self.window.getControl(control_id)
        except Exception:
            return None

    def activate(self):
        self.window.setFocusId(self.SEARCH_INPUT_ID)
        self.window.getControl(self.STATUS_LABEL_ID).setLabel("")
        self._update_next_page_button()

    def handle_click(self, control_id):
        if control_id == self.SEARCH_INPUT_ID:
            self.start_search()
        elif control_id == self.RESULTS_LIST_ID:
            self.play_selected()
        elif control_id == self.NEXT_PAGE_BUTTON_ID:
            self.load_next_page()

    def handle_action(self, action):
        if action.getId() == xbmcgui.ACTION_SELECT_ITEM:
            if self.window.getFocusId() == self.SEARCH_INPUT_ID:
                self.start_search()
            elif self.window.getFocusId() == self.RESULTS_LIST_ID:
                self.play_selected()
            elif self.window.getFocusId() == self.NEXT_PAGE_BUTTON_ID:
                self.load_next_page()
        if self._update_queue:
            self._process_updates()

    def start_search(self):
        query = self.window.getControl(self.SEARCH_INPUT_ID).getLabel()
        if not query:
            return
        self.window.getControl(self.STATUS_LABEL_ID).setLabel("Searching...")
        self.window.getControl(self.RESULTS_LIST_ID).reset()
        self.search_results = []
        self._next_cursor = None
        self._update_next_page_button()

        def search_task():
            results, cursor = gql.search(query, search_type="all")
            self._update_queue.append(("update_results", results, cursor))

        threading.Thread(target=search_task, daemon=True).start()

    def load_next_page(self):
        if not self._next_cursor:
            return
        self.window.getControl(self.STATUS_LABEL_ID).setLabel("Loading more...")
        self.window.getControl(self.NEXT_PAGE_BUTTON_ID).setEnabled(False)

        def search_task():
            results, cursor = gql.search(
                query=self.window.getControl(self.SEARCH_INPUT_ID).getLabel(),
                search_type="all",
                cursor=self._next_cursor
            )
            self._update_queue.append(("update_results", results, cursor))

        threading.Thread(target=search_task, daemon=True).start()

    def _process_updates(self):
        if not self._update_queue:
            return
        action, data, cursor = self._update_queue.pop(0)
        if action == "update_results":
            self._render_results(data, cursor)

    def _render_results(self, results, cursor):
        self.search_results.extend(results)
        self._next_cursor = cursor
        self.window.getControl(self.STATUS_LABEL_ID).setLabel("")
        list_control = self.window.getControl(self.RESULTS_LIST_ID)
        for item in results:
            name = item.get("display_name") or item.get("name") or item.get("user_name") or "Unknown"
            list_control.addItem(name)
        self._update_next_page_button()

    def _update_next_page_button(self):
        btn = self._safe_control(self.NEXT_PAGE_BUTTON_ID)
        if btn:
            btn.setVisible(bool(self._next_cursor))
            btn.setEnabled(bool(self._next_cursor))

    def play_selected(self):
        idx = self.window.getControl(self.RESULTS_LIST_ID).getSelectedPosition()
        if idx < 0 or idx >= len(self.search_results):
            return
        result = self.search_results[idx]
        login = result.get("login") or result.get("user_login") or result.get("name")
        if login:
            website_token = xbmcaddon.Addon().getSetting("website_token")
            url = stream.resolve_stream_url(login, website_token)
            player.play_stream(url, login)
