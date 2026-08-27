"""Shared helpers for Kodi view implementations.

Extracted from discover_view.py and live_streams_view.py so view code stays
lean. Only imports from xbmc* (Kodi) and standard library — no lib.* or
lib.views.* circular dependencies.
"""

import xbmcgui


def thumbnail_url(raw_url, width=320, height=180):
    """Replace {width}/{height} placeholders in a Twitch thumbnail URL."""
    return raw_url.replace("{width}", str(width)).replace("{height}", str(height))


# ---------------------------------------------------------------------------
# xbmcgui.ListItem builders
# ---------------------------------------------------------------------------


def _game_viewers_label(game_name, viewer_count):
    return f"{game_name} - {viewer_count} viewers"


def _set_stream_properties(item, broadcaster_id, broadcaster_login, platform, is_live, game_name, viewer_count):
    item.setProperty("broadcaster_id", broadcaster_id)
    item.setProperty("broadcaster_login", broadcaster_login)
    item.setProperty("platform", platform)
    item.setProperty("is_live", "true" if is_live else "false")
    item.setProperty("game_name", game_name)
    item.setProperty("viewer_count", str(viewer_count))
    return item


def build_stream_item(stream_data):
    """Build a ListItem for a live Twitch stream entry (from Helix)."""
    item = xbmcgui.ListItem(stream_data["user_name"])
    item.setLabel2(_game_viewers_label(stream_data["game_name"], stream_data["viewer_count"]))
    item.setArt({"thumb": thumbnail_url(stream_data["thumbnail_url"])})
    return _set_stream_properties(
        item,
        stream_data["user_id"],
        stream_data["user_login"],
        "twitch",
        True,
        stream_data["game_name"],
        stream_data["viewer_count"],
    )


def build_channel_item(channel):
    """Build a ListItem for a followed Twitch channel (live or offline)."""
    is_live = channel.get("is_live")
    item = xbmcgui.ListItem(channel["display_name"])
    item.setLabel2("Live - " + channel.get("game_name", "") if is_live else "Offline")
    item.setArt({"thumb": channel.get("thumbnail_url", "")})
    return _set_stream_properties(
        item,
        channel.get("id", ""),
        channel.get("broadcaster_login", ""),
        "twitch",
        is_live,
        channel.get("game_name", ""),
        channel.get("viewer_count", ""),
    )


def build_kick_result_item(normalized):
    """Build a ListItem for a Kick stream/channel result."""
    item = xbmcgui.ListItem(normalized["display_name"])
    item.setLabel2(_game_viewers_label(normalized["game_name"], normalized["viewer_count"]))
    item.setArt({"thumb": normalized["thumbnail_url"]})
    return _set_stream_properties(
        item,
        normalized["id"],
        normalized["login"],
        "kick",
        True,
        normalized["game_name"],
        normalized["viewer_count"],
    )


def _set_live_list_properties(item, broadcaster_id, broadcaster_login, platform, game_name, viewer_count):
    _set_stream_properties(item, broadcaster_id, broadcaster_login, platform, True, game_name, viewer_count)
    item.setProperty("subtitle", f"{viewer_count} viewers · {game_name}")
    return item


def build_live_list_item(channel, stream_data):
    """Build a ListItem for a live followed Twitch channel on Live Streams."""
    item = xbmcgui.ListItem(channel["broadcaster_name"])
    item.setLabel2(_game_viewers_label(stream_data["game_name"], stream_data["viewer_count"]))
    item.setArt({"thumb": thumbnail_url(stream_data["thumbnail_url"])})
    return _set_live_list_properties(
        item,
        channel["broadcaster_id"],
        channel["broadcaster_login"],
        "twitch",
        stream_data["game_name"],
        stream_data["viewer_count"],
    )


def build_kick_list_item(normalized):
    """Build a ListItem for a live followed Kick channel on Live Streams."""
    item = xbmcgui.ListItem(normalized["display_name"])
    item.setLabel2(_game_viewers_label(normalized["game_name"], normalized["viewer_count"]))
    item.setArt({"thumb": normalized["thumbnail_url"]})
    return _set_live_list_properties(
        item,
        normalized["id"],
        normalized["login"],
        "kick",
        normalized["game_name"],
        normalized["viewer_count"],
    )


def build_offline_list_item(channel):
    """Build a ListItem for an offline followed Twitch channel."""
    item = xbmcgui.ListItem(channel["broadcaster_name"])
    item.setLabel2("Offline")
    item.setProperty("subtitle", "Offline")
    return _set_stream_properties(
        item,
        channel["broadcaster_id"],
        channel["broadcaster_login"],
        "twitch",
        False,
        "",
        "",
    )


# ---------------------------------------------------------------------------
# Live Streams – interleaving
# ---------------------------------------------------------------------------


def interleave_live_items(twitch_live, kick_live):
    """Interleave Twitch live tuples and Kick normalized dicts by viewer count.

    *twitch_live*: list of ``(channel, stream_data)`` tuples, already live-only.
    *kick_live*: list of normalized Kick dicts, already live-only.

    Returns built xbmcgui.ListItems sorted by viewer_count descending.
    """
    tagged = [(stream_data["viewer_count"], build_live_list_item, (channel, stream_data)) for channel, stream_data in twitch_live]
    tagged += [(normalized["viewer_count"], build_kick_list_item, (normalized,)) for normalized in kick_live]
    tagged.sort(key=lambda entry: entry[0], reverse=True)
    return [builder(*args) for _viewer_count, builder, args in tagged]


def build_followed_channel_item(channel):
    """Build a ListItem for a followed Twitch channel on the VODs & Clips channel picker -
    every followed channel regardless of current live status (VODs/Clips exist independent
    of whether the channel is live right now)."""
    item = xbmcgui.ListItem(channel["broadcaster_name"])
    item.setProperty("broadcaster_id", channel["broadcaster_id"])
    item.setProperty("broadcaster_login", channel["broadcaster_login"])
    item.setProperty("broadcaster_name", channel["broadcaster_name"])
    return item


def build_video_list_item(video):
    """Build a ListItem for one VOD tile on the VODs & Clips content screen."""
    item = xbmcgui.ListItem(video["title"])
    item.setLabel2(f"{video['duration']} · {video['view_count']} views")
    item.setArt({"thumb": thumbnail_url(video["thumbnail_url"])})
    item.setProperty("video_id", video["id"])
    item.setProperty("duration", video["duration"])
    item.setProperty("view_count", str(video["view_count"]))
    return item


def build_clip_list_item(clip):
    """Build a ListItem for one Clip tile on the VODs & Clips content screen."""
    item = xbmcgui.ListItem(clip["title"])
    item.setLabel2(f"{int(clip['duration'])}s · {clip['view_count']} views")
    item.setArt({"thumb": clip["thumbnail_url"]})
    item.setProperty("thumbnail_url", clip["thumbnail_url"])
    item.setProperty("view_count", str(clip["view_count"]))
    return item