"""Search window for finding Twitch channels and streams."""
import threading
import xbmc
import xbmcaddon
import xbmcgui
from lib.twitch import gql, stream
from lib.windows import player


class SearchWindow(xbmcgui.WindowXMLDialog):
    SEARCH_INPUT_ID = 101
    RESULTS_LIST_ID = 102
    STATUS_LABEL_ID = 103
    NEXT_PAGE_BUTTON_ID = 104

    def __init__(self, *args, **kwargs):
        super(SearchWindow, self).__init__(*args, **kwargs)
        self.search_results = []
        self._update_queue = []
        self._next_cursor = None

    def _safe_control(self, control_id):
        try:
            return self.getControl(control_id)
        except Exception:
            return None

    def onInit(self):
        self.setFocusId(self.SEARCH_INPUT_ID)
        self.getControl(self.SEARCH_INPUT_ID).setFocus(True)
        self.getControl(self.STATUS_LABEL_ID).setLabel("")
        self._update_next_page_button()

    def onFocus(self, controlId):
        pass

    def onClick(self, controlId):
        if controlId == self.SEARCH_INPUT_ID:
            self.start_search()
        elif controlId == self.RESULTS_LIST_ID:
            self.play_selected()
        elif controlId == self.NEXT_PAGE_BUTTON_ID:
            self.load_next_page()

    def onAction(self, action):
        if action.getId() in (xbmcgui.ACTION_PREVIOUS_MENU, xbmcgui.ACTION_NAV_BACK):
            self.close()
        if action.getId() == xbmcgui.ACTION_SELECT_ITEM:
            if self.getFocusId() == self.SEARCH_INPUT_ID:
                self.start_search()
            elif self.getFocusId() == self.RESULTS_LIST_ID:
                self.play_selected()
            elif self.getFocusId() == self.NEXT_PAGE_BUTTON_ID:
                self.load_next_page()
        if self._update_queue:
            self._process_updates()

    def start_search(self):
        query = self.getControl(self.SEARCH_INPUT_ID).getLabel()
        if not query:
            return
        self.getControl(self.STATUS_LABEL_ID).setLabel("Searching...")
        self.getControl(self.RESULTS_LIST_ID).reset()
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
        self.getControl(self.STATUS_LABEL_ID).setLabel("Loading more...")
        self.getControl(self.NEXT_PAGE_BUTTON_ID).setEnabled(False)
        
        def search_task():
            results, cursor = gql.search(
                query=self.getControl(self.SEARCH_INPUT_ID).getLabel(),
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
        self.getControl(self.STATUS_LABEL_ID).setLabel("")
        list_control = self.getControl(self.RESULTS_LIST_ID)
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
        idx = self.getControl(self.RESULTS_LIST_ID).getSelectedPosition()
        if idx < 0 or idx >= len(self.search_results):
            return
        result = self.search_results[idx]
        login = result.get("login") or result.get("user_login") or result.get("name")
        if login:
            website_token = xbmcaddon.Addon().getSetting("website_token")
            url = stream.resolve_stream_url(login, website_token)
            player.play_stream(url, login)
            self.close()
