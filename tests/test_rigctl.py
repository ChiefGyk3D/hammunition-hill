# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""rigctld reply parsing. Read-only by design -- there is no set path to test."""

from hammunition_hill.streams import STREAM_KINDS, build_stream, is_stream
from hammunition_hill.streams.rigctl import RigctlStream, parse_state


def test_frequency_converts_hz_to_khz():
    state = parse_state(["14074000"], ["USB", "2400"])
    assert state["khz"] == 14074.0
    assert state["band"] == "20m"


def test_mode_and_passband():
    state = parse_state(["7074000"], ["PKTUSB", "3000"])
    assert state["mode"] == "PKTUSB"
    assert state["passband_hz"] == 3000


def test_out_of_band_frequency_has_no_band():
    assert parse_state(["12345000"], ["USB", "2400"])["band"] is None


def test_missing_replies_degrade_to_none():
    state = parse_state([], [])
    assert state == {"khz": None, "band": None, "mode": None, "passband_hz": None}


def test_unparseable_frequency_is_none():
    assert parse_state(["not-a-number"], ["USB"])["khz"] is None


def test_unparseable_passband_is_none():
    assert parse_state(["14074000"], ["USB", "wide"])["passband_hz"] is None


def test_mode_only_reply():
    state = parse_state(["14074000"], ["CW"])
    assert state["mode"] == "CW"
    assert state["passband_hz"] is None


# --- registry -----------------------------------------------------------
def test_stream_kinds_registered():
    assert set(STREAM_KINDS) == {"dxcluster", "wsjtx", "rigctl", "gpsd", "nmea"}


def test_is_stream():
    assert is_stream("dxcluster")
    assert not is_stream("hamqsl")


def test_build_stream_returns_a_fresh_instance():
    """Streams hold per-connection state, so they must not be shared."""
    assert build_stream("rigctl") is not build_stream("rigctl")
    assert isinstance(build_stream("rigctl"), RigctlStream)


def test_unknown_stream_kind_is_an_error():
    import pytest

    with pytest.raises(ValueError, match="unknown stream kind"):
        build_stream("nonsense")


def test_rigctl_exposes_no_set_commands():
    """A dashboard must never be able to key a transmitter.

    The guarantee is structural: there is no method that sends anything but the
    two get commands. This test fails loudly if one is ever added.
    """
    import inspect

    from hammunition_hill.streams import rigctl

    source = inspect.getsource(rigctl)
    for forbidden in ('"F "', '"M "', '"T 1"', "set_freq", "set_mode", "set_ptt"):
        assert forbidden not in source, f"rigctl gained a write path: {forbidden}"
