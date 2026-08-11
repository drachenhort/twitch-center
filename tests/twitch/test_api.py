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
    assert len(first_params) == 100
    assert len(second_params) == 50


def test_get_live_status_raises_token_expired_on_401():
    with patch.object(api.requests, "get", return_value=_response({}, status_code=401)):
        with pytest.raises(api.TokenExpiredError):
            api.get_live_status("token", "client-id", ["1"])


def test_get_live_status_empty_ids_makes_no_request():
    with patch.object(api.requests, "get") as mock_get:
        result = api.get_live_status("token", "client-id", [])
    assert result == []
    mock_get.assert_not_called()
