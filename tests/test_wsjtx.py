"""WSJT-X UDP parsing. Datagrams are untrusted input from a local socket."""

import struct

from hammunition_hill.streams.wsjtx import MAGIC, parse_datagram


def _string(value):
    if value is None:
        return struct.pack(">I", 0xFFFFFFFF)
    encoded = value.encode()
    return struct.pack(">I", len(encoded)) + encoded


def _header(message_type, client="WSJT-X"):
    return struct.pack(">III", MAGIC, 2, message_type) + _string(client)


def decode_datagram(*, snr=-12, mode="FT8", message="CQ JA1XYZ PM95"):
    return (
        _header(2)
        + struct.pack(">?", True)
        + struct.pack(">I", 45_296_000)   # 12:34:56 in ms since midnight
        + struct.pack(">i", snr)
        + struct.pack(">d", 0.2)
        + struct.pack(">I", 1500)
        + _string(mode)
        + _string(message)
    )


def status_datagram(dial_hz=14_074_000, mode="FT8", dx_call="JA1XYZ"):
    return (
        _header(1)
        + struct.pack(">Q", dial_hz)
        + _string(mode)
        + _string(dx_call)
        + _string("-12")
        + _string(mode)
        + struct.pack(">???", True, False, True)
    )


def logged_datagram(call="JA1XYZ", grid="PM95", dial_hz=14_074_000, mode="FT8"):
    return (
        _header(5)
        + struct.pack(">Q", 0) + struct.pack(">I", 0) + struct.pack(">?", True)
        + _string(call)
        + _string(grid)
        + struct.pack(">Q", dial_hz)
        + _string(mode)
    )


# --- decodes ------------------------------------------------------------
def test_decode_is_parsed():
    parsed = parse_datagram(decode_datagram())
    assert parsed["type"] == "decode"
    assert parsed["snr"] == -12
    assert parsed["mode"] == "FT8"
    assert parsed["message"] == "CQ JA1XYZ PM95"


def test_decode_time_converts_to_utc_clock():
    assert parse_datagram(decode_datagram())["at"] == "12:34:56"


def test_positive_and_negative_snr():
    assert parse_datagram(decode_datagram(snr=-24))["snr"] == -24
    assert parse_datagram(decode_datagram(snr=6))["snr"] == 6


def test_decode_message_is_bounded():
    parsed = parse_datagram(decode_datagram(message="X" * 500))
    assert len(parsed["message"]) <= 64


# --- status -------------------------------------------------------------
def test_status_is_parsed():
    parsed = parse_datagram(status_datagram())
    assert parsed["type"] == "status"
    assert parsed["khz"] == 14074.0
    assert parsed["dx_call"] == "JA1XYZ"
    assert parsed["transmitting"] is False
    assert parsed["tx_enabled"] is True


def test_status_frequency_converts_hz_to_khz():
    assert parse_datagram(status_datagram(dial_hz=7_074_000))["khz"] == 7074.0


# --- logged QSO ---------------------------------------------------------
def test_logged_qso_is_parsed():
    parsed = parse_datagram(logged_datagram())
    assert parsed["type"] == "logged"
    assert parsed["call"] == "JA1XYZ"
    assert parsed["grid"] == "PM95"
    assert parsed["khz"] == 14074.0


# --- robustness ---------------------------------------------------------
def test_wrong_magic_is_ignored():
    bad = struct.pack(">III", 0xDEADBEEF, 2, 2) + _string("x")
    assert parse_datagram(bad) is None


def test_truncated_datagram_is_ignored():
    assert parse_datagram(decode_datagram()[:20]) is None


def test_empty_datagram_is_ignored():
    assert parse_datagram(b"") is None


def test_unhandled_message_types_are_ignored():
    """Heartbeat, clear, close, and the reply family are all deliberately unused."""
    for message_type in (0, 3, 4, 6, 99):
        assert parse_datagram(_header(message_type)) is None


def test_absurd_string_length_is_refused():
    """A length field claiming 4GB must not become an allocation."""
    hostile = _header(2) + struct.pack(">?", True) + struct.pack(">I", 0)
    hostile += struct.pack(">i", 0) + struct.pack(">d", 0.0) + struct.pack(">I", 0)
    hostile += struct.pack(">I", 0xFFFFFFF0)
    assert parse_datagram(hostile) is None


def test_null_strings_are_handled():
    """0xffffffff is Qt's null, and WSJT-X sends it for absent fields."""
    parsed = parse_datagram(status_datagram(dx_call=None))
    assert parsed["dx_call"] is None
