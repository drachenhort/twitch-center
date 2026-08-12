from unittest.mock import MagicMock, patch

import pytest
import requests

from lib.twitch import api


def _response(json_body, status_code=200):
    response = MagicMock()
    response.status_code = status_code
    response.json.return_value = json_body
    if status_code >= 400 and status_code != 401:
        response.raise_for_status.side_effect = requests.HTTPError(response=response)
    else:
        response.raise_for_status.side_effect = None
    return response


def test_get_current_user_returns_first_data_element():
    body = {"data": [{"id": "123", "login": "someuser", "display_name": "SomeUser"}]}
    with patch.object(api.requests, "get", return_value=_response(body)) as mock_get:
        result = api.get_current_user("token", "client-id")
    assert result == {"id": "123", "login": "someuser", "display_name": "SomeUser"}
    assert mock_get.call_args.kwargs["headers"]["Authorization"] == "Bearer token"
    assert mock_get.call_args.kwargs["headers"]["Client-Id"] == "client-id"


def test_get_current_user_raises_token_expired_on_401():
    with patch.object(api.requests, "get", return_value=_response({}, status_code=401)):
        with pytest.raises(api.TokenExpiredError):
            api.get_current_user("token", "client-id")


def test_get_current_user_propagates_other_http_errors():
    with patch.object(api.requests, "get", return_value=_response({}, status_code=500)):
        with pytest.raises(requests.RequestException):
            api.get_current_user("token", "client-id")


def test_get_followed_channels_returns_data():
    body = {
        "data": [
            {"broadcaster_id": "1", "broadcaster_login": "a", "broadcaster_name": "A"},
            {"broadcaster_id": "2", "broadcaster_login": "b", "broadcaster_name": "B"},
        ],
        "pagination": {},
    }
    with patch.object(api.requests, "get", return_value=_response(body)) as mock_get:
        result = api.get_followed_channels("token", "client-id", "user-id")
    assert result == body["data"]
    assert mock_get.call_args.kwargs["params"]["user_id"] == "user-id"


def test_get_followed_channels_follows_pagination():
    page1 = {
        "data": [{"broadcaster_id": "1", "broadcaster_login": "a", "broadcaster_name": "A"}],
        "pagination": {"cursor": "abc"},
    }
    page2 = {
        "data": [{"broadcaster_id": "2", "broadcaster_login": "b", "broadcaster_name": "B"}],
        "pagination": {},
    }
    with patch.object(api.requests, "get", side_effect=[_response(page1), _response(page2)]) as mock_get:
        result = api.get_followed_channels("token", "client-id", "user-id")
    assert result == page1["data"] + page2["data"]
    assert mock_get.call_count == 2
    assert mock_get.call_args_list[1].kwargs["params"]["after"] == "abc"


def test_get_followed_channels_raises_token_expired_on_401():
    with patch.object(api.requests, "get", return_value=_response({}, status_code=401)):
        with pytest.raises(api.TokenExpiredError):
            api.get_followed_channels("token", "client-id", "user-id")


def test_get_live_status_returns_data_for_small_list():
    body = {"data": [{"user_id": "1", "user_login": "a", "viewer_count": 10}]}
    with patch.object(api.requests, "get", return_value=_response(body)) as mock_get:
        result = api.get_live_status("token", "client-id", ["1", "2"])
    assert result == body["data"]
    assert mock_get.call_count == 1


def test_get_live_status_batches_over_100_ids():
    ids = [str(i) for i in range(150)]
    body1 = {"data": [{"user_id": "1"}]}
    body2 = {"data": [{"user_id": "101"}]}
    with patch.object(api.requests, "get", side_effect=[_response(body1), _response(body2)]) as mock_get:
        result = api.get_live_status("token", "client-id", ids)
    assert result == body1["data"] + body2["data"]
    assert mock_get.call_count == 2
    first_params = mock_get.call_args_list[0].kwargs["params"]
    second_params = mock_get.call_args_list[1].kwargs["params"]
    first_user_ids = [uid for key, uid in first_params if key == "user_id"]
    second_user_ids = [uid for key, uid in second_params if key == "user_id"]
    assert len(first_user_ids) == 100
    assert len(second_user_ids) == 50
    assert ("first", 100) in first_params
    assert ("first", 100) in second_params


def test_get_live_status_raises_token_expired_on_401():
    with patch.object(api.requests, "get", return_value=_response({}, status_code=401)):
        with pytest.raises(api.TokenExpiredError):
            api.get_live_status("token", "client-id", ["1"])


def test_get_live_status_empty_ids_makes_no_request():
    with patch.object(api.requests, "get") as mock_get:
        result = api.get_live_status("token", "client-id", [])
    assert result == []
    mock_get.assert_not_called()


def test_get_top_games_returns_id_and_name():
    body = {
        "data": [
            {"id": "509658", "name": "Just Chatting", "box_art_url": "https://example.invalid/1.jpg"},
            {"id": "21779", "name": "League of Legends", "box_art_url": "https://example.invalid/2.jpg"},
        ]
    }
    with patch.object(api.requests, "get", return_value=_response(body)) as mock_get:
        result = api.get_top_games("token", "client-id")
    assert result == [
        {"id": "509658", "name": "Just Chatting"},
        {"id": "21779", "name": "League of Legends"},
    ]
    assert mock_get.call_args.kwargs["params"]["first"] == 20


def test_get_top_games_raises_token_expired_on_401():
    with patch.object(api.requests, "get", return_value=_response({}, status_code=401)):
        with pytest.raises(api.TokenExpiredError):
            api.get_top_games("token", "client-id")


def test_get_live_streams_by_game_returns_data():
    body = {"data": [{"user_id": "1", "user_name": "A", "game_name": "Foo", "viewer_count": 10}]}
    with patch.object(api.requests, "get", return_value=_response(body)) as mock_get:
        result = api.get_live_streams_by_game("token", "client-id", "509658")
    assert result == body["data"]
    assert mock_get.call_args.kwargs["params"]["game_id"] == "509658"
    assert mock_get.call_args.kwargs["params"]["first"] == 20


def test_get_live_streams_by_game_raises_token_expired_on_401():
    with patch.object(api.requests, "get", return_value=_response({}, status_code=401)):
        with pytest.raises(api.TokenExpiredError):
            api.get_live_streams_by_game("token", "client-id", "509658")


def test_search_categories_returns_id_and_name():
    body = {
        "data": [
            {"id": "16497", "name": "World of Warships", "box_art_url": "https://x.invalid/a.jpg"},
            {"id": "9999", "name": "Warships 2", "box_art_url": "https://x.invalid/b.jpg"},
        ]
    }
    with patch.object(api.requests, "get", return_value=_response(body)) as mock_get:
        result = api.search_categories("token", "client-id", "warships")
    assert result == [
        {"id": "16497", "name": "World of Warships"},
        {"id": "9999", "name": "Warships 2"},
    ]
    params = mock_get.call_args.kwargs["params"]
    assert params["query"] == "warships"
    assert params["first"] == 20


def test_search_categories_raises_token_expired_on_401():
    with patch.object(api.requests, "get", return_value=_response({}, status_code=401)):
        with pytest.raises(api.TokenExpiredError):
            api.search_categories("token", "client-id", "warships")


def test_search_channels_returns_data_with_live_only_default():
    body = {
        "data": [
            {
                "broadcaster_login": "someone",
                "display_name": "Someone",
                "id": "999",
                "is_live": True,
                "game_name": "Foo",
                "thumbnail_url": "https://example.invalid/thumb.jpg",
            }
        ]
    }
    with patch.object(api.requests, "get", return_value=_response(body)) as mock_get:
        result = api.search_channels("token", "client-id", "someone")
    assert result == body["data"]
    params = mock_get.call_args.kwargs["params"]
    assert params["query"] == "someone"
    # Helix wants lowercase true/false; requests would render a bare Python
    # bool as "True"/"False", which Twitch rejects.
    assert params["live_only"] == "true"
    assert params["first"] == 20


def test_search_channels_can_disable_live_only():
    body = {"data": []}
    with patch.object(api.requests, "get", return_value=_response(body)) as mock_get:
        api.search_channels("token", "client-id", "someone", live_only=False)
    assert mock_get.call_args.kwargs["params"]["live_only"] == "false"


def test_search_channels_raises_token_expired_on_401():
    with patch.object(api.requests, "get", return_value=_response({}, status_code=401)):
        with pytest.raises(api.TokenExpiredError):
            api.search_channels("token", "client-id", "someone")
