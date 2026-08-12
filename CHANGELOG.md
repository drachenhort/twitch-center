# Changelog

All notable changes to this project are documented here. Format loosely follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions follow the addon's own
`version` field in `addon.xml`.

## [0.6.0] - 2026-08-12

### Added
- Real stream playback via inputstream.adaptive: clicking a live channel in Home or Discover now
  plays it in Kodi's own player instead of being a no-op.
- New `script.module.inputstreamhelper` addon dependency, used to ensure inputstream.adaptive is
  installed and enabled before playback starts.

## [0.5.0] - 2026-08-11

### Added
- Discover screen: browse live streams for any game (not just followed channels) via a top-games
  row, or search any channel by name.

### Fixed
- Window navigation no longer terminates the Kodi script when opening a new screen (Home →
  Discover, or any re-login hand-off) — a shared `closed_event` now propagates through the whole
  navigation chain instead of each window prematurely signaling the script's exit.
- Focus navigation now reaches every control in the Home and Discover skins (previously some
  buttons/controls were unreachable by remote).

## [0.4.0] - 2026-08-11

### Added
- Followed-games filter row on Home: a row of your real followed live games (via Twitch's
  unofficial internal API, response shape verified against a live capture), selecting one filters
  the channel list to live followed channels playing it.

## [0.3.0] - 2026-08-11

### Added
- Home screen: followed-channels list with live channels surfaced first, thumbnails, viewer counts,
  and game names.
- Transparent access-token refresh so a session persists past Twitch's ~4-hour token expiry instead
  of forcing re-login every time.

### Fixed
- Login code display made large and centered (was barely visible).

## [0.2.0] - 2026-08-11

### Added
- Twitch device-code login flow: displays a code + verification URL, polls in the background,
  saves the resulting token.

## [0.1.0] - 2026-08-11

### Added
- Initial Kodi addon scaffold: manifest, package skeleton (auth/API/stream/chat/UI layers, all
  stubbed), pytest harness.
