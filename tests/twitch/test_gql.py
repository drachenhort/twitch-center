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


def test_get_followed_live_games_omits_authorization_header_without_website_token():
    body = [{"data": {"currentUser": {"followedGames": {"nodes": []}}}}]
    with patch.object(gql.requests, "post", return_value=_response(body)) as mock_post:
        gql.get_followed_live_games()
    headers = mock_post.call_args.kwargs["headers"]
    assert headers["Client-Id"] == gql.WEB_CLIENT_ID
    assert "Authorization" not in headers


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


def test_get_followed_live_games_falls_back_to_name_when_display_name_missing():
    # Per-node field access must be defensive: a node missing displayName
    # (one of the three unverified field-name guesses) should still produce
    # a usable entry via the "name" fallback, not abort the whole list.
    body = [
        {
            "data": {
                "currentUser": {
                    "followedGames": {
                        "nodes": [
                            {"id": "1", "name": "just-chatting", "displayName": "Just Chatting"},
                            {"id": "2", "name": "programming"},
                        ]
                    }
                }
            }
        }
    ]
    with patch.object(gql.requests, "post", return_value=_response(body)):
        result = gql.get_followed_live_games("access-token")
    assert result == [
        {"id": "1", "name": "just-chatting", "displayName": "Just Chatting"},
        {"id": "2", "name": "programming", "displayName": "programming"},
    ]


def test_get_followed_live_games_skips_node_missing_both_name_fields():
    # A single unusable node (missing both displayName and name) must be
    # skipped, not cause the whole call to degrade to [].
    body = [
        {
            "data": {
                "currentUser": {
                    "followedGames": {
                        "nodes": [
                            {"id": "1", "name": "just-chatting", "displayName": "Just Chatting"},
                            {"id": "2"},
                            {"id": "3", "name": "programming", "displayName": "Programming"},
                        ]
                    }
                }
            }
        }
    ]
    with patch.object(gql.requests, "post", return_value=_response(body)):
        result = gql.get_followed_live_games("access-token")
    assert result == [
        {"id": "1", "name": "just-chatting", "displayName": "Just Chatting"},
        {"id": "3", "name": "programming", "displayName": "Programming"},
    ]


def test_get_playback_access_token_returns_value_and_signature_on_success():
    body = {
        "data": {
            "streamPlaybackAccessToken": {"value": "opaque-token-json", "signature": "abc123"}
        }
    }
    with patch.object(gql.requests, "post", return_value=_response(body)) as mock_post:
        result = gql.get_playback_access_token("somechannel")
    assert result == {"value": "opaque-token-json", "signature": "abc123"}
    payload = mock_post.call_args.kwargs["json"]
    assert payload["operationName"] == "PlaybackAccessToken"
    assert payload["variables"] == {
        "isLive": True,
        "login": "somechannel",
        "isVod": False,
        "vodID": "",
        "playerType": "site",
        "platform": "web",
    }
    assert (
        payload["extensions"]["persistedQuery"]["sha256Hash"]
        == "ed230aa1e33e07eebb8928504583da78a5173989fadfb1ac94be06a04f3cdbe9"
    )
    headers = mock_post.call_args.kwargs["headers"]
    assert headers["Client-Id"] == gql.WEB_CLIENT_ID
    # Deliberately no Authorization header - see the function's docstring:
    # gql.twitch.tv rejects any user token from a non-Twitch client_id here,
    # regardless of the Client-Id header sent, and anonymous access works
    # fine for public live streams.
    assert "Authorization" not in headers


def test_get_playback_access_token_sends_authorization_when_website_token_given():
    body = {
        "data": {
            "streamPlaybackAccessToken": {"value": "opaque-token-json", "signature": "abc123"}
        }
    }
    with patch.object(gql.requests, "post", return_value=_response(body)) as mock_post:
        gql.get_playback_access_token("somechannel", "my-website-token")
    headers = mock_post.call_args.kwargs["headers"]
    assert headers["Authorization"] == "OAuth my-website-token"


def test_get_playback_access_token_returns_none_on_401():
    with patch.object(gql.requests, "post", return_value=_response({}, status_code=401)):
        assert gql.get_playback_access_token("somechannel") is None


def test_get_playback_access_token_returns_none_on_network_error():
    with patch.object(gql.requests, "post", side_effect=requests.ConnectionError("boom")):
        assert gql.get_playback_access_token("somechannel") is None


def test_get_playback_access_token_returns_none_on_other_non_200():
    with patch.object(gql.requests, "post", return_value=_response({}, status_code=500)):
        assert gql.get_playback_access_token("somechannel") is None


def test_get_playback_access_token_returns_none_on_missing_token_data():
    body = {"data": {"streamPlaybackAccessToken": None}}
    with patch.object(gql.requests, "post", return_value=_response(body)):
        assert gql.get_playback_access_token("somechannel") is None


def test_get_playback_access_token_returns_none_on_unexpected_shape():
    with patch.object(gql.requests, "post", return_value=_response({"unexpected": "shape"})):
        assert gql.get_playback_access_token("somechannel") is None
