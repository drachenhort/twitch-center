from unittest.mock import MagicMock, patch

import pytest
import requests

from lib.kick import api


def _response(json_body, status_code=200):
    response = MagicMock()
    response.status_code = status_code
    response.json.return_value = json_body
    if status_code >= 400 and status_code != 401:
        response.raise_for_status.side_effect = requests.HTTPError(response=response)
    else:
        response.raise_for_status.side_effect = None
    return response


def test_get_current_user_normalizes_field_names():
    body = {"data": [{"user_id": 42, "name": "SomeUser"}]}
    with patch.object(api.requests, "get", return_value=_response(body)) as mock_get:
        result = api.get_current_user("token")
    assert result == {"id": "42", "login": "someuser", "display_name": "SomeUser"}
    assert mock_get.call_args.kwargs["headers"]["Authorization"] == "Bearer token"


def test_get_current_user_raises_token_expired_on_401():
    with patch.object(api.requests, "get", return_value=_response({}, status_code=401)):
        with pytest.raises(api.TokenExpiredError):
            api.get_current_user("token")


def test_get_channel_returns_first_match():
    body = {"data": [{"broadcaster_user_id": 42, "slug": "somechannel", "stream": {"is_live": True, "url": "https://x/stream.m3u8"}}]}
    with patch.object(api.requests, "get", return_value=_response(body)) as mock_get:
        result = api.get_channel("token", "somechannel")
    assert result == body["data"][0]
    assert mock_get.call_args.kwargs["params"] == {"slug": "somechannel"}


def test_get_channel_returns_none_when_not_found():
    with patch.object(api.requests, "get", return_value=_response({"data": []})):
        result = api.get_channel("token", "nosuchchannel")
    assert result is None


def test_get_live_streams_returns_data():
    body = {"data": [{"broadcaster_user_id": 1}, {"broadcaster_user_id": 2}]}
    with patch.object(api.requests, "get", return_value=_response(body)) as mock_get:
        result = api.get_live_streams("token", category_id=5, first=10)
    assert result == body["data"]
    assert mock_get.call_args.kwargs["params"] == {"category_id": 5, "limit": 10}


def test_get_live_streams_omits_category_id_when_none():
    body = {"data": []}
    with patch.object(api.requests, "get", return_value=_response(body)) as mock_get:
        api.get_live_streams("token")
    assert mock_get.call_args.kwargs["params"] == {"limit": 20}


def test_get_top_categories_returns_id_and_name():
    body = {"data": [{"id": 7, "name": "Just Chatting"}, {"id": 8, "name": "Games"}]}
    with patch.object(api.requests, "get", return_value=_response(body)):
        result = api.get_top_categories("token", first=2)
    assert result == [{"id": 7, "name": "Just Chatting"}, {"id": 8, "name": "Games"}]


def test_get_user_by_login_returns_normalized_dict():
    body = {"data": [{"user_id": 9, "name": "SomeUser"}]}
    with patch.object(api.requests, "get", return_value=_response(body)) as mock_get:
        result = api.get_user_by_login("token", "someuser")
    assert result == {"id": "9", "login": "someuser", "display_name": "SomeUser"}
    assert mock_get.call_args.kwargs["params"] == {"slug": "someuser"}


def test_get_user_by_login_returns_none_when_not_found():
    with patch.object(api.requests, "get", return_value=_response({"data": []})):
        result = api.get_user_by_login("token", "nosuchuser")
    assert result is None


def test_search_channels_returns_data():
    body = {"data": [{"slug": "somechannel"}, {"slug": "otherchannel"}]}
    with patch.object(api.requests, "get", return_value=_response(body)) as mock_get:
        result = api.search_channels("token", "some", first=5)
    assert result == body["data"]
    assert mock_get.call_args.kwargs["params"] == {"searchQuery": "some", "limit": 5}


def test_search_channels_uses_search_base_not_api_base():
    body = {"data": []}
    with patch.object(api.requests, "get", return_value=_response(body)) as mock_get:
        api.search_channels("token", "query")
    called_url = mock_get.call_args.args[0]
    assert called_url == api.SEARCH_BASE + "/search/channels"
