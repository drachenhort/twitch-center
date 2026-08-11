"""Twitch Helix API calls. No xbmc* imports - pure Python, pytest-testable."""


def get_followed_channels(access_token, user_id):
    """Return the user's followed channels as a list of dicts (Helix
    /channels/followed), each with at least broadcaster_id, broadcaster_login,
    broadcaster_name."""
    raise NotImplementedError


def get_live_status(access_token, user_ids):
    """Return live-stream info (Helix /streams) for the given broadcaster user_ids -
    only entries for currently-live channels are returned."""
    raise NotImplementedError


def get_games_for_channels(access_token, user_ids):
    """Return a dict mapping user_id -> game_id for the given broadcaster user_ids,
    derived from their current/most recent live stream."""
    raise NotImplementedError


def get_live_streams_by_game(access_token, game_id):
    """Return currently-live streams (Helix /streams?game_id=) for the given game_id."""
    raise NotImplementedError


def search_channels(access_token, query):
    """Free-text channel search (Helix /search/channels) for the given query string."""
    raise NotImplementedError
