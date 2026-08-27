"""Menu view: the landing screen after Login - Live Streams / Discover /
Settings / Log in again / Log in to Kick. Not a Window subclass - see
MainWindow."""
import xbmcaddon
import xbmcgui

from lib.kick import auth as kick_auth


class MenuView:
    LIVE_STREAMS_BUTTON_ID = 501
    DISCOVER_BUTTON_ID = 502
    VOD_CLIPS_BUTTON_ID = 503
    SETTINGS_BUTTON_ID = 504
    RELOGIN_BUTTON_ID = 505
    KICK_LOGIN_BUTTON_ID = 506
    # MainWindow focuses this when Menu becomes visible - the skin's own
    # <defaultcontrol> only fires once, on the very first window activation.
    DEFAULT_FOCUS_ID = LIVE_STREAMS_BUTTON_ID

    def __init__(self, window, closed_event=None):
        self.window = window
        self.closed_event = closed_event

    def activate(self):
        self._update_login_labels()

    def _update_login_labels(self):
        # Twitch is always logged in by the time Menu is reachable at all
        # (main.py only shows Menu when a Twitch token exists) - this button
        # stays clickable to switch accounts, it just always reads "logged in".
        self._set_label(self.RELOGIN_BUTTON_ID, "(Twitch) Logged in")
        kick_logged_in = bool(kick_auth.load_token(xbmcaddon.Addon()))
        self._set_label(
            self.KICK_LOGIN_BUTTON_ID, "(Kick) Logged in" if kick_logged_in else "Log in to Kick"
        )

    def _set_label(self, control_id, text):
        try:
            self.window.getControl(control_id).setLabel(text)
        except Exception:
            pass

    def handle_action(self, action):
        if action.getId() != xbmcgui.ACTION_SELECT_ITEM:
            return
        focus = self.window.getFocusId()
        if focus == self.LIVE_STREAMS_BUTTON_ID:
            self.window._switch_view("live_streams")
        elif focus == self.DISCOVER_BUTTON_ID:
            self.window._switch_view("discover")
        elif focus == self.VOD_CLIPS_BUTTON_ID:
            self.window._switch_view("vod_clips_channels")
        elif focus == self.SETTINGS_BUTTON_ID:
            xbmcaddon.Addon().openSettings()
        elif focus == self.RELOGIN_BUTTON_ID:
            self.window._switch_view("login")
        elif focus == self.KICK_LOGIN_BUTTON_ID:
            self._select_kick_login()

    def _select_kick_login(self):
        addon = xbmcaddon.Addon()
        if not addon.getSetting("kick_client_id") or not addon.getSetting("kick_client_secret"):
            xbmcgui.Dialog().ok(
                "Kick", "Set Kick Client ID and Client Secret in Settings first."
            )
            return
        self.window._switch_view("kick_login")

    def handle_click(self, control_id):
        pass
