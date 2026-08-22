"""Kick OAuth 2.1 Authorization Code + PKCE flow. No xbmc* imports - pure
Python, pytest-testable."""
import base64
import hashlib
import queue
import secrets
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlencode, urlparse

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
