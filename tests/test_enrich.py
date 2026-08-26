"""Spot enrichment: entity, path, and the needed-slot join."""

import pytest

from hammunition_hill.adif import build_index
from hammunition_hill.enrich import Enricher, Station
from hammunition_hill.prefix import PrefixTable

RAW = {
    "call": "JA1XYZ",
    "spotter": "W1ABC",
    "khz": 14074.0,
    "comment": "FT8 -12 dB",
    "time": "1234",
    "mode_from_comment": "FT8",
    "spotted_at": "2026-08-26T12:34:00Z",
}


@pytest.fixture
def table():
    return PrefixTable(None)


@pytest.fixture
def enricher(table):
    return Enricher(table, Station.from_config({"callsign": "N0CALL", "grid": "FN31pr"}))


# --- station ------------------------------------------------------------
def test_station_derives_coordinates_from_grid():
    station = Station.from_config({"grid": "FN31pr"})
    assert station.located
    assert station.lat == pytest.approx(41.73, abs=0.05)


def test_explicit_coordinates_win_over_grid():
    station = Station.from_config({"grid": "FN31pr", "lat": 10.0, "lon": 20.0})
    assert (station.lat, station.lon) == (10.0, 20.0)


def test_a_bad_grid_degrades_rather_than_raising():
    """A typo in config should cost bearings, not stop the collector."""
    station = Station.from_config({"grid": "NOT-A-GRID"})
    assert not station.located


def test_no_station_at_all():
    assert not Station.from_config({}).located


# --- enrichment ---------------------------------------------------------
def test_entity_and_continent(enricher):
    spot = enricher.enrich_spot(RAW)
    assert spot["entity"] == "Japan"
    assert spot["continent"] == "AS"


def test_band_and_mode(enricher):
    spot = enricher.enrich_spot(RAW)
    assert spot["band"] == "20m"
    assert spot["mode"] == "FT8"
    assert spot["mode_inferred"] is False


def test_mode_is_inferred_when_the_comment_says_nothing(enricher):
    spot = enricher.enrich_spot({**RAW, "mode_from_comment": None})
    assert spot["mode"] == "FT8"
    assert spot["mode_inferred"] is True


def test_path_is_computed(enricher):
    """Connecticut to Japan is a long north-westerly path."""
    path = enricher.enrich_spot(RAW)["path"]
    assert path["km"] == pytest.approx(10800, rel=0.1)
    assert 300 <= path["bearing"] <= 340


def test_path_is_omitted_without_a_station(table):
    plain = Enricher(table, Station.from_config({}))
    assert plain.enrich_spot(RAW)["path"] is None


def test_unresolvable_callsign_does_not_break_a_spot(enricher):
    spot = enricher.enrich_spot({**RAW, "call": "!!!!"})
    assert spot["entity"] is None
    assert spot["path"] is None
    assert spot["call"] == "!!!!"


def test_builtin_table_flags_entities_as_approximate(enricher):
    assert enricher.enrich_spot(RAW)["entity_approximate"] is True


def test_spots_come_back_newest_first(enricher):
    """The stream appends; the panel reads top-down."""
    raws = [{**RAW, "call": "JA1AAA"}, {**RAW, "call": "JA1BBB"}]
    assert [s["call"] for s in enricher.enrich_spots(raws)] == ["JA1BBB", "JA1AAA"]


# --- the needed join ----------------------------------------------------
def test_no_needed_field_without_a_log(enricher):
    """Without a log we say nothing, rather than implying everything is new."""
    assert "needed" not in enricher.enrich_spot(RAW)


def test_needed_appears_once_a_log_is_loaded(enricher, table):
    enricher.set_log_index(build_index("<CALL:6>DL1ABC<BAND:3>20M<MODE:3>SSB<EOR>", table))
    spot = enricher.enrich_spot(RAW)
    assert spot["needed"]["new_entity"] is True


def test_worked_entity_is_not_new(enricher, table):
    enricher.set_log_index(build_index("<CALL:6>JA1ABC<BAND:3>20M<MODE:3>FT8<EOR>", table))
    needed = enricher.enrich_spot(RAW)["needed"]
    assert needed["new_entity"] is False
    assert needed["new_band"] is False


def test_band_slot_is_flagged(enricher, table):
    """Japan worked on 40m; this spot is 20m."""
    enricher.set_log_index(build_index("<CALL:6>JA1ABC<BAND:3>40M<MODE:2>CW<EOR>", table))
    needed = enricher.enrich_spot(RAW)["needed"]
    assert needed["new_entity"] is False
    assert needed["new_band"] is True


def test_reloading_the_log_swaps_the_answer(enricher, table):
    """A log reload must take effect on the next render, wholesale."""
    assert enricher.enrich_spot(RAW).get("needed") is None
    enricher.set_log_index(build_index("<CALL:6>JA1ABC<BAND:3>20M<MODE:3>FT8<EOR>", table))
    assert enricher.enrich_spot(RAW)["needed"]["new_entity"] is False
    enricher.set_log_index(None)
    assert "needed" not in enricher.enrich_spot(RAW)


# --- activations --------------------------------------------------------
def test_activation_prefers_its_own_coordinates(enricher):
    """A park has real coordinates; an entity centroid is a fallback."""
    activation = enricher.enrich_activation(
        {"call": "K1ABC", "lat": 44.0, "lon": -68.0, "khz": 14285.0, "reference": "US-0001"}
    )
    assert activation["path"]["km"] == pytest.approx(430, rel=0.15)
    assert activation["band"] == "20m"


def test_activation_falls_back_to_grid(enricher):
    activation = enricher.enrich_activation({"call": "G4ABC", "grid": "IO91wm"})
    assert activation["path"] is not None


def test_activation_falls_back_to_the_entity_centroid(enricher):
    activation = enricher.enrich_activation({"call": "VK2ABC"})
    assert activation["entity"] == "Australia"
    assert activation["path"] is not None


def test_activation_without_a_frequency_has_no_band(enricher):
    assert "band" not in enricher.enrich_activation({"call": "K1ABC"})
