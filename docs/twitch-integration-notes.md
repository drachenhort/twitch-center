# Twitch Integration — Reference Notes for twitch-center (Kodi addon)

Companion doc to `kick-integration-notes.md`. Same format, so the two
platforms can be compared side-by-side inside your Claude Code session while
you build out parity between them.

Good news relative to Kick: Twitch's **chat** story is officially solved via
EventSub over WebSocket — no public HTTPS endpoint required, which was the
structural blocker on the Kick side. Playback is still the same unofficial-
GQL situation Kick has, though.

---

## 1. Official API (Helix)

- Dev console (app registration): `https://dev.twitch.tv/console`
- API base: `https://api.twitch.tv/helix/...`
- Docs: `https://dev.twitch.tv/docs/api/reference`
- Auth docs: `https://dev.twitch.tv/docs/authentication/`

### Auth: two token types
- **App access token** (client credentials flow) — no user login required.
  Covers most read-only public endpoints: `Get Streams`, `Get Users`,
  `Get Games`/categories, `Search Categories`, `Get Clips`, `Get Videos`.
  This is the one that gives you Twitch-style "browse without login."
- **User access token** (OAuth authorization code flow) — needed for
  anything scoped to a specific user's data/actions (follows, chat sending,
  moderation, polls, etc.). Register redirect URI in the dev console
  (`http://localhost:<port>` works fine for a local-loopback flow, same
  pattern you'll use for Kick's PKCE flow).
- Every request needs both the Bearer token **and** a `Client-Id` header —
  don't forget the second one, it's easy to miss coming from single-header
  auth schemes.

Example:
```
GET https://api.twitch.tv/helix/streams?first=10
Authorization: Bearer <app_or_user_token>
Client-Id: <your_client_id>
```

### Key read endpoints for a "browse" UI
- `GET /helix/streams` — live streams, filterable by `game_id`, `language`,
  `user_login`, etc. Works with an app access token.
- `GET /helix/games` / `GET /helix/search/categories` — category browsing.
- `GET /helix/users` — resolve login → user_id and vice versa.
- `GET /helix/clips`, `GET /helix/videos` — clips/VODs metadata.

### Chat sending / moderation (if you want it)
- `POST /helix/chat/messages` — send chat messages via API (replaces IRC's
  `chat:edit` scope with `user:write:chat`, plus `user:bot` and either
  `channel:bot` or moderator status if using an app access token on behalf
  of a bot account).
- Moderation endpoints (ban/timeout/etc.) exist under `/helix/moderation/...`
  similar in spirit to Kick's `/moderation/bans`.

---

## 2. Chat: EventSub over WebSocket (this is the good part)

Twitch has been actively steering people off IRC and legacy PubSub onto
**EventSub**, and for a desktop/local client like a Kodi addon, the
**WebSocket transport** is the one that matters — it's a persistent client-
initiated connection, so unlike webhooks (or Kick's whole real-time story)
you don't need a public HTTPS endpoint.

- Docs: `https://dev.twitch.tv/docs/eventsub/`
- Chat-specific guide: `https://dev.twitch.tv/docs/chat/send-receive-messages/`
- IRC → EventSub migration guide: `https://dev.twitch.tv/docs/chat/irc-migration/`

### Flow
1. Open a WebSocket connection to Twitch's EventSub WebSocket server →
   receive a `session_id` in the welcome message.
2. Create a `channel.chat.message` subscription via the Helix API, passing
   that `session_id` as the transport and the target `broadcaster_user_id` /
   `user_id` (the "reading as" identity) as condition.
3. Messages stream in as JSON notifications over the same socket — includes
   text, fragments (emotes/mentions/cheermotes parsed out), badges, color,
   message type, etc. Much easier to parse than raw IRC.
4. Server sends a `Reconnect` message with a new URL before restarting your
   connection — handle that to avoid dropped subscriptions.

### Scopes
- Minimum: `user:read:chat` from the chatting/reading identity.
- If using an app access token instead of a user token: also need
  `user:bot` from that identity, plus either `channel:bot` scope from the
  broadcaster or moderator status in that channel.

### Concurrent join limits
- Joining chat only happens when you subscribe to `channel.chat.message`
  (or `JOIN` on legacy IRC). Joining as broadcaster/moderator, or after
  being authorized via `channel:bot`, doesn't count against your global
  concurrent join limit — relevant if the addon lets a user watch many
  channels' chat at once.

### Legacy IRC (still works, not recommended for new builds)
- `irc.chat.twitch.tv` — standard IRC connection, `chat:read`/`chat:edit`
  scopes. Twitch's own docs now recommend EventSub over IRC going forward
  and note IRC is getting tighter limits over time. Only worth using if you
  want one code path that also covers older reference implementations, but
  for a fresh addon, build on EventSub directly.

**Bottom line:** unlike Kick, chat is a fully legitimate, officially
supported feature to ship at parity — no scraping, no fragile browser
automation required.

---

## 3. Playback URL — still unofficial (same tier as Kick)

Helix does **not** expose a stream playback URL. This is the same situation
as Kick's `v2/channels/{slug}` endpoint — you're relying on the internal
GraphQL API that the Twitch website itself uses, not anything documented or
supported.

- GQL endpoint: `https://gql.twitch.tv/gql`
- Explicitly labeled unofficial by community wrappers: <cite>"The GraphQL
  API is as unofficial as it can be. It only works by emulating the twitch
  website (clientId and accessToken matching the clientId of the twitch
  site itself)"</cite> — i.e. you use Twitch's own public web client ID
  (commonly seen as `kimne78kx3ncx6brgo4mv6wki5h1ko` in community tools),
  not your registered app's client ID.
- Flow: query GQL for a `PlaybackAccessToken` (signature + token) for the
  channel login → request the HLS master playlist from Usher:
  ```
  https://usher.ttvnw.net/api/channel/hls/<channel>.m3u8?sig=<sig>&token=<token>&allowsource=true
  ```
- VOD equivalent uses `/vod/<id>.m3u8` with its own accesstoken call.
- Response gives a master playlist with variant streams (resolution,
  framerate, bandwidth) via `video-weaver.*.hls.ttvnw.net` — parse with an
  m3u8 library same as you'd do for Kick's IVS playlist.
- Same caveats as Kick: treat as best-effort, expect occasional breakage,
  don't hardcode assumptions about token lifetime.
- Note: some regions/ISPs have had ad-injection or quality-throttling
  behavior tied to this endpoint historically (see community proxy/relay
  projects like `ttv.lol` or region-specific quality proxies) — not
  something you need to solve, just be aware it's a known rough edge if
  users report quality issues that aren't your addon's fault.

---

## 4. Suggested module layout (mirrors the Kick structure)

```
twitch/
  __init__.py
  twitch_client.py     # official Helix: auth, streams, categories, users
  twitch_playback.py   # unofficial: GQL PlaybackAccessToken -> usher m3u8
  twitch_auth.py        # app access token + user OAuth (authorization code)
  twitch_chat.py          # EventSub WebSocket client — officially supported
```

### `twitch_client.py`
- App access token acquisition (client credentials — no user interaction,
  use this as the default for anonymous browsing)
- User OAuth flow (loopback redirect, same UX pattern as the Kick PKCE flow)
  for anything requiring a logged-in identity
- `get_streams(...)`, `get_categories()`, `get_users(...)`
- Remember the `Client-Id` header on every call, in addition to Bearer auth

### `twitch_playback.py`
- `get_playback_url(channel_login) -> str | None`
- Uses the public web client ID for the GQL call, not your registered
  Helix client ID
- Same "don't cache beyond session, expect breakage" posture as Kick

### `twitch_chat.py`
- WebSocket connection lifecycle (connect → welcome → session_id →
  subscribe via Helix → stream notifications → handle `Reconnect`)
- This can genuinely ship as a first-class, non-experimental feature —
  unlike Kick chat, there's no structural reachability problem

---

## 5. Kick vs. Twitch — quick comparison for parity planning

| Feature | Twitch | Kick |
|---|---|---|
| Anonymous browsing | Yes — app access token | Unclear, verify per docs.kick.com |
| Live streams / categories | Official (Helix) | Official (`/public/v1/livestreams`) |
| Playback URL | Unofficial (GQL + Usher) | Unofficial (`v2/channels/{slug}`) |
| Chat (receive) | Official — EventSub WebSocket | Unofficial (Pusher, reverse-engineered) |
| Chat (send) / moderation | Official (Helix) | Official (`/public/v1/moderation/bans`) |
| Real-time transport | WebSocket (client-initiated, no public endpoint needed) | Webhook (requires public HTTPS endpoint) |

The practical implication: **your chat UX will likely be better on Twitch
than Kick** for the foreseeable future, unless Kick ships a WebSocket-based
event transport to match. Worth setting expectations in the addon's docs/UI
if Kick chat ships as a reduced-feature or experimental tier.
