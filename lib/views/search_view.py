"""Search view: finding Twitch channels/streams. Kick has no working search
endpoint (see docs/kick-live-testing-findings-2026-08-22.md, Finding 4) - Kick
channels are discoverable only via Live Streams favorites and Discover's
categories row. Not a Window subclass - see MainWindow."""
import threading
import xbmc
import xbmcaddon
import xbmcgui
from lib import providers
from lib.twitch import gql
from lib.windows import player

_PLAYBACK_ERROR_MESSAGE = "Couldn't start playback. Try again."


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
        # Shared across every view hosted by MainWindow, which bootstraps it.
        self.closed_event = closed_event

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
            twitch_results, cursor = gql.search(query, search_type="all")
            self._update_queue.append(("update_results", twitch_results, cursor))

        threading.Thread(target=search_task, daemon=True).start()

    def load_next_page(self):
        if not self._next_cursor:
            return
        self.window.getControl(self.STATUS_LABEL_ID).setLabel("Loading more...")
        self.window.getControl(self.NEXT_PAGE_BUTTON_ID).setEnabled(False)

        def search_task():
            twitch_results, cursor = gql.search(
                query=self.window.getControl(self.SEARCH_INPUT_ID).getLabel(),
                search_type="all",
                cursor=self._next_cursor
            )
            self._update_queue.append(("update_results", twitch_results, cursor))

        threading.Thread(target=search_task, daemon=True).start()

    def _process_updates(self):
        if not self._update_queue:
            return
        action, twitch_results, cursor = self._update_queue.pop(0)
        if action == "update_results":
            self._render_results(twitch_results, cursor)

    def _render_results(self, twitch_results, cursor):
        twitch_normalized = [providers.normalize_twitch_search_result(r) for r in twitch_results]
        merged = providers.merge_by_viewer_count(twitch_normalized)
        self.search_results.extend(merged)
        self._next_cursor = cursor
        self.window.getControl(self.STATUS_LABEL_ID).setLabel("")
        list_control = self.window.getControl(self.RESULTS_LIST_ID)
        for normalized in merged:
            item = xbmcgui.ListItem(normalized["display_name"])
            item.setArt({"thumb": normalized["thumbnail_url"]})
            item.setProperty("platform", normalized["platform"])
            item.setProperty("is_live", "true" if normalized["is_live"] else "false")
            item.setProperty("game_name", normalized["game_name"])
            item.setProperty("viewer_count", str(normalized["viewer_count"]))
            list_control.addItem(item)
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
        login = result.get("login")
        if not login:
            return
        addon = xbmcaddon.Addon()
        try:
            url = providers.resolve_stream_url(addon, result["platform"], login)
            player.play_stream(url, login, platform=result["platform"])
        except providers.StreamUnavailableError:
            self._show_error(_PLAYBACK_ERROR_MESSAGE)
            return
        except Exception as exc:
            xbmc.log(
                "script.twitch.center: Search channel selection failed: " + repr(exc),
                xbmc.LOGERROR,
            )
            self._show_error(_PLAYBACK_ERROR_MESSAGE)
            return

    def _show_error(self, message):
        """Transient failure (e.g. one playback attempt): mirrors this
        file's existing pattern of writing status text directly to
        STATUS_LABEL_ID (see start_search/load_next_page), rather than a
        separate error label."""
        status_label = self._safe_control(self.STATUS_LABEL_ID)
        if status_label:
            status_label.setLabel(message)
