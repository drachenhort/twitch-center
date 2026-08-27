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


def test_get_vod_playback_access_token_returns_value_and_signature():
    body = {"data": {"videoPlaybackAccessToken": {"value": "vod-token-json", "signature": "sig123"}}}
    with patch.object(gql.requests, "post", return_value=_response(body)) as mock_post:
        token = gql.get_vod_playback_access_token("123456789")
    assert token == {"value": "vod-token-json", "signature": "sig123"}
    variables = mock_post.call_args.kwargs["json"]["variables"]
    assert variables["isLive"] is False
    assert variables["isVod"] is True
    assert variables["vodID"] == "123456789"
    assert variables["login"] == ""


def test_get_vod_playback_access_token_returns_none_on_missing_field():
    body = {"data": {}}
    with patch.object(gql.requests, "post", return_value=_response(body)):
        assert gql.get_vod_playback_access_token("123456789") is None


def test_get_vod_playback_access_token_returns_none_on_non_200():
    with patch.object(gql.requests, "post", return_value=_response({}, status_code=500)):
        assert gql.get_vod_playback_access_token("123456789") is None


def test_get_vod_playback_access_token_returns_none_on_request_exception():
    with patch.object(gql.requests, "post", side_effect=requests.RequestException("boom")):
        assert gql.get_vod_playback_access_token("123456789") is None


def test_get_vod_playback_access_token_passes_website_token_through():
    body = {"data": {"videoPlaybackAccessToken": {"value": "v", "signature": "s"}}}
    with patch.object(gql.requests, "post", return_value=_response(body)) as mock_post:
        gql.get_vod_playback_access_token("123456789", "my-website-token")
    headers = mock_post.call_args.kwargs["headers"]
    assert headers["Authorization"] == "OAuth my-website-token"


def _clip_body(qualities, signature="sig123", value="tok-value"):
    return {
        "data": {
            "clip": {
                "playbackAccessToken": {"signature": signature, "value": value},
                "videoQualities": qualities,
            }
        }
    }


def test_get_clip_video_url_returns_highest_quality_source_url_with_token_appended():
    body = _clip_body(
        [
            {"quality": "480", "sourceURL": "https://example/480.mp4"},
            {"quality": "1080", "sourceURL": "https://example/1080.mp4"},
            {"quality": "720", "sourceURL": "https://example/720.mp4"},
        ],
        signature="sig123",
        value="tok value",
    )
    with patch.object(gql.requests, "post", return_value=_response(body)) as mock_post:
        result = gql.get_clip_video_url("SomeClipSlug")
    assert result == "https://example/1080.mp4?sig=sig123&token=tok%20value"
    payload = mock_post.call_args.kwargs["json"]
    assert payload["operationName"] == "VideoAccessToken_Clip"
    assert payload["variables"] == {"slug": "SomeClipSlug"}


def test_get_clip_video_url_returns_none_when_clip_missing():
    body = {"data": {"clip": None}}
    with patch.object(gql.requests, "post", return_value=_response(body)):
        assert gql.get_clip_video_url("SomeClipSlug") is None


def test_get_clip_video_url_returns_none_when_no_qualities():
    body = _clip_body([])
    with patch.object(gql.requests, "post", return_value=_response(body)):
        assert gql.get_clip_video_url("SomeClipSlug") is None


def test_get_clip_video_url_returns_none_when_token_missing():
    body = {"data": {"clip": {"playbackAccessToken": None, "videoQualities": [{"quality": "1080", "sourceURL": "https://example/1080.mp4"}]}}}
    with patch.object(gql.requests, "post", return_value=_response(body)):
        assert gql.get_clip_video_url("SomeClipSlug") is None


def test_get_clip_video_url_returns_none_on_non_200():
    with patch.object(gql.requests, "post", return_value=_response({}, status_code=500)):
        assert gql.get_clip_video_url("SomeClipSlug") is None


def test_get_clip_video_url_returns_none_on_request_exception():
    with patch.object(gql.requests, "post", side_effect=requests.RequestException("boom")):
        assert gql.get_clip_video_url("SomeClipSlug") is None


def test_get_clip_video_url_passes_website_token_through():
    body = _clip_body([{"quality": "1080", "sourceURL": "https://example/1080.mp4"}])
    with patch.object(gql.requests, "post", return_value=_response(body)) as mock_post:
        gql.get_clip_video_url("SomeClipSlug", "my-website-token")
    headers = mock_post.call_args.kwargs["headers"]
    assert headers["Authorization"] == "OAuth my-website-token"
