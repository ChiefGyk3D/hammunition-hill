"""The egress guard is the security core. These are the tests that matter most."""

import pytest

from hammunition_hill.egress import EgressDenied, EgressGuard

PUBLIC = "93.184.216.34"


def guard(allowed=(), local=()):
    return EgressGuard.build(set(allowed), set(local))


def test_host_not_in_allowlist_is_denied():
    with pytest.raises(EgressDenied, match="not in the egress allowlist"):
        guard(["services.swpc.noaa.gov"]).check("https://evil.example/x")


def test_allowlist_is_closed_by_default():
    with pytest.raises(EgressDenied):
        guard().check("https://www.hamqsl.com/solarxml.php")


@pytest.mark.parametrize("scheme", ["file", "ftp", "gopher", "data", "javascript"])
def test_non_http_schemes_are_refused(scheme):
    with pytest.raises(EgressDenied, match="not http or https"):
        guard(["example.com"]).check(f"{scheme}://example.com/x")


@pytest.mark.parametrize(
    "addr",
    ["127.0.0.1", "10.1.2.3", "192.168.1.50", "172.16.0.1", "169.254.169.254", "::1", "0.0.0.0"],
)
def test_private_and_reserved_addresses_are_refused(addr):
    """A mistyped or hijacked upstream must not become a LAN probe.

    169.254.169.254 is in here on purpose: it is the cloud metadata endpoint,
    and it is the single most valuable SSRF target there is.
    """
    host = f"[{addr}]" if ":" in addr else addr
    with pytest.raises(EgressDenied, match="private, loopback, or reserved"):
        guard([addr]).check(f"http://{host}/status")


def test_local_flag_opts_a_host_back_in():
    """Pi-Star and OpenWebRX are legitimate LAN targets -- but only explicitly."""
    g = guard(["192.168.1.50"], local=["192.168.1.50"])
    assert g.check("http://192.168.1.50/") == "192.168.1.50"


def test_public_address_passes():
    assert guard([PUBLIC]).check(f"https://{PUBLIC}/feed") == PUBLIC


def test_all_resolved_addresses_are_checked(monkeypatch):
    """Partial trust is not trust: one bad address poisons the host."""
    monkeypatch.setattr(
        "hammunition_hill.egress.resolve_all", lambda host: [PUBLIC, "10.0.0.7"]
    )
    with pytest.raises(EgressDenied, match="10.0.0.7"):
        guard(["split.example"]).check("https://split.example/")


def test_hostname_resolving_public_is_allowed(monkeypatch):
    monkeypatch.setattr("hammunition_hill.egress.resolve_all", lambda host: [PUBLIC])
    url = "https://www.hamqsl.com/solarxml.php"
    assert guard(["www.hamqsl.com"]).check(url) == "www.hamqsl.com"


def test_hostnames_are_normalized():
    """Case and the trailing root dot must not be a way around the allowlist."""
    g = guard([PUBLIC])
    assert g.check(f"https://{PUBLIC}./x") == PUBLIC


def test_missing_hostname_is_denied():
    with pytest.raises(EgressDenied, match="no hostname"):
        guard(["example.com"]).check("https:///path")
