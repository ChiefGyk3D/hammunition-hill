"""DX cluster line parsing. Cluster output is untrusted, noisy, and inconsistent."""

import pytest

from hammunition_hill.streams.cluster import parse_spot_line

REAL_LINES = [
    "DX de W1ABC:     14074.0  JA1XYZ       FT8 -12 dB               1234Z",
    "DX de EA5ABC-#:   7023.5  VP8ABC       CW 599                   0812Z",
    "DX de VE3XYZ:    21295.0  ZS6ABC       SSB loud                 1530Z",
    "DX de DL1ABC:  144174.0  G4XYZ        FT8                      2001Z",
]


@pytest.mark.parametrize("line", REAL_LINES)
def test_real_lines_parse(line):
    assert parse_spot_line(line) is not None


def test_fields_extracted():
    spot = parse_spot_line(REAL_LINES[0])
    assert spot["spotter"] == "W1ABC"
    assert spot["khz"] == 14074.0
    assert spot["call"] == "JA1XYZ"
    assert spot["time"] == "1234"
    assert "FT8" in spot["comment"]


def test_mode_is_lifted_from_the_comment():
    """A mode the spotter typed beats anything we could infer from frequency."""
    assert parse_spot_line(REAL_LINES[1])["mode_from_comment"] == "CW"
    assert parse_spot_line(REAL_LINES[2])["mode_from_comment"] == "SSB"


def test_no_mode_word_means_no_claim():
    spot = parse_spot_line("DX de W1ABC:     14025.0  JA1XYZ       up 2               1234Z")
    assert spot["mode_from_comment"] is None


def test_spotter_with_ssid_is_kept():
    assert parse_spot_line(REAL_LINES[1])["spotter"] == "EA5ABC-#"


@pytest.mark.parametrize("line", [
    "",
    "Hello and welcome to the cluster",
    "WWV de VE7CC <18Z> : SFI=168, A=7, K=3",
    "To ALL de W1ABC: anyone on 20m?",
    ">>> W1ABC has left the cluster",
])
def test_non_spot_traffic_is_dropped(line):
    """Clusters emit chat, bulletins, and announcements. None of it is a spot."""
    assert parse_spot_line(line) is None


def test_absurd_frequencies_are_rejected():
    assert parse_spot_line("DX de W1ABC:     0.5  JA1XYZ   x   1234Z") is None
    assert parse_spot_line("DX de W1ABC:  99999999.0  JA1XYZ   x   1234Z") is None


def test_comment_is_bounded():
    """A hostile node must not be able to push a megabyte into a snapshot."""
    line = f"DX de W1ABC:     14074.0  JA1XYZ   {'A' * 5000}   1234Z"
    spot = parse_spot_line(line)
    assert spot is not None
    assert len(spot["comment"]) <= 60


def test_lowercase_input_is_normalized():
    spot = parse_spot_line("dx de w1abc:     14074.0  ja1xyz       ft8      1234Z")
    assert spot["call"] == "JA1XYZ"
    assert spot["spotter"] == "W1ABC"


def test_spotted_at_is_stamped_locally():
    """The cluster's own time field is four digits with no date; ours is real."""
    spot = parse_spot_line(REAL_LINES[0])
    assert spot["spotted_at"].endswith("Z")
