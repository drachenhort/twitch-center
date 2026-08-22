"""Kick OAuth 2.1 Authorization Code + PKCE flow. No xbmc* imports - pure
Python, pytest-testable."""
import base64
import hashlib
import secrets
from urllib.parse import urlencode

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
