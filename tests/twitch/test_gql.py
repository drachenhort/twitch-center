from unittest.mock import MagicMock, patch

import requests

from lib.twitch import gql


def _response(json_body, status_code=200):
    response = MagicMock()
    response.status_code = status_code
    response.json.return_value = json_body
    return response


def test_get_followed_live_games_returns_parsed_list_on_success():
    body = [
        {
            "data": {
                "currentUser": {
                    "followedGames": {
                        "nodes": [
                            {"id": "1", "name": "just-chatting", "displayName": "Just Chatting"},
                            {"id": "2", "name": "programming", "displayName": "Programming"},
                        ]
                    }
                }
            }
        }
    ]
    with patch.object(gql.requests, "post", return_value=_response(body)) as mock_post:
        result = gql.get_followed_live_games("access-token")
    assert result == [
        {"id": "1", "name": "just-chatting", "displayName": "Just Chatting"},
        {"id": "2", "name": "programming", "displayName": "Programming"},
    ]
    headers = mock_post.call_args.kwargs["headers"]
    assert headers["Client-Id"] == gql.WEB_CLIENT_ID
    assert headers["Authorization"] == "OAuth access-token"


def test_get_followed_live_games_sends_expected_query_and_variables():
    body = [{"data": {"currentUser": {"followedGames": {"nodes": []}}}}]
    with patch.object(gql.requests, "post", return_value=_response(body)) as mock_post:
        gql.get_followed_live_games("access-token", limit=50)
    payload = mock_post.call_args.kwargs["json"]
    assert payload[0]["operationName"] == "FollowingGames_CurrentUser"
    assert payload[0]["variables"] == {"limit": 50, "type": "LIVE"}
    assert (
        payload[0]["extensions"]["persistedQuery"]["sha256Hash"]
        == "f3c5d45175d623ed3d5ff4ca4c7de379ea6a1a4852236087dc1b81b7dbfd3114"
    )


def test_get_followed_live_games_returns_empty_list_on_network_error():
    with patch.object(gql.requests, "post", side_effect=requests.ConnectionError("boom")):
        result = gql.get_followed_live_games("access-token")
    assert result == []


def test_get_followed_live_games_returns_empty_list_on_non_200():
    with patch.object(gql.requests, "post", return_value=_response({}, status_code=401)):
        result = gql.get_followed_live_games("access-token")
    assert result == []


def test_get_followed_live_games_returns_empty_list_on_unexpected_shape():
    with patch.object(
        gql.requests, "post", return_value=_response({"unexpected": "shape"})
    ):
        result = gql.get_followed_live_games("access-token")
    assert result == []


def test_get_followed_live_games_returns_empty_list_on_missing_nodes_key():
    body = [{"data": {"currentUser": {"followedGames": {}}}}]
    with patch.object(gql.requests, "post", return_value=_response(body)):
        result = gql.get_followed_live_games("access-token")
    assert result == []
