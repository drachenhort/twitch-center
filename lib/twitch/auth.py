"""Twitch OAuth device-code flow. No xbmc* imports - pure Python, pytest-testable."""
import json

import requests

from lib.twitch import api

DEVICE_CODE_URL = "https://id.twitch.tv/oauth2/device"
TOKEN_URL = "https://id.twitch.tv/oauth2/token"
SCOPES = ["user:read:follows"]

_EXPIRED_MESSAGES = {"expired_token", "expired"}


def request_device_code(client_id, scopes):
    """Start the device-code flow. Returns dict with device_code, user_code,
    verification_uri, expires_in, interval (per Twitch's device-code response).
    Raises requests.RequestException on network/HTTP failure."""
    response = requests.post(
        DEVICE_CODE_URL,
        data={"client_id": client_id, "scopes": " ".join(scopes)},
        timeout=10,
    )
    response.raise_for_status()
    return response.json()


def poll_device_code_once(client_id, device_code):
    """Make one poll attempt against Twitch's token endpoint. Never raises - network
    errors are treated the same as an "authorization_pending" response, since a
    single transient failure shouldn't abort the whole login flow.

    Returns one of:
      {"status": "success", "token": {...}}
      {"status": "pending"}
      {"status": "slow_down"}
      {"status": "expired"}
    """
    try:
        response = requests.post(
            TOKEN_URL,
            data={
                "client_id": client_id,
                "device_code": device_code,
                "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
            },
            timeout=10,
        )
    except requests.RequestException:
        return {"status": "pending"}

    if response.status_code == 200:
        try:
            return {"status": "success", "token": response.json()}
        except ValueError:
            return {"status": "pending"}

    try:
        body = response.json()
    except ValueError:
        return {"status": "pending"}

    message = body.get("message", "")
    if message == "slow_down":
        return {"status": "slow_down"}
    if message in _EXPIRED_MESSAGES:
        return {"status": "expired"}
    return {"status": "pending"}


def save_token(token, addon):
    """Persist a token dict to the addon's hidden twitch_token setting."""
    addon.setSetting("twitch_token", json.dumps(token))


def load_token(addon):
    """Load a previously saved token dict from the addon's hidden twitch_token
    setting, or None if none saved / the stored value isn't valid JSON."""
    raw = addon.getSetting("twitch_token")
    if not raw:
        return None
    try:
        return json.loads(raw)
    except ValueError:
        return None


def refresh_access_token(client_id, refresh_token):
    """Exchange a refresh_token for a new token dict. Returns None on any failure
    (network error, non-200 response, unparseable body) rather than raising -
    "refresh didn't work" is an expected outcome the caller must handle either way."""
    try:
        response = requests.post(
            TOKEN_URL,
            data={
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
                "client_id": client_id,
            },
            timeout=10,
        )
    except requests.RequestException:
        return None
    if response.status_code != 200:
        return None
    try:
        return response.json()
    except ValueError:
        return None


def clear_token(addon):
    """Remove the saved token, e.g. after a refresh attempt fails and the user
    must log in again from scratch."""
    addon.setSetting("twitch_token", "")


def run_device_code_login(
    client_id,
    scopes,
    addon,
    on_code,
    on_status,
    cancel_event,
    sleep_fn=None,
    wait_fn=None,
    request_fn=request_device_code,
    poll_fn=poll_device_code_once,
    get_current_user_fn=None,
):
    """Orchestrates the full device-code login flow: request a code, report it via
    on_code, then poll until success/expiry/cancellation, reporting status via
    on_status after each attempt. Returns True on successful login (token saved),
    False otherwise. Safe to run on a background thread - all callbacks are the
    caller's responsibility to make thread-safe for their UI toolkit.

    wait_fn(seconds) is used to pause between poll attempts; it defaults to
    cancel_event.wait(seconds), which both sleeps AND returns early the moment
    cancellation is requested, so cancellation during the wait is near-instant.
    sleep_fn is kept as a legacy override for tests that don't want to deal
    with a real Event: when supplied (and wait_fn isn't), it's used instead.
    Any unexpected exception (malformed Twitch responses, etc.) is caught and
    reported via on_status("error") rather than propagating out of this
    function - it's expected to run on a background thread with no other
    error surface.

    get_current_user_fn(access_token, client_id) is called once, right after a
    successful token exchange and before the token is saved, to cache the
    logged-in user's id/login/display_name onto the token dict (defaults to
    api.get_current_user). If it raises, the whole login is treated as failed -
    on_status("error"), nothing saved - rather than saving a token with no
    cached user info."""
    if wait_fn is None:
        if sleep_fn is not None:
            wait_fn = lambda seconds: sleep_fn(seconds)
        else:
            wait_fn = lambda seconds: cancel_event.wait(seconds)
    if get_current_user_fn is None:
        get_current_user_fn = api.get_current_user

    try:
        try:
            device_info = request_fn(client_id, scopes)
        except requests.RequestException:
            on_status("error")
            return False

        on_code(device_info["user_code"], device_info["verification_uri"])
        on_status("pending")

        interval = device_info.get("interval", 5)
        expires_in = device_info.get("expires_in", 1800)
        elapsed = 0

        while elapsed < expires_in:
            if cancel_event.is_set():
                return False
            wait_fn(interval)
            elapsed += interval

            if cancel_event.is_set():
                return False

            result = poll_fn(client_id, device_info["device_code"])

            if cancel_event.is_set():
                return False

            status = result["status"]

            if status == "success":
                token = result["token"]
                try:
                    user_info = get_current_user_fn(token["access_token"], client_id)
                except Exception:
                    on_status("error")
                    return False
                token["user_id"] = user_info["id"]
                token["login"] = user_info["login"]
                token["display_name"] = user_info["display_name"]

                if cancel_event.is_set():
                    return False

                save_token(token, addon)
                on_status("success")
                return True
            if status == "slow_down":
                interval += 5
                on_status("pending")
                continue
            if status == "expired":
                on_status("expired")
                return False
            on_status("pending")

        on_status("expired")
        return False
    except Exception:
        on_status("error")
        return False
