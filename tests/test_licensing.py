# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Guessing a licence class from US callsign format.

The asymmetry that matters: a Group A call proves the holder is an Extra,
because nobody else may hold one. Every other format is a floor, because vanity
lets you take a call from any group at or below your own.
"""

import pytest

from hammunition_hill.enrich import Station
from hammunition_hill.licensing import guess_class
from hammunition_hill.prefix import PrefixTable


@pytest.fixture(scope="module")
def table():
    return PrefixTable(None)


# --- Group A: the only certain case -------------------------------------
@pytest.mark.parametrize("call", ["W1AW", "K1AB", "N7XY", "W6QQ"])
def test_one_by_two_is_certainly_extra(call, table):
    guess = guess_class(call, table)
    assert guess.klass == "extra"
    assert guess.certain is True
    assert guess.group == "A"


@pytest.mark.parametrize("call", ["KA1B", "NW7X", "WB2Q", "AA1B"])
def test_two_by_one_is_certainly_extra(call, table):
    guess = guess_class(call, table)
    assert guess.klass == "extra"
    assert guess.certain is True


@pytest.mark.parametrize("call", ["AA1AB", "AL7ZZ", "AK4XY", "AC9QQ"])
def test_two_by_two_with_an_a_prefix_is_certainly_extra(call, table):
    """AA-AL 2x2 is Group A; KA-WZ 2x2 is not. The first letter decides."""
    guess = guess_class(call, table)
    assert guess.klass == "extra"
    assert guess.certain is True


# --- everything else is a floor -----------------------------------------
@pytest.mark.parametrize("call", ["KB1AB", "WA6XY", "NZ9QQ"])
def test_two_by_two_without_an_a_prefix_guesses_advanced(call, table):
    guess = guess_class(call, table)
    assert guess.klass == "advanced"
    assert guess.certain is False


@pytest.mark.parametrize("call", ["K1ABC", "W6XYZ", "N0QQQ"])
def test_one_by_three_guesses_general(call, table):
    guess = guess_class(call, table)
    assert guess.klass == "general"
    assert guess.certain is False


@pytest.mark.parametrize("call", ["KE8ABC", "WB2CDE", "NA4XYZ"])
def test_two_by_three_guesses_technician(call, table):
    guess = guess_class(call, table)
    assert guess.klass == "technician"
    assert guess.certain is False


def test_uncertain_guesses_say_why(table):
    """The reason string is shown to the operator, so it must be honest."""
    assert "vanity" in guess_class("KE8ABC", table).reason
    assert "only an Amateur Extra" in guess_class("W1AW", table).reason


# --- refusing to guess ---------------------------------------------------
@pytest.mark.parametrize("call", ["DL1ABC", "JA1XYZ", "G0ABC", "VK2ABC", "PY2ABC"])
def test_non_us_callsigns_get_no_guess(call, table):
    """Other countries encode nothing about class. Silence beats a wrong guess."""
    assert guess_class(call, table) is None


@pytest.mark.parametrize("call", ["VE3ABC", "VK2ABC", "AP2ABC", "AT1ABC"])
def test_non_us_prefixes_fail_the_shape_check(call, table):
    """The shape check alone rejects these -- V, and A followed by M-Z, are not US.

    ITU allocates K*, N*, W*, and AAA-ALZ to the United States, so in practice
    almost nothing foreign gets past the format test. The entity lookup below is
    a second layer rather than the load-bearing one.
    """
    assert guess_class(call, None) is None


@pytest.mark.parametrize("junk", ["", "   ", "!!!", "12345", "K", "TOOLONGCALL"])
def test_junk_gets_no_guess(junk, table):
    assert guess_class(junk, table) is None


def test_portable_designators_are_stripped(table):
    """W1AW/4 is still W1AW, and still an Extra call."""
    assert guess_class("W1AW/4", table).klass == "extra"
    assert guess_class("W1AW/P", table).klass == "extra"


def test_a_foreign_prefix_qualifier_defeats_the_guess(table):
    """DL/W1AW is operating in Germany; the base call is now DL."""
    assert guess_class("DL/W1AW", table) is None


def test_lowercase_is_accepted(table):
    assert guess_class("w1aw", table).klass == "extra"


def test_the_entity_check_catches_what_the_shape_check_cannot(monkeypatch, table):
    """Defence in depth: if a US-shaped prefix were ever reassigned, the table wins.

    Simulated rather than found in the wild, because ITU allocations mean there
    is no real example today -- which is exactly why this layer needs a test of
    its own instead of relying on one.
    """

    class Foreign:
        name = "Somewhere Else"

    monkeypatch.setattr(table, "lookup", lambda call: Foreign())
    assert guess_class("W1AW", None) is not None  # shape alone accepts it
    assert guess_class("W1AW", table) is None  # the table rejects it


def test_an_unresolvable_callsign_gets_no_guess(monkeypatch, table):
    monkeypatch.setattr(table, "lookup", lambda call: None)
    assert guess_class("W1AW", table) is None


# --- Station integration -------------------------------------------------
def test_station_infers_from_the_callsign(table):
    station = Station.from_config({"callsign": "W1AW", "grid": "FN31pr"}, table)
    assert station.license_class == "extra"
    assert station.license_certain is True


def test_configured_class_always_wins(table):
    """An Extra holding a vanity 2x3 must not be demoted by a guess."""
    station = Station.from_config(
        {"callsign": "KE8ABC", "grid": "FN31pr", "license_class": "extra"}, table
    )
    assert station.license_class == "extra"
    assert station.license_certain is True
    assert station.license_reason == "set in config"


def test_configured_class_is_normalized(table):
    station = Station.from_config({"callsign": "W1AW", "license_class": "  General "}, table)
    assert station.license_class == "general"


def test_no_callsign_means_no_class(table):
    assert Station.from_config({"grid": "FN31pr"}, table).license_class is None


def test_non_us_station_gets_no_class(table):
    station = Station.from_config({"callsign": "DL1ABC", "grid": "JO31"}, table)
    assert station.license_class is None
    assert station.license_reason is None


def test_a_non_us_operator_can_still_configure_one(table):
    """The panel is a reference for anyone; config is not US-gated."""
    station = Station.from_config({"callsign": "DL1ABC", "license_class": "extra"}, table)
    assert station.license_class == "extra"
