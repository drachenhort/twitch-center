"""Twitch OAuth device-code flow. No xbmc* imports - pure Python, pytest-testable."""
import json
import time

import requests

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


def run_device_code_login(
    client_id,
    scopes,
    addon,
    on_code,
    on_status,
    cancel_event,
    sleep_fn=time.sleep,
    request_fn=request_device_code,
    poll_fn=poll_device_code_once,
):
    """Orchestrates the full device-code login flow: request a code, report it via
    on_code, then poll until success/expiry/cancellation, reporting status via
    on_status after each attempt. Returns True on successful login (token saved),
    False otherwise. Safe to run on a background thread - all callbacks are the
    caller's responsibility to make thread-safe for their UI toolkit."""
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
        sleep_fn(interval)
        elapsed += interval

        result = poll_fn(client_id, device_info["device_code"])
        status = result["status"]

        if status == "success":
            save_token(result["token"], addon)
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
