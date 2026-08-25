# Kick.com Integration — Reference Notes for twitch-center (Kodi addon)

Context: `twitch-center` is a Python Kodi addon. Goal is to add Kick.com support
alongside existing Twitch functionality, aiming for feature parity where
possible (browse live channels/categories, playback, chat).

This doc separates **official, supported API surface** from **unofficial/
undocumented endpoints** that fill the gaps Twitch-style addons typically also
rely on (e.g. Twitch's Helix vs. the undocumented GQL/usher trick). Treat the
unofficial section as best-effort and expect it to break without notice.

---

## 1. Official Public API

- Developer portal (app registration): `https://dev.kick.com`
- Docs: `https://docs.kick.com`
- Docs source (open, community-editable): `https://github.com/KickEngineering/KickDevDocs`
- OAuth server (separate host from the API): `https://id.kick.com`
- API base: `https://api.kick.com/public/v1/...`

### Auth: OAuth 2.1 with PKCE
1. Register an app in the dev portal → get `client_id` / `client_secret`.
2. Generate a `code_verifier` (random string), derive `code_challenge` via SHA-256.
3. Standard authorization-code + PKCE exchange against `id.kick.com`.
4. Use the resulting Bearer token against `api.kick.com/public/v1/...`.

**Resolved 2026-08-25:** yes - `docs.kick.com`'s OAuth flow doc confirms
`client_credentials` grant support (App Access Token), described as usable
"when user login is not required" for "publicly available data". Used by
`lib.kick.auth.get_app_access_token` for Discover's category browse/search,
so no interactive per-user PKCE login is needed for read-only browsing.
Playback and Kick Favorites need no token at all - see section 2 below.

### Known endpoints
- `GET /public/v1/livestreams` — query params seen: `category_id`, `language`,
  `sort`, `limit`. Returns viewer count, stream title, category, language,
  mature flag, tags, `started_at`, `broadcaster_user_id`, `slug`.

  Example:
  ```
  GET https://api.kick.com/public/v1/livestreams?category_id=101&language=en&sort=viewer_count&limit=20
  Authorization: Bearer YOUR_ACCESS_TOKEN
  ```

- `POST /public/v1/moderation/bans` — ban/timeout a chat user.
  ```json
  {
    "broadcaster_user_id": 123,
    "user_id": 456,
    "reason": "Spam"
  }
  ```
  (omit duration for a permanent ban)

- Categories, channels, users endpoints also exist under `/public/v1/` — check
  `docs.kick.com` / the KickDevDocs GitHub repo directly for the current full
  list and response shapes, since the API is still actively being expanded.

### Real-time events
- Official real-time integration is **webhook/event-subscription based**, not
  a push WebSocket feed. You register a webhook URL and Kick POSTs signed
  event payloads to it (e.g. chat message sent, stream live/offline).
- Webhook signatures are verified — there's a debug-only flag to skip
  verification for local testing with synthetic unsigned payloads (see
  KickMCP project for reference implementation details).
- **Practical problem for a Kodi addon**: webhooks need a publicly reachable
  HTTPS endpoint. That's fine for a server-side integration, but awkward for
  code running on an end user's home network. Not solved by Tailscale, since
  Kick's servers need inbound reachability, not just the user's own devices.

---

## 2. Unofficial / undocumented surface (fills gaps, no stability guarantee)

These are things the official API does **not** currently provide, sourced
from community reverse-engineering repos. Same trust tier as how unofficial
Twitch Kodi addons use Twitch's internal GQL endpoint to get `usher.ttvnw.net`
playback URLs instead of anything in Helix.

### Playback URL (HLS/m3u8)
Not available via the official public API. Community approach:

```
GET https://kick.com/api/v2/channels/{slug}
```

Response includes (trimmed):
```json
{
  "id": 999,
  "slug": "trainwreckstv",
  "playback_url": "https://<id>.us-west-2.playback.live-video.net/api/video/v1/us-west-2.<acct>.channel.<id>.m3u8",
  "vod_enabled": true,
  "livestream": { "is_live": true, "viewer_count": ... },
  ...
}
```
- `livestream` is `null` when the channel is offline — check before trying
  to play.
- Underlying playback infra is AWS IVS (same as many other platforms) —
  standard HLS, should work fine with Kodi's inputstream adaptive handling
  once you have the m3u8 URL, same as any other IVS/HLS source.
- Some sources note a dedicated scrape helper at
  `kick.com/api/v2/channels/scrapes/playback-url` returning a signed/JWT-
  tokenized IVS URL directly — worth checking response shape before relying
  on it, token expiry (`exp` claim) means URLs are not permanently cacheable.
- Reference implementation pattern (Python, using `curl_cffi` to avoid basic
  bot-detection via TLS fingerprinting):
  ```python
  from curl_cffi import requests

  def get_playback_url(slug: str) -> str | None:
      r = requests.get(
          f"https://kick.com/api/v2/channels/{slug}",
          impersonate="chrome124",
      ).json()
      if not r.get("livestream"):
          return None  # offline
      return r["playback_url"]
  ```

### Chat
No stable public WebSocket. Kick's own site historically used **Pusher**
for chat delivery, channel pattern like `chatrooms.{id}.v2`. Reverse-
engineered by sniffing WebSocket frames via the Chrome DevTools Protocol
(see `mattseabrook/KICK.com-Streaming-REST-API`'s "KICKstand" script) —
i.e., running a headless/real browser instance and intercepting network
frames, not a clean API call. Fragile, ToS-grey, not recommended as the
primary chat path for a distributed addon.

**Recommendation:** scope chat out of v1, or mark it experimental/off-by-
default, and revisit once/if Kick's official webhook event system exposes
something more addon-friendly (e.g. a documented realtime channel rather
than inbound webhooks only).

### Community doc/endpoint dumps (for cross-referencing field names, etc.)
- `github.com/johne5s/kick-api-docs`
- `github.com/fb-sean/kick-website-endpoints`
- `github.com/mattseabrook/KICK.com-Streaming-REST-API`
- Unofficial MCP server (env-driven, useful as a reference implementation of
  OAuth + webhook signature verification): search "KickMCP" / LobeHub listing

---

## 3. Suggested module layout (mirroring an existing `twitch_client.py` pattern)

```
kick/
  __init__.py
  kick_client.py       # official API: auth, livestreams, categories, moderation
  kick_playback.py      # unofficial: resolve slug -> m3u8 playback URL
  kick_auth.py           # OAuth2.1 + PKCE flow, token storage/refresh
  kick_chat.py            # stub/experimental — flag as unsupported for v1
```

### `kick_client.py` responsibilities
- OAuth token acquisition/refresh (PKCE flow; needs a redirect handling
  strategy inside Kodi — e.g. a local loopback HTTP listener bound to
  `127.0.0.1` on a fixed port during the auth dialog, same pattern used by
  Spotify/Twitch Kodi addons that need a browser-based OAuth step)
- `get_livestreams(category_id=None, language=None, sort="viewer_count", limit=20)`
- `get_categories()`
- Response caching (short TTL, similar to the Deezer client pattern already
  used in RadioTop) to stay within undocumented rate limits

### `kick_playback.py` responsibilities
- `get_playback_url(slug) -> str | None`
- Treat failures/schema changes as expected; log and degrade gracefully
  rather than raising unhandled exceptions into the Kodi UI
- Don't cache the resolved URL beyond stream session — IVS tokens expire
  (JWT `exp` claim observed in captured responses)

---

## 4. Open questions to resolve before implementation

1. Does the official API support anonymous/app-level read access for
   livestreams+categories, or is per-user OAuth mandatory even for browsing?
   (Confirm against current `docs.kick.com`.)
2. What's Kick's current stance/rate limits on the unofficial `v2` endpoints —
   any recent blocking of `curl_cffi`-style impersonation, Cloudflare
   challenges, etc.? Worth a quick manual test before committing to the
   approach.
3. Whether chat is a hard requirement for v1 or can ship as "Kick support:
   browse + watch" first, with chat marked experimental/later.
4. Legal/ToS posture the project wants to take on the unofficial-endpoint
   dependency (same conversation you'd have already had for Twitch's GQL
   usage, if twitch-center relies on that for playback too).
5. **Unresolved conflict (found in final review of kick-provider-core):**
   `lib/kick/stream.py`'s `resolve_stream_url` currently assumes the
   official Public API's `GET /public/v1/channels` response embeds the
   playback URL inline at `channel["stream"]["url"]`. That is UNVERIFIED
   against the real official API and directly contradicts section 2 above
   ("Playback URL (HLS/m3u8)"), which found the official API does *not*
   expose a playback URL at all. If the official response really lacks it,
   the fallback is the unofficial `GET https://kick.com/api/v2/channels/{slug}`
   endpoint (`api.SEARCH_BASE + "/channels/" + slug`, already used by
   `search_channels`), reading its `playback_url` field instead. This must
   be confirmed/fixed before sub-project 4 (playback wiring) can work.
