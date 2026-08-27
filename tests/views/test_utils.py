from lib.views import utils as view_utils


def test_build_followed_channel_item_sets_properties():
    channel = {"broadcaster_id": "1", "broadcaster_login": "somechannel", "broadcaster_name": "SomeChannel"}
    item = view_utils.build_followed_channel_item(channel)
    assert item.getLabel() == "SomeChannel"
    assert item.getProperty("broadcaster_id") == "1"
    assert item.getProperty("broadcaster_login") == "somechannel"
    assert item.getProperty("broadcaster_name") == "SomeChannel"


def test_build_video_list_item_sets_properties():
    video = {
        "id": "999", "title": "Epic Stream", "created_at": "2026-08-20T00:00:00Z",
        "duration": "3h8m33s", "thumbnail_url": "https://example.invalid/thumb-%{width}x%{height}.jpg",
        "view_count": 150,
    }
    item = view_utils.build_video_list_item(video)
    assert item.getLabel() == "Epic Stream"
    assert item.getProperty("video_id") == "999"
    assert item.getProperty("duration") == "3h8m33s"
    assert item.getProperty("view_count") == "150"
    assert item.getLabel2() == "3h8m33s · 150 views"
    assert item.getArt("thumb") == "https://example.invalid/thumb-%320x%180.jpg"


def test_build_clip_list_item_sets_properties():
    clip = {
        "id": "abc", "title": "Great Play", "created_at": "2026-08-20T00:00:00Z",
        "duration": 29.9, "thumbnail_url": "https://clips-media-assets2.twitch.tv/AB12CD34-preview-480x272.jpg",
        "view_count": 42,
    }
    item = view_utils.build_clip_list_item(clip)
    assert item.getLabel() == "Great Play"
    assert item.getProperty("thumbnail_url") == clip["thumbnail_url"]
    assert item.getProperty("view_count") == "42"
    assert item.getLabel2() == "29s · 42 views"
    assert item.getArt("thumb") == "https://clips-media-assets2.twitch.tv/AB12CD34-preview-480x272.jpg"
