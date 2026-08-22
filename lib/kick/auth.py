"""Kick OAuth 2.1 Authorization Code + PKCE flow. No xbmc* imports - pure
Python, pytest-testable."""
import base64
import hashlib
import json
import queue
import secrets
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlencode, urlparse

import requests

AUTHORIZE_URL = "https://id.kick.com/oauth/authorize"
TOKEN_URL = "https://id.kick.com/oauth/token"
SCOPES = ["user:read", "channel:read", "chat:write"]


def generate_pkce_pair():
    """Return (code_verifier, code_challenge) per RFC 7636 (S256)."""
    verifier = base64.urlsafe_b64encode(secrets.token_bytes(64)).rstrip(b"=").decode("ascii")
    challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest())
        .rstrip(b"=")
        .decode("ascii")
    )
    return verifier, challenge


def build_authorize_url(client_id, redirect_uri, code_challenge, scopes, state):
    """Build the URL the user opens in a browser to approve the app."""
    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": " ".join(scopes),
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
        "state": state,
    }
    return AUTHORIZE_URL + "?" + urlencode(params)


_CALLBACK_HTML = b"<html><body>You can close this tab and return to Kodi.</body></html>"


class _CallbackHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        params = parse_qs(urlparse(self.path).query)
        if "code" in params:
            self.server.result_queue.put(
                {"status": "success", "code": params["code"][0], "state": params.get("state", [None])[0]}
            )
        elif "error" in params:
            self.server.result_queue.put({"status": "error", "error": params["error"][0]})
        else:
            self.server.result_queue.put({"status": "error", "error": "missing_code"})
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.end_headers()
        self.wfile.write(_CALLBACK_HTML)

    def log_message(self, format, *args):
        pass  # silence BaseHTTPRequestHandler's default stderr logging


def await_callback(port, timeout_seconds):
    """Run a one-shot loopback HTTP server on 127.0.0.1:port, blocking until it
    receives a request carrying `code`/`state` or `error`, or timeout_seconds
    elapses. Returns {"status": "success", "code", "state"} |
    {"status": "error", "error"} | {"status": "timeout"}."""
    server = HTTPServer(("127.0.0.1", port), _CallbackHandler)
    server.result_queue = queue.Queue(maxsize=1)
    server.timeout = timeout_seconds
    try:
        server.handle_request()
        return server.result_queue.get_nowait()
    except queue.Empty:
        return {"status": "timeout"}
    finally:
        server.server_close()


def exchange_code_for_token(client_id, redirect_uri, code, code_verifier):
    """Exchange an authorization code for a token dict. Raises
    requests.RequestException on network/HTTP failure."""
    response = requests.post(
        TOKEN_URL,
        data={
            "grant_type": "authorization_code",
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "code": code,
            "code_verifier": code_verifier,
        },
        timeout=10,
    )
    response.raise_for_status()
    return response.json()


def refresh_access_token(client_id, refresh_token, on_error=None):
    """Exchange a refresh_token for a new token dict. Returns None on any
    failure (network error, non-200, unparseable body) rather than raising -
    mirrors lib.twitch.auth.refresh_access_token's contract."""
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
    except requests.RequestException as exc:
        if on_error:
            on_error("network error: " + repr(exc))
        return None
    if response.status_code != 200:
        if on_error:
            on_error("HTTP " + str(response.status_code) + ": " + response.text[:200])
        return None
    try:
        return response.json()
    except ValueError as exc:
        if on_error:
            on_error("unparseable response body: " + repr(exc))
        return None


def save_token(token, addon):
    """Persist a token dict to the addon's hidden kick_token setting."""
    addon.setSetting("kick_token", json.dumps(token))


def load_token(addon):
    """Load a previously saved token dict, or None if none saved / invalid JSON."""
    raw = addon.getSetting("kick_token")
    if not raw:
        return None
    try:
        return json.loads(raw)
    except ValueError:
        return None


def clear_token(addon):
    """Remove the saved token, e.g. after a failed refresh forces re-login."""
    addon.setSetting("kick_token", "")


def run_pkce_login(
    client_id,
    redirect_port,
    addon,
    on_code,
    on_status,
    cancel_event,
    scopes=None,
    callback_timeout_seconds=300,
    await_callback_fn=await_callback,
    exchange_fn=exchange_code_for_token,
    get_current_user_fn=None,
):
    """Orchestrates the full PKCE login flow: build the authorize URL, report
    it via on_code, wait for the loopback callback, exchange the code for a
    token, cache the current user onto it, and save. Returns True on success,
    False otherwise. Mirrors lib.twitch.auth.run_device_code_login's
    callback/cancellation contract so login_view.py can drive both flows
    uniformly.

    Unlike the device-code flow there's no polling loop - await_callback_fn
    blocks (with its own timeout) waiting for the loopback server to receive
    the redirect, so cancellation is checked before starting and after the
    callback returns, rather than on every poll tick."""
    if scopes is None:
        scopes = SCOPES
    if get_current_user_fn is None:
        from lib.kick import api

        get_current_user_fn = api.get_current_user

    if cancel_event.is_set():
        return False

    try:
        redirect_uri = f"http://127.0.0.1:{redirect_port}/callback"
        verifier, challenge = generate_pkce_pair()
        state = secrets.token_urlsafe(16)
        url = build_authorize_url(client_id, redirect_uri, challenge, scopes, state)

        on_code(url)
        on_status("pending")

        result = await_callback_fn(redirect_port, callback_timeout_seconds)

        if cancel_event.is_set():
            return False

        status = result["status"]
        if status == "timeout":
            on_status("expired")
            return False
        if status == "error":
            on_status("denied")
            return False

        if result.get("state") != state:
            on_status("error")
            return False

        try:
            token = exchange_fn(client_id, redirect_uri, result["code"], verifier)
        except requests.RequestException:
            on_status("error")
            return False

        if cancel_event.is_set():
            return False

        try:
            user_info = get_current_user_fn(token["access_token"])
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
    except Exception:
        on_status("error")
        return False
