"""The Host header parser behind the H-02 check (B34)."""

import pytest

from harness.api.hosts import host_allowed


@pytest.mark.parametrize(
    "host",
    [
        "evil.example#.ts.net",
        "127.0.0.1:8765@evil.example",
        "localhost:8765/x",
        "localhost:port",
        "localhost:",
        "[::1]evil",
        "[::1]:8765:1",
        "mac.ts.net evil",
        "mac_x.ts.net",
    ],
)
def test_malformed_hosts_are_refused(host: str) -> None:
    """Only a name or an IPv6 literal, then an optional numeric port."""
    assert host_allowed(host, ["*.example"]) is False


def test_a_bracketed_ipv6_name_can_be_allowed() -> None:
    assert host_allowed("[fd7a:115c:a1e0::1]:443", ["[fd7a:115c:a1e0::1]"]) is True
