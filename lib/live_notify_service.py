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


def _followed_channels(token, client_id):
    return api.get_followed_channels(token["access_token"], client_id, token["user_id"])


def _followed_broadcaster_ids(token, client_id):
    return [c["broadcaster_id"] for c in _followed_channels(token, client_id)]


def _log_subscribed_channels(channels, verbose):
    if not verbose:
        return
    names = ", ".join(c.get("broadcaster_login", c["broadcaster_id"]) for c in channels)
    xbmc.log(
        "script.twitch.center: live-notify: subscribed to %d followed channel(s): %s"
        % (len(channels), names),
        xbmc.LOGINFO,
    )


def _refresh_token(addon, client_id, token):
    """Refreshes an expired token using its refresh_token, saves the result (preserving the
    cached user_id/login/display_name, mirroring lib/views/discover_view.py's
    _handle_expired_token), and returns the new token dict - or None if the refresh itself
    failed (network error, non-200, unparseable body), matching auth.refresh_access_token's
    documented contract. Never raises."""
    def _log_refresh_error(message):
        xbmc.log(
            "script.twitch.center: live-notify token refresh failed: " + message,
            xbmc.LOGWARNING,
        )

    new_token = auth.refresh_access_token(
        client_id, token["refresh_token"], on_error=_log_refresh_error
    )
    if new_token is None:
        return None
    new_token["user_id"] = token.get("user_id")
    new_token["login"] = token.get("login")
    new_token["display_name"] = token.get("display_name")
    auth.save_token(new_token, addon)
    return new_token


def run(addon=None, monitor_cls=None, client_cls=None, settings_cls=None):
    addon = addon or xbmcaddon.Addon()
    monitor_cls = monitor_cls or xbmc.Monitor
    client_cls = client_cls or LiveNotifyClient
    settings_cls = settings_cls or Settings

    monitor = monitor_cls()
    running = None  # _RunningClient or None
    ticks_since_follow_refresh = 0
    ticks_per_follow_refresh = _FOLLOW_REFRESH_INTERVAL_SECONDS // _SETTING_POLL_INTERVAL_SECONDS

    while True:
        settings = settings_cls(addon)

        if not settings.live_notify_enabled and running is not None:
            running.disconnect()
            running = None

        elif settings.live_notify_enabled and running is None:
            client = None
            try:
                token = auth.load_token(addon)
                if token is not None and token.get("user_id"):
                    client_id = addon.getSetting("client_id")
                    try:
                        client = client_cls(token["access_token"], client_id)
                        client.connect()
                        channels = _followed_channels(token, client_id)
                        client.set_broadcasters([c["broadcaster_id"] for c in channels])
                        _log_subscribed_channels(channels, settings.live_notify_verbose_logging)
                    except api.TokenExpiredError:
                        _refresh_token(addon, client_id, token)
                        # Leave running as None either way: on success, the next tick's
                        # load_token() picks up the freshly-saved token; on failure, this is
                        # just another transient failure to retry later.
                        raise
                    running = _RunningClient(client)
                    ticks_since_follow_refresh = 0
            except Exception as exc:
                if client is not None:
                    try:
                        client.disconnect()
                    except Exception:
                        pass
                xbmc.log(
                    "script.twitch.center: live-notify service failed to connect: " + repr(exc),
                    xbmc.LOGWARNING,
                )
                running = None

        elif settings.live_notify_enabled and running is not None:
            for event in running.drain():
                if event.get("type") == "stream_online":
                    if settings.live_notify_verbose_logging:
                        xbmc.log(
                            "script.twitch.center: live-notify: %s went live, showing notification"
                            % event["broadcaster_user_name"],
                            xbmc.LOGINFO,
                        )
                    xbmcgui.Dialog().notification(
                        "Twitch Center", "%s is live" % event["broadcaster_user_name"]
                    )
                elif event.get("type") in ("status", "subscription_error"):
                    if settings.live_notify_verbose_logging:
                        xbmc.log(
                            "script.twitch.center: live-notify event: " + repr(event),
                            xbmc.LOGINFO,
                        )
            ticks_since_follow_refresh += 1
            if ticks_since_follow_refresh >= ticks_per_follow_refresh:
                ticks_since_follow_refresh = 0
                try:
                    token = auth.load_token(addon)
                    if token is not None and token.get("user_id"):
                        client_id = addon.getSetting("client_id")
                        try:
                            channels = _followed_channels(token, client_id)
                            running.client.set_broadcasters([c["broadcaster_id"] for c in channels])
                            _log_subscribed_channels(channels, settings.live_notify_verbose_logging)
                        except api.TokenExpiredError:
                            refreshed = _refresh_token(addon, client_id, token)
                            if refreshed is not None:
                                # LiveNotifyClient has no access-token setter; tear down and let
                                # the next tick reconnect with the freshly-saved token.
                                running.disconnect()
                                running = None
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
