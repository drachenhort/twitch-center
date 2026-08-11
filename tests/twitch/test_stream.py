import pytest
from lib.twitch import stream


def test_resolve_stream_url_not_implemented():
    with pytest.raises(NotImplementedError):
        stream.resolve_stream_url("some_channel")
