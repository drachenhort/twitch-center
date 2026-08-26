"""Background service entry point, referenced by addon.xml's xbmc.service extension. Runs for
Kodi's whole lifetime; polls the live_notify_enabled setting and, when on, keeps a
LiveNotifyClient subscribed to stream.online for the user's followed Twitch channels."""
import os
import queue
import sys
import threading

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import xbmc
import xbmcaddon
import xbmcgui

from lib.settings import Settings
from lib.twitch import api, auth
from lib.twitch.eventsub import LiveNotifyClient

_SETTING_POLL_INTERVAL_SECONDS = 60
_FOLLOW_REFRESH_INTERVAL_SECONDS = 600


class _RunningClient:
    """Bundles a LiveNotifyClient with the dedicated thread that drains its blocking
    read_events() generator into a plain Queue the main service loop can poll non-blockingly."""

    def __init__(self, client):
        self.client = client
        self.events = queue.Queue()
        self._thread = threading.Thread(target=self._pump, daemon=True)
        self._thread.start()

    def _pump(self):
        for event in self.client.read_events():
            self.events.put(event)

    def drain(self):
        events = []
        while True:
            try:
                events.append(self.events.get_nowait())
            except queue.Empty:
                break
        return events

    def disconnect(self):
        self.client.disconnect()


def _followed_broadcaster_ids(token, client_id):
    channels = api.get_followed_channels(token["access_token"], client_id, token["user_id"])
    return [c["broadcaster_id"] for c in channels]


def run(addon=None, monitor_cls=None, client_cls=None, settings_cls=None):
    addon = addon or xbmcaddon.Addon()
    monitor_cls = monitor_cls or xbmc.Monitor
    client_cls = client_cls or LiveNotifyClient
    settings_cls = settings_cls or Settings

    monitor = monitor_cls()
    running = None  # _RunningClient or None
    ticks_since_follow_refresh = 0
    _TICKS_PER_FOLLOW_REFRESH = _FOLLOW_REFRESH_INTERVAL_SECONDS // _SETTING_POLL_INTERVAL_SECONDS

    while True:
        settings = settings_cls(addon)

        if not settings.live_notify_enabled and running is not None:
            running.disconnect()
            running = None

        elif settings.live_notify_enabled and running is None:
            try:
                token = auth.load_token(addon)
                if token is not None:
                    client_id = token.get("client_id") or addon.getSetting("client_id")
                    client = client_cls(token["access_token"], client_id)
                    client.connect()
                    client.set_broadcasters(_followed_broadcaster_ids(token, client_id))
                    running = _RunningClient(client)
                    ticks_since_follow_refresh = 0
            except Exception as exc:
                xbmc.log(
                    "script.twitch.center: live-notify service failed to connect: " + repr(exc),
                    xbmc.LOGWARNING,
                )
                running = None

        elif settings.live_notify_enabled and running is not None:
            for event in running.drain():
                if event.get("type") == "stream_online":
                    xbmcgui.Dialog().notification(
                        "Twitch Center", "%s is live" % event["broadcaster_user_name"]
                    )
            ticks_since_follow_refresh += 1
            if ticks_since_follow_refresh >= _TICKS_PER_FOLLOW_REFRESH:
                ticks_since_follow_refresh = 0
                try:
                    token = auth.load_token(addon)
                    if token is not None:
                        client_id = token.get("client_id") or addon.getSetting("client_id")
                        running.client.set_broadcasters(_followed_broadcaster_ids(token, client_id))
                except Exception as exc:
                    xbmc.log(
                        "script.twitch.center: live-notify follow-refresh failed: " + repr(exc),
                        xbmc.LOGWARNING,
                    )

        if monitor.waitForAbort(_SETTING_POLL_INTERVAL_SECONDS):
            if running is not None:
                running.disconnect()
            break


if __name__ == "__main__":
    run()
