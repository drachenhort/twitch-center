import pytest
from lib.twitch import api


def test_get_followed_channels_not_implemented():
    with pytest.raises(NotImplementedError):
        api.get_followed_channels("token", "user-id")


def test_get_live_status_not_implemented():
    with pytest.raises(NotImplementedError):
        api.get_live_status("token", ["user-id"])


def test_get_games_for_channels_not_implemented():
    with pytest.raises(NotImplementedError):
        api.get_games_for_channels("token", ["user-id"])


def test_get_live_streams_by_game_not_implemented():
    with pytest.raises(NotImplementedError):
        api.get_live_streams_by_game("token", "game-id")


def test_search_channels_not_implemented():
    with pytest.raises(NotImplementedError):
        api.search_channels("token", "query")
