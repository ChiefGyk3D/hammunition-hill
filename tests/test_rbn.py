# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""RBN: the parser, the tally, and the claim that neither grows with traffic.

The Reverse Beacon Network emits several thousand spots a minute. The module's
central design claim is that nothing it keeps grows with that -- watched spots
are capped, and everything else collapses into a per-band, per-mode tally
bounded by the band plan.

A claim about memory is worth nothing unless it is measured, so the tests below
push a hundred thousand spots through and check what is left. That is the same
lesson the FCC ULS importer taught this project: its docstring claimed bounded
memory while the first version would have needed most of a gigabyte.

There is also a stream-level test here, driving the read loop with a real
StreamReader fed from memory. Nothing in this repository tested a stream client
above its line parser before -- a refactor that pulled a method out of the
cluster class entirely left all seventeen of its tests passing.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import pytest

from hammunition_hill.streams.rbn import (
    DEFAULT_WINDOW_SECONDS,
    MAX_WATCHED,
    RbnStream,
    _Tally,
    parse_rbn_line,
)

# Real-shaped lines from the CW feed and the digital feed.
LINES = [
    "DX de W3LPL-#:   14025.0  DL1ABC         CW    23 dB  28 WPM  CQ      1234Z",
    "DX de VE7CC-#:    7030.5  K1ABC          CW    12 dB  25 WPM  CQ      1235Z",
    "DX de DL8LAS-#:  14074.0  JA1XYZ         FT8   -8 dB  15 WPM  CQ      1236Z",
    "DX de KM3T-#:    21023.4  G0ABC          CW     6 dB  22 WPM  DX      1237Z",
    "DX de EA5WU-#:    3573.0  VK2DEF         FT8  -21 dB  15 WPM  CQ      1238Z",
]


# --- the parser -------------------------------------------------------------


@pytest.mark.parametrize("line", LINES)
def test_real_lines_parse(line):
    assert parse_rbn_line(line) is not None


def test_every_structured_field_is_extracted():
    """The structure is the whole reason this is not the cluster parser."""
    spot = parse_rbn_line(LINES[0])
    assert spot["spotter"] == "W3LPL-#"
    assert spot["khz"] == 14025.0
    assert spot["call"] == "DL1ABC"
    assert spot["band"] == "20m"
    assert spot["mode"] == "CW"
    assert spot["snr_db"] == 23
    assert spot["wpm"] == 28
    assert spot["kind"] == "CQ"
    assert spot["time"] == "1234"


def test_a_negative_snr_keeps_its_sign():
    """A weak digital decode is the common case, and dropping the minus would
    turn the worst signal on the band into the best."""
    assert parse_rbn_line(LINES[2])["snr_db"] == -8
    assert parse_rbn_line(LINES[4])["snr_db"] == -21


def test_the_band_comes_from_the_band_plan_not_the_line():
    """RBN does not send a band, and inferring it here rather than in the panel
    means one implementation of the band edges."""
    assert parse_rbn_line(LINES[1])["band"] == "40m"
    assert parse_rbn_line(LINES[3])["band"] == "15m"
    assert parse_rbn_line(LINES[4])["band"] == "80m"


def test_a_plain_cluster_spot_is_not_an_rbn_spot():
    """The cluster feed has a free-text comment where this expects dB and WPM.
    Accepting it would invent an SNR."""
    assert parse_rbn_line("DX de W1ABC:  14074.0  JA1XYZ  FT8 -12 dB   1234Z") is None


@pytest.mark.parametrize(
    "line",
    [
        "",
        "   ",
        "Please enter your call:",
        "WWV de W0MU <18Z> : SFI=142, A=8, K=2",
        "DX de W3LPL-#:   14025.0  DL1ABC  CW  23 dB  28 WPM",  # no time
        "DX de W3LPL-#:   14025.0  DL1ABC  CW  dB  28 WPM  CQ  1234Z",  # no number
        "not a spot at all",
    ],
)
def test_non_spot_traffic_is_dropped(line):
    assert parse_rbn_line(line) is None


def test_an_absurd_frequency_is_rejected():
    assert parse_rbn_line(LINES[0].replace("14025.0", "999999999")) is None


@pytest.mark.parametrize("snr", ["95", "-55"])
def test_an_absurd_snr_is_rejected(snr):
    """A skimmer reporting +95 dB has a fault, and so would any average that
    included it."""
    assert parse_rbn_line(LINES[0].replace(" 23 dB", f" {snr} dB")) is None


def test_lowercase_input_is_normalised():
    spot = parse_rbn_line(LINES[0].lower())
    assert spot["call"] == "DL1ABC"
    assert spot["mode"] == "CW"
    assert spot["spotter"] == "W3LPL-#"


def test_the_digital_feed_speed_unit_is_accepted():
    """The FT8 feed reports BPS where the CW feed reports WPM."""
    spot = parse_rbn_line(LINES[2].replace("WPM", "BPS"))
    assert spot is not None
    assert spot["wpm"] == 15


def test_spotted_at_is_stamped_locally():
    """The four-digit time on the wire has no date and no year. The panel needs
    to know how old a spot is, so arrival is recorded here."""
    spot = parse_rbn_line(LINES[0])
    assert spot["spotted_at"].endswith("Z")
    stamped = datetime.fromisoformat(spot["spotted_at"].replace("Z", "+00:00"))
    assert abs((datetime.now(UTC) - stamped).total_seconds()) < 5


# --- the tally --------------------------------------------------------------


def spot(call="DL1ABC", spotter="W3LPL-#", band="20m", mode="CW", snr=20):
    return {"call": call, "spotter": spotter, "band": band, "mode": mode, "snr_db": snr}


def test_a_tally_counts_spots_calls_and_skimmers_separately():
    """Fifty spots of one station is a different fact from fifty stations."""
    tally = _Tally(600)
    now = datetime.now(UTC)
    for index in range(50):
        tally.add(spot(call="DL1ABC", spotter=f"SK{index}-#"), now)
    row = tally.to_list()[0]
    assert row["spots"] == 50
    assert row["calls"] == 1
    assert row["spotters"] == 50


def test_bands_and_modes_are_separate_buckets():
    tally = _Tally(600)
    now = datetime.now(UTC)
    tally.add(spot(band="20m", mode="CW"), now)
    tally.add(spot(band="20m", mode="FT8"), now)
    tally.add(spot(band="40m", mode="CW"), now)
    assert len(tally.to_list()) == 3


def test_the_busiest_band_comes_first():
    """The panel shows this in order, so the order is the answer."""
    tally = _Tally(600)
    now = datetime.now(UTC)
    for _ in range(5):
        tally.add(spot(band="40m"), now)
    for _ in range(30):
        tally.add(spot(band="20m"), now)
    assert [row["band"] for row in tally.to_list()][0] == "20m"


def test_the_best_signal_and_who_it_was_are_kept():
    tally = _Tally(600)
    now = datetime.now(UTC)
    tally.add(spot(call="WEAK", snr=3), now)
    tally.add(spot(call="LOUD", snr=41), now)
    tally.add(spot(call="MIDDLING", snr=17), now)
    row = tally.to_list()[0]
    assert row["best_snr"] == 41
    assert row["best_call"] == "LOUD"


def test_a_spot_on_no_recognised_band_is_dropped_rather_than_bucketed_as_none():
    tally = _Tally(600)
    tally.add(spot(band=None), datetime.now(UTC))
    assert tally.to_list() == []
    assert tally.total == 0


def test_a_band_that_went_quiet_expires():
    tally = _Tally(60)
    old = datetime.now(UTC) - timedelta(seconds=300)
    tally.add(spot(band="10m"), old)
    tally.add(spot(band="20m"), datetime.now(UTC))
    tally.expire(datetime.now(UTC))
    assert [row["band"] for row in tally.to_list()] == ["20m"]


def test_expiry_corrects_the_total_rather_than_leaving_it_high():
    tally = _Tally(60)
    old = datetime.now(UTC) - timedelta(seconds=300)
    for _ in range(10):
        tally.add(spot(band="10m"), old)
    tally.add(spot(band="20m"), datetime.now(UTC))
    assert tally.total == 11
    tally.expire(datetime.now(UTC))
    assert tally.total == 1


def test_a_recent_spot_keeps_a_bucket_alive():
    tally = _Tally(60)
    tally.add(spot(band="10m"), datetime.now(UTC) - timedelta(seconds=300))
    tally.add(spot(band="10m"), datetime.now(UTC))
    tally.expire(datetime.now(UTC))
    assert len(tally.to_list()) == 1


# --- the claim that this does not grow --------------------------------------


def test_a_hundred_thousand_spots_leave_a_bounded_tally():
    """The design claim, measured.

    A busy evening is thousands of spots a minute. If anything here scaled with
    that, a Pi would run out of memory overnight -- and the docstring would go
    on saying it did not, which is how the ULS importer nearly shipped needing
    620 MB.
    """
    tally = _Tally(600)
    now = datetime.now(UTC)
    bands = ["160m", "80m", "40m", "30m", "20m", "17m", "15m", "12m", "10m", "6m"]
    modes = ["CW", "FT8", "FT4", "RTTY"]
    for index in range(100_000):
        tally.add(
            spot(
                call=f"CALL{index}",
                spotter=f"SK{index}-#",
                band=bands[index % len(bands)],
                # Divided, not modulo: index % 10 and index % 4 share a factor,
                # so only twenty of the forty combinations would ever appear and
                # the bound below would be tested against half a table.
                mode=modes[(index // len(bands)) % len(modes)],
            ),
            now,
        )

    rows = tally.to_list()
    assert len(rows) == len(bands) * len(modes), "buckets grew beyond band x mode"
    assert len(rows) < 100, "whatever the band plan, this stays a table not a log"
    assert tally.total == 100_000, "the count is still right"

    # The identifier sets are the only per-spot thing retained, and they are
    # capped. Without the cap this would be a hundred thousand strings.
    #
    # Both bounds, deliberately. Checking only against MAX_TRACKED makes the
    # test vacuous under exactly the change it exists to catch -- raise the
    # constant to ten million and it still passes. The absolute number is the
    # claim: a table, not a log.
    for bucket in tally.buckets.values():
        assert len(bucket["calls"]) <= _Tally.MAX_TRACKED
        assert len(bucket["spotters"]) <= _Tally.MAX_TRACKED
        assert len(bucket["calls"]) <= 2_000, "the identifier sets are not bounded in practice"
        assert len(bucket["spotters"]) <= 2_000


def test_the_watch_list_is_capped():
    """A contest hour of your own callsign is history, not a dashboard."""
    stream = RbnStream()
    for index in range(MAX_WATCHED * 3):
        stream.watched.append(spot(call=f"X{index}"))
    assert len(stream.watched) == MAX_WATCHED


# --- the stream itself ------------------------------------------------------


async def drive(stream, lines, *, watch, flush_seconds=0.01):
    """Run the read loop over a canned transcript and return what it emitted.

    A real StreamReader fed from memory, so this exercises the actual loop --
    the readuntil, the timeouts, the flush timer -- rather than a stand-in for
    it. `feed_eof` makes the loop return cleanly the way a closed peer does.
    """
    reader = asyncio.StreamReader()
    for line in lines:
        reader.feed_data((line + "\n").encode())
    reader.feed_eof()

    emitted = []

    async def emit(payload):
        emitted.append(payload)

    cfg = type("Cfg", (), {"id": "rbn", "options": {"flush_seconds": flush_seconds}})()
    await stream._read(reader, cfg, emit, watch, DEFAULT_WINDOW_SECONDS)
    # The loop flushes on a timer, so a short transcript may end before one is
    # due. The payload is what matters, and it is complete either way.
    return emitted, stream.payload(watch, DEFAULT_WINDOW_SECONDS)


async def test_the_read_loop_tallies_what_it_reads():
    stream = RbnStream()
    _, payload = await drive(stream, LINES, watch=set())
    assert payload["spots_in_window"] == len(LINES)
    assert {row["band"] for row in payload["activity"]} == {"20m", "40m", "15m", "80m"}


async def test_a_watched_callsign_is_kept_and_others_are_not():
    """The feature: who is hearing me."""
    stream = RbnStream()
    _, payload = await drive(stream, LINES, watch={"K1ABC"})
    assert [item["call"] for item in payload["heard_me"]] == ["K1ABC"]
    assert payload["heard_me"][0]["snr_db"] == 12
    assert payload["heard_me"][0]["spotter"] == "VE7CC-#"


async def test_watched_spots_come_back_newest_first():
    """A panel reads down from the top, so the newest report belongs there."""
    stream = RbnStream()
    lines = [LINES[1].replace("12 dB", f"{n} dB") for n in (5, 15, 25)]
    _, payload = await drive(stream, lines, watch={"K1ABC"})
    assert [item["snr_db"] for item in payload["heard_me"]] == [25, 15, 5]


async def test_a_watched_spot_is_also_counted_in_the_activity():
    """It is a real decode on a real band, so excluding it would understate the
    band it was heard on."""
    stream = RbnStream()
    _, payload = await drive(stream, LINES, watch={"K1ABC"})
    assert payload["spots_in_window"] == len(LINES)


async def test_non_spot_traffic_in_the_transcript_changes_nothing():
    stream = RbnStream()
    noise = ["Please enter your call:", "", "Hello and welcome", "WWV de W0MU: SFI=142"]
    _, payload = await drive(stream, noise + LINES, watch=set())
    assert payload["spots_in_window"] == len(LINES)


async def test_a_clean_close_ends_the_loop_rather_than_hanging():
    """feed_eof with nothing pending is a peer that hung up politely."""
    stream = RbnStream()
    await asyncio.wait_for(drive(stream, [], watch=set()), timeout=5)


async def test_the_payload_reports_what_it_is_watching():
    stream = RbnStream()
    _, payload = await drive(stream, LINES, watch={"K1ABC", "N0CALL"})
    assert payload["watching"] == ["K1ABC", "N0CALL"]
    assert payload["window_seconds"] == DEFAULT_WINDOW_SECONDS


async def test_the_loop_emits_on_its_timer():
    """Emitting per spot would be thousands of snapshot writes a minute."""
    stream = RbnStream()
    emitted, _ = await drive(stream, LINES * 20, watch=set(), flush_seconds=0.1)
    assert len(emitted) < len(LINES) * 20, "the loop emitted per spot"


async def test_a_zero_flush_interval_does_not_spin_forever():
    """asyncio.wait_for with a timeout of zero never lets the read start, so the
    loop turns forever without consuming a byte -- a config typo that costs a
    core. Found by writing the test above with flush_seconds=0 and watching the
    suite hang.
    """
    stream = RbnStream()
    await asyncio.wait_for(drive(stream, LINES, watch=set(), flush_seconds=0.0), timeout=10)


async def test_a_negative_flush_interval_does_not_spin_either():
    stream = RbnStream()
    await asyncio.wait_for(drive(stream, LINES, watch=set(), flush_seconds=-5), timeout=10)


def test_rbn_needs_a_callsign_rather_than_connecting_anonymously():
    """The network requires a login, so failing here is better than failing at
    a socket with a message nobody can act on."""
    stream = RbnStream()
    cfg = type("Cfg", (), {"id": "rbn", "url": "telnet://x:7000", "options": {}})()
    with pytest.raises(ValueError, match="needs options.callsign"):
        asyncio.run(stream.run(cfg, None))
