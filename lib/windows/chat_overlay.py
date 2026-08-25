"""Non-modal chat overlay shown during playback."""
import textwrap
import threading
import time

import xbmc
import xbmcgui

from lib.twitch.irc import ChatClient

# Caps how often the message list is rebuilt, regardless of message rate -
# a busy channel's chat can arrive several messages/second, and without
# this a full control.reset()+addItems() per message floods the GUI
# thread badly enough to delay it processing input (e.g. Back).
_RENDER_THROTTLE_SECONDS = 0.25

# The skin's <wrapmultiline> label tag isn't honored on this Kodi build (long
# messages render as a single ellipsized line no matter how tall the label
# is), so lines are wrapped by hand and joined with literal newlines, which
# Kodi labels always render regardless of wrapmultiline support. Width is
# chars-per-line for the message label at its skin font/box size - measured
# against live rendering (a 39-char line still got ellipsized), not computed
# from font metrics, since this build's actual glyph width per point is
# wider than the font size alone would suggest.
_MESSAGE_WRAP_WIDTH = 26

# Caps wrapped lines to what the message label's fixed skin height can show.
# Without this, a message that wraps to more lines than fit just gets cut off
# mid-glyph at the label's bottom edge with no ellipsis (no "..." appears
# because this is a hard clip, not the single-line width truncation that
# does add one) - so the cutoff is done here instead, cleanly, with a
# visible "..." marking that the message was cut.
_MAX_MESSAGE_LINES = 5

# Fixed number of emote image-control slots in the skin's per-item layout
# (ids 110-115, see resources/skins/Default/1080i/script-twitch-center-chat-overlay.xml).
# Re-capped here independently of eventsub.py's own _MAX_EMOTES_PER_MESSAGE cap - this
# function must not assume its caller already enforced the limit.
_MAX_EMOTE_SLOTS = 6


def _wrap_message_lines(text):
    lines = textwrap.wrap(text, _MESSAGE_WRAP_WIDTH)
    if len(lines) > _MAX_MESSAGE_LINES:
        lines = lines[:_MAX_MESSAGE_LINES]
        lines[-1] = lines[-1][: max(0, _MESSAGE_WRAP_WIDTH - 3)].rstrip() + "..."
    return lines


def _build_message_item(event):
    item = xbmcgui.ListItem(event["display_name"])
    lines = _wrap_message_lines(event["text"])
    item.setLabel2("\n".join(lines))
    emotes = (event.get("emotes") or [])[:_MAX_EMOTE_SLOTS]
    if emotes:
        art = {
            "emote_%d" % i: emote.get("url")
            for i, emote in enumerate(emotes)
            if emote.get("url")
        }
        if art:
            item.setArt(art)
    return item


class ChatOverlay(xbmcgui.WindowXMLDialog):
    MESSAGE_LIST_ID = 101
    _MAX_MESSAGES = 50

    def __init__(self, *args, channel, access_token=None, client_id=None,
                 broadcaster_user_id=None, user_id=None, chat_client_cls=None, time_fn=None,
                 **kwargs):
        super().__init__(*args, **kwargs)
        self.channel = channel
        self._access_token = access_token
        self._client_id = client_id
        self._broadcaster_user_id = broadcaster_user_id
        self._user_id = user_id
        self._chat_client_cls = chat_client_cls or ChatClient
        self._time_fn = time_fn or time.time
        self._client = None
        self._messages = []
        self._cancel_event = threading.Event()
        self._thread = None
        self._last_render_at = None
        self._total_evicted = 0
        self._control_evicted = 0

    # Actions that should reach the player's own OSD/context menu instead of
    # being swallowed by this dialog - without this, the overlay (which is
    # the focused, topmost window during playback) eats these and the user
    # has to close chat before opening player options. ACTION_SELECT_ITEM is
    # included because on at least one CEC remote setup, Select/Enter (not a
    # dedicated OSD/context-menu button) is what triggers the player's OSD -
    # the overlay has no meaningful use for Select itself (chat has nothing
    # clickable), so forwarding it here doesn't lose any overlay function.
    _PLAYER_FORWARD_ACTIONS = (
        xbmcgui.ACTION_SHOW_OSD,
        xbmcgui.ACTION_CONTEXT_MENU,
        xbmcgui.ACTION_SELECT_ITEM,
    )

    def onAction(self, action):
        if action.getId() in self._PLAYER_FORWARD_ACTIONS:
            xbmc.executebuiltin("Action(%d)" % action.getId())
            return
        super().onAction(action)

    def onInit(self):
        self._client = self._chat_client_cls(
            self.channel,
            access_token=self._access_token,
            client_id=self._client_id,
            broadcaster_user_id=self._broadcaster_user_id,
            user_id=self._user_id,
        )
        self._client.connect()
        self._thread = threading.Thread(target=self._pump_messages, daemon=True)
        self._thread.start()

    def _pump_messages(self):
        try:
            for event in self._client.read_messages():
                if self._cancel_event.is_set():
                    break
                if event["type"] != "message":
                    continue
                before = len(self._messages)
                self._messages.append(event)
                del self._messages[:-self._MAX_MESSAGES]
                self._total_evicted += (before + 1) - len(self._messages)
                now = self._time_fn()
                if self._last_render_at is None or now - self._last_render_at >= _RENDER_THROTTLE_SECONDS:
                    self._render()
                    self._last_render_at = now
            # Flush whatever arrived since the last throttled render, so the
            # overlay never ends up stuck showing a stale message set.
            self._render()
        except Exception as exc:
            xbmc.log(
                "script.twitch.center: chat overlay pump thread failed: " + repr(exc),
                xbmc.LOGERROR,
            )

    def _render(self):
        # Incremental: only remove items evicted from the front and append
        # items new since the last render, instead of reset()+addItems() of
        # the whole list. A full rebuild recreates every ListItem on every
        # tick, which re-triggers async emote art loading for messages
        # already on screen (visible as emote art popping in several
        # renders after the message first appeared).
        control = self._safe_control(self.MESSAGE_LIST_ID)
        if not control:
            return
        pending_evictions = self._total_evicted - self._control_evicted
        for _ in range(pending_evictions):
            if control.size() <= 0:
                break
            control.removeItem(0)
        self._control_evicted = self._total_evicted

        to_add = len(self._messages) - control.size()
        if to_add > 0:
            control.addItems([_build_message_item(event) for event in self._messages[-to_add:]])

        if self._messages:
            control.selectItem(control.size() - 1)

    def _safe_control(self, control_id):
        try:
            return self.getControl(control_id)
        except Exception:
            return None

    def close(self):
        self._cancel_event.set()
        if self._client is not None:
            self._client.disconnect()
        super().close()
