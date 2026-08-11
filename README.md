# twitch-center

A media-center type solution for viewing Twitch streams. Login via Twitch, watch streams, and view
the IRC chat paired to a given streamer.

Not designed for communicating back to the streamer — more a second way to consume
streamer-generated content.

## Status

The scaffold is in place: the addon manifest (`addon.xml`) and a `lib/` package
skeleton (a `twitch/` API layer, a `windows/` UI layer, and `settings.py`) all
exist, with tests covering them. The real Twitch/network/UI logic is not yet
implemented — everything is currently stubbed. See `docs/superpowers/specs` and
`docs/superpowers/plans` for the design and implementation tracking.

## Development

```
pip install -r requirements-dev.txt && pytest
```

This runs the test suite (28 tests, all passing as of this scaffold). See
`CLAUDE.md` for current state.
