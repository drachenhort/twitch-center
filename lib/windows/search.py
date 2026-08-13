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

    def __init__(self, *args, **kwargs):
        super(SearchWindow, self).__init__(*args, **kwargs)
        self.search_results = []
        self._update_queue = []

    def onInit(self):
        self.setFocusId(self.SEARCH_INPUT_ID)
        self.getControl(self.SEARCH_INPUT_ID).setFocus(True)
        self.getControl(self.STATUS_LABEL_ID).setLabel("")

    def onFocus(self, controlId):
        pass

    def onClick(self, controlId):
        if controlId == self.SEARCH_INPUT_ID:
            self.start_search()
        elif controlId == self.RESULTS_LIST_ID:
            self.play_selected()

    def onAction(self, action):
        if action.getId() in (xbmcgui.ACTION_PREVIOUS_MENU, xbmcgui.ACTION_NAV_BACK):
            self.close()
        if action.getId() == xbmcgui.ACTION_SELECT_ITEM:
            if self.getFocusId() == self.SEARCH_INPUT_ID:
                self.start_search()
            elif self.getFocusId() == self.RESULTS_LIST_ID:
                self.play_selected()
        if self._update_queue:
            self._process_updates()

    def start_search(self):
        query = self.getControl(self.SEARCH_INPUT_ID).getLabel()
        if not query:
            return
        self.getControl(self.STATUS_LABEL_ID).setLabel("Searching...")
        self.getControl(self.RESULTS_LIST_ID).reset()
        
        def search_task():
            results = gql.search(query, search_type="all")
            self._update_queue.append(("update_results", results))
            
        threading.Thread(target=search_task, daemon=True).start()

    def _process_updates(self):
        if not self._update_queue:
            return
        action, data = self._update_queue.pop(0)
        if action == "update_results":
            self._render_results(data)

    def _render_results(self, results):
        self.search_results = results
        self.getControl(self.STATUS_LABEL_ID).setLabel("")
        list_control = self.getControl(self.RESULTS_LIST_ID)
        list_control.reset()
        for item in results:
            name = item.get("display_name") or item.get("name") or item.get("user_name") or "Unknown"
            list_control.addItem(name)

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
