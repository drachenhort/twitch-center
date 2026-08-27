import xbmcaddon

from lib import providers


def test_get_kick_favorites_defaults_to_empty_list():
    addon = xbmcaddon.Addon()
    assert providers.get_kick_favorites(addon) == []


def test_get_kick_favorites_returns_empty_list_for_malformed_json():
    addon = xbmcaddon.Addon()
    addon.setSetting("kick_favorite_channels", "not-json")
    assert providers.get_kick_favorites(addon) == []


def test_get_kick_favorites_returns_empty_list_for_non_list_json():
    addon = xbmcaddon.Addon()
    addon.setSetting("kick_favorite_channels", '{"not": "a list"}')
    assert providers.get_kick_favorites(addon) == []


def test_add_kick_favorite_appends_and_persists():
    addon = xbmcaddon.Addon()
    providers.add_kick_favorite(addon, "somechannel")
    assert providers.get_kick_favorites(addon) == ["somechannel"]


def test_add_kick_favorite_is_idempotent():
    addon = xbmcaddon.Addon()
    providers.add_kick_favorite(addon, "somechannel")
    providers.add_kick_favorite(addon, "somechannel")
    assert providers.get_kick_favorites(addon) == ["somechannel"]


def test_remove_kick_favorite_deletes_it():
    addon = xbmcaddon.Addon()
    providers.add_kick_favorite(addon, "somechannel")
    providers.add_kick_favorite(addon, "otherchannel")
    providers.remove_kick_favorite(addon, "somechannel")
    assert providers.get_kick_favorites(addon) == ["otherchannel"]


def test_remove_kick_favorite_is_a_no_op_if_not_present():
    addon = xbmcaddon.Addon()
    providers.add_kick_favorite(addon, "somechannel")
    providers.remove_kick_favorite(addon, "nosuchchannel")
    assert providers.get_kick_favorites(addon) == ["somechannel"]


from unittest.mock import patch

from lib import providers


def test_normalize_twitch_channel_live():
    channel = {"broadcaster_id": "1", "broadcaster_login": "alice", "broadcaster_name": "Alice"}
    stream_data = {
        "viewer_count": 500,
        "game_name": "Just Chatting",
        "thumbnail_url": "https://example.invalid/{width}x{height}.jpg",
    }
    result = providers.normalize_twitch_channel(channel, stream_data)
    assert result == {
        "platform": "twitch",
        "id": "1",
        "login": "alice",
        "display_name": "Alice",
        "is_live": True,
        "viewer_count": 500,
        "game_name": "Just Chatting",
        "thumbnail_url": "https://example.invalid/320x180.jpg",
    }


def test_normalize_twitch_channel_offline():
    channel = {"broadcaster_id": "1", "broadcaster_login": "alice", "broadcaster_name": "Alice"}
    result = providers.normalize_twitch_channel(channel)
    assert result == {
        "platform": "twitch",
        "id": "1",
        "login": "alice",
        "display_name": "Alice",
        "is_live": False,
        "viewer_count": 0,
        "game_name": "",
        "thumbnail_url": "",
    }


def test_get_kick_live_favorites_returns_empty_list_when_no_favorites():
    addon = xbmcaddon.Addon()
    assert providers.get_kick_live_favorites(addon) == []


def test_get_kick_live_favorites_needs_no_kick_login():
    # The unofficial channel endpoint is public/unauthenticated - no
    # kick_token needed at all, unlike the old official-API implementation.
    addon = xbmcaddon.Addon()  # no kick_token set
    providers.add_kick_favorite(addon, "livechannel")

    def fake_get_unofficial_channel(slug):
        assert slug == "livechannel"
        return {"id": 42, "slug": "livechannel", "livestream": {"is_live": True, "viewer_count": 300}}

    result = providers.get_kick_live_favorites(addon, get_unofficial_channel_fn=fake_get_unofficial_channel)
    assert [item["login"] for item in result] == ["livechannel"]


def test_get_kick_live_favorites_normalizes_live_favorites_only():
    addon = xbmcaddon.Addon()
    providers.add_kick_favorite(addon, "livechannel")
    providers.add_kick_favorite(addon, "offlinechannel")

    def fake_get_unofficial_channel(slug):
        if slug == "livechannel":
            return {
                "id": 42,
                "slug": "livechannel",
                "livestream": {
                    "is_live": True,
                    "viewer_count": 300,
                    "thumbnail": {"url": "https://example.invalid/thumb.jpg"},
                    "categories": [{"name": "Just Chatting"}],
                },
            }
        return {"id": 43, "slug": "offlinechannel", "livestream": {"is_live": False}}

    result = providers.get_kick_live_favorites(addon, get_unofficial_channel_fn=fake_get_unofficial_channel)
    assert result == [
        {
            "platform": "kick",
            "id": "42",
            "login": "livechannel",
            "display_name": "livechannel",
            "is_live": True,
            "viewer_count": 300,
            "game_name": "Just Chatting",
            "thumbnail_url": "https://example.invalid/thumb.jpg",
        }
    ]


def test_get_kick_live_favorites_skips_a_favorite_that_errors():
    addon = xbmcaddon.Addon()
    providers.add_kick_favorite(addon, "brokenchannel")
    providers.add_kick_favorite(addon, "goodchannel")

    def fake_get_unofficial_channel(slug):
        if slug == "brokenchannel":
            raise Exception("boom")
        return {"id": 7, "slug": "goodchannel", "livestream": {"is_live": True, "viewer_count": 10}}

    result = providers.get_kick_live_favorites(addon, get_unofficial_channel_fn=fake_get_unofficial_channel)
    assert [item["login"] for item in result] == ["goodchannel"]


def test_get_kick_live_favorites_defensively_handles_missing_fields():
    # The unofficial endpoint's response shape isn't fully confirmed - this
    # pins the "never crash on an unexpected shape" contract regardless of
    # which fields turn out to be right.
    addon = xbmcaddon.Addon()
    providers.add_kick_favorite(addon, "sparsechannel")

    def fake_get_unofficial_channel(slug):
        return {"id": 1, "slug": "sparsechannel", "livestream": {"is_live": True}}

    result = providers.get_kick_live_favorites(addon, get_unofficial_channel_fn=fake_get_unofficial_channel)
    assert result == [
        {
            "platform": "kick",
            "id": "1",
            "login": "sparsechannel",
            "display_name": "sparsechannel",
            "is_live": True,
            "viewer_count": 0,
            "game_name": "",
            "thumbnail_url": "",
        }
    ]


def test_merge_by_viewer_count_interleaves_descending():
    twitch_items = [
        {"platform": "twitch", "viewer_count": 500},
        {"platform": "twitch", "viewer_count": 50},
    ]
    kick_items = [
        {"platform": "kick", "viewer_count": 300},
    ]
    merged = providers.merge_by_viewer_count(twitch_items, kick_items)
    assert [item["viewer_count"] for item in merged] == [500, 300, 50]


def test_merge_by_viewer_count_handles_empty_lists():
    assert providers.merge_by_viewer_count([], []) == []
    assert providers.merge_by_viewer_count([{"platform": "twitch", "viewer_count": 1}], []) == [
        {"platform": "twitch", "viewer_count": 1}
    ]


def _set_kick_app_credentials(addon):
    addon.setSetting("kick_client_id", "cid")
    addon.setSetting("kick_client_secret", "csecret")


def test_get_kick_top_categories_returns_empty_list_when_no_kick_app_credentials():
    addon = xbmcaddon.Addon()
    assert providers.get_kick_top_categories(addon) == []


def test_get_kick_top_categories_returns_categories_when_configured():
    addon = xbmcaddon.Addon()
    _set_kick_app_credentials(addon)

    def fake_get_top_categories(access_token):
        assert access_token == "apptok"
        return [{"id": 7, "name": "Just Chatting"}, {"id": 8, "name": "Games"}]

    with patch.object(kick_auth, "get_app_access_token", return_value="apptok"):
        result = providers.get_kick_top_categories(addon, get_top_categories_fn=fake_get_top_categories)
    assert result == [{"id": 7, "name": "Just Chatting"}, {"id": 8, "name": "Games"}]


def test_get_kick_top_categories_returns_empty_list_on_error():
    addon = xbmcaddon.Addon()
    _set_kick_app_credentials(addon)

    def failing(access_token):
        raise Exception("boom")

    with patch.object(kick_auth, "get_app_access_token", return_value="apptok"):
        result = providers.get_kick_top_categories(addon, get_top_categories_fn=failing)
    assert result == []


def test_search_kick_categories_returns_empty_list_when_no_kick_app_credentials():
    addon = xbmcaddon.Addon()
    assert providers.search_kick_categories(addon, "eve") == []


def test_search_kick_categories_returns_matches_when_configured():
    addon = xbmcaddon.Addon()
    _set_kick_app_credentials(addon)

    def fake_search_categories(access_token, query):
        assert access_token == "apptok"
        assert query == "eve"
        return [{"id": 3, "name": "EVE Online"}]

    with patch.object(kick_auth, "get_app_access_token", return_value="apptok"):
        result = providers.search_kick_categories(addon, "eve", search_categories_fn=fake_search_categories)
    assert result == [{"id": 3, "name": "EVE Online"}]


def test_search_kick_categories_returns_empty_list_on_error():
    addon = xbmcaddon.Addon()
    _set_kick_app_credentials(addon)

    def failing(access_token, query):
        raise Exception("boom")

    with patch.object(kick_auth, "get_app_access_token", return_value="apptok"):
        result = providers.search_kick_categories(addon, "eve", search_categories_fn=failing)
    assert result == []


def test_get_kick_category_streams_returns_empty_list_when_no_kick_app_credentials():
    addon = xbmcaddon.Addon()
    assert providers.get_kick_category_streams(addon, category_id=7) == []


def test_get_kick_category_streams_normalizes_results():
    addon = xbmcaddon.Addon()
    _set_kick_app_credentials(addon)

    def fake_get_live_streams(access_token, category_id=None, first=20):
        assert access_token == "apptok"
        assert category_id == 7
        return [
            {
                "broadcaster_user_id": 1,
                "slug": "somechannel",
                "viewer_count": 42,
                "category": {"name": "Just Chatting"},
            }
        ]

    with patch.object(kick_auth, "get_app_access_token", return_value="apptok"):
        result = providers.get_kick_category_streams(addon, category_id=7, get_live_streams_fn=fake_get_live_streams)
    assert result == [
        {
            "platform": "kick",
            "id": "1",
            "login": "somechannel",
            "display_name": "somechannel",
            "is_live": True,
            "viewer_count": 42,
            "game_name": "Just Chatting",
            "thumbnail_url": "",
        }
    ]


def test_get_kick_category_streams_returns_empty_list_on_error():
    addon = xbmcaddon.Addon()
    _set_kick_app_credentials(addon)

    def failing(access_token, category_id=None, first=20):
        raise Exception("boom")

    with patch.object(kick_auth, "get_app_access_token", return_value="apptok"):
        result = providers.get_kick_category_streams(addon, category_id=7, get_live_streams_fn=failing)
    assert result == []


import pytest

from lib.kick import auth as kick_auth
from lib.kick import stream as kick_stream
from lib.twitch import stream as twitch_stream


def test_resolve_stream_url_dispatches_to_twitch():
    addon = xbmcaddon.Addon()
    addon.setSetting("website_token", "webtok")
    with patch.object(twitch_stream, "resolve_stream_url", return_value="https://twitch.example/x.m3u8") as mock:
        url = providers.resolve_stream_url(addon, "twitch", "somechannel")
    mock.assert_called_once_with("somechannel", "webtok")
    assert url == "https://twitch.example/x.m3u8"


def test_resolve_stream_url_wraps_twitch_unavailable_error():
    addon = xbmcaddon.Addon()
    with patch.object(twitch_stream, "resolve_stream_url", side_effect=twitch_stream.StreamUnavailableError("x")):
        with pytest.raises(providers.StreamUnavailableError):
            providers.resolve_stream_url(addon, "twitch", "somechannel")


def test_resolve_stream_url_dispatches_to_kick():
    # No kick_token needed - kick_stream.resolve_stream_url uses the
    # unofficial, unauthenticated endpoint.
    addon = xbmcaddon.Addon()
    with patch.object(kick_stream, "resolve_stream_url", return_value="https://kick.example/x.m3u8") as mock:
        url = providers.resolve_stream_url(addon, "kick", "somechannel")
    mock.assert_called_once_with(None, "somechannel")
    assert url == "https://kick.example/x.m3u8"


def test_resolve_stream_url_wraps_kick_unavailable_error():
    addon = xbmcaddon.Addon()
    with patch.object(kick_stream, "resolve_stream_url", side_effect=kick_stream.StreamUnavailableError("x")):
        with pytest.raises(providers.StreamUnavailableError):
            providers.resolve_stream_url(addon, "kick", "somechannel")


def test_resolve_stream_url_raises_for_unknown_platform():
    addon = xbmcaddon.Addon()
    with pytest.raises(providers.StreamUnavailableError):
        providers.resolve_stream_url(addon, "nonsense", "somechannel")


def test_resolve_stream_url_wraps_any_twitch_exception():
    # twitch_stream.resolve_stream_url can also let requests exceptions
    # (HTTPError, RequestException, ...) propagate on a network failure, none
    # of which is twitch_stream.StreamUnavailableError. None of those should
    # ever escape providers.resolve_stream_url uncaught.
    addon = xbmcaddon.Addon()
    addon.setSetting("website_token", "webtok")
    with patch.object(twitch_stream, "resolve_stream_url", side_effect=Exception("network error")):
        with pytest.raises(providers.StreamUnavailableError):
            providers.resolve_stream_url(addon, "twitch", "somechannel")


def test_resolve_stream_url_wraps_any_kick_exception():
    # kick_stream.resolve_stream_url's call chain can raise things other than
    # kick_stream.StreamUnavailableError - e.g. TokenExpiredError on an expired
    # token, or requests exceptions (HTTPError, RequestException, ...) on other
    # HTTP errors or network failures. None of those should ever escape
    # providers.resolve_stream_url uncaught.
    addon = xbmcaddon.Addon()
    with patch.object(kick_stream, "resolve_stream_url", side_effect=Exception("token expired")):
        with pytest.raises(providers.StreamUnavailableError):
            providers.resolve_stream_url(addon, "kick", "somechannel")


def test_resolve_vod_url_dispatches_to_twitch():
    addon = xbmcaddon.Addon()
    addon.setSetting("website_token", "webtok")
    with patch.object(twitch_stream, "resolve_vod_url", return_value="https://twitch.example/vod.m3u8") as mock:
        url = providers.resolve_vod_url(addon, "123456789")
    mock.assert_called_once_with("123456789", "webtok")
    assert url == "https://twitch.example/vod.m3u8"


def test_resolve_vod_url_wraps_unavailable_error():
    addon = xbmcaddon.Addon()
    with patch.object(twitch_stream, "resolve_vod_url", side_effect=twitch_stream.StreamUnavailableError("x")):
        with pytest.raises(providers.StreamUnavailableError):
            providers.resolve_vod_url(addon, "123456789")


def test_resolve_vod_url_wraps_any_exception():
    addon = xbmcaddon.Addon()
    with patch.object(twitch_stream, "resolve_vod_url", side_effect=Exception("network error")):
        with pytest.raises(providers.StreamUnavailableError):
            providers.resolve_vod_url(addon, "123456789")


def test_resolve_clip_url_dispatches_to_twitch():
    addon = xbmcaddon.Addon()
    thumb = "https://clips-media-assets2.twitch.tv/AB12CD34-preview-480x272.jpg"
    with patch.object(twitch_stream, "resolve_clip_url", return_value="https://twitch.example/clip.mp4") as mock:
        url = providers.resolve_clip_url(addon, thumb)
    mock.assert_called_once_with(thumb)
    assert url == "https://twitch.example/clip.mp4"


def test_resolve_clip_url_wraps_unavailable_error():
    addon = xbmcaddon.Addon()
    with patch.object(twitch_stream, "resolve_clip_url", side_effect=twitch_stream.StreamUnavailableError("x")):
        with pytest.raises(providers.StreamUnavailableError):
            providers.resolve_clip_url(addon, "bad-url")
