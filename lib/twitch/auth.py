"""Twitch OAuth device-code flow. No xbmc* imports - pure Python, pytest-testable."""


def request_device_code(client_id):
    """Start the device-code flow. Returns dict with device_code, user_code,
    verification_uri, expires_in, interval (per Twitch's device-code response)."""
    raise NotImplementedError


def poll_for_token(client_id, device_code, interval):
    """Poll Twitch's token endpoint until the user authorizes the device code.
    Returns dict with access_token, refresh_token, expires_in, scope, token_type."""
    raise NotImplementedError


def save_token(token):
    """Persist a token dict to local storage."""
    raise NotImplementedError


def load_token():
    """Load a previously saved token dict, or None if none saved."""
    return None
