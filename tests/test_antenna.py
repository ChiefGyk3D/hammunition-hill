# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Antenna and feedline arithmetic, checked against what it claims to be.

A calculator is trusted the moment it is on screen, which makes a wrong one
worse than none: somebody cuts wire to it. So these tests anchor the results to
figures an operator can recognise -- the 468/f dipole rule, a 100 ft run of
LMR-400 at 2 m, a 2:1 SWR reflecting 11% of the power -- rather than only
checking that the arithmetic is self-consistent.

The published coax numbers are the load-bearing part. The model is *defined* by
the two points in the table, so what the tests below verify is that the curve
through those points still lands where the datasheets say at frequencies in
between and outside.
"""

from __future__ import annotations

import json
import math
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

from hammunition_hill.antenna import (
    ANTENNA_BY_ID,
    ANTENNAS,
    COAX,
    COAX_BY_ID,
    FEET_PER_METRE,
    SPEED_OF_LIGHT,
    WIRE_SHORTENING,
    AntennaError,
    cut_chart,
    electrical_length_m,
    element_length_m,
    loss_constants,
    matched_loss_db,
    power_after_loss,
    reference,
    swr_figures,
    total_line_loss_db,
    wavelength_m,
)

HUNDRED_FEET_M = 100.0 / FEET_PER_METRE


# --- wavelength and element lengths -----------------------------------------


def test_a_wavelength_is_a_wavelength():
    assert wavelength_m(300.0) == pytest.approx(0.999308, rel=1e-5)
    assert wavelength_m(14.2) == pytest.approx(SPEED_OF_LIGHT / 14.2e6)


@pytest.mark.parametrize("freq", [0, -1, -0.0001])
def test_a_frequency_that_cannot_mean_anything_is_an_error(freq):
    with pytest.raises(AntennaError, match="positive"):
        wavelength_m(freq)


@pytest.mark.parametrize("freq_mhz", [1.9, 3.6, 7.15, 14.2, 21.3, 28.4, 50.1, 146.0])
def test_the_dipole_matches_the_468_over_f_rule(freq_mhz):
    """The rule of thumb every US handbook prints, and what the panel must agree with.

    468/f is 0.95 of a free-space half wave expressed in feet. If these ever
    disagree, one of them is wrong and it is not the century-old one.
    """
    feet = element_length_m(freq_mhz, "dipole") * FEET_PER_METRE
    assert feet == pytest.approx(468.0 / freq_mhz, rel=0.002)


@pytest.mark.parametrize("freq_mhz", [7.15, 14.2, 28.4, 146.0])
def test_the_full_wave_loop_matches_the_1005_over_f_rule(freq_mhz):
    feet = element_length_m(freq_mhz, "loop") * FEET_PER_METRE
    assert feet == pytest.approx(1005.0 / freq_mhz, rel=0.005)


def test_a_quarter_wave_vertical_is_half_a_dipole():
    """Not a tautology worth skipping: they are separate table entries."""
    assert element_length_m(14.2, "vertical") == pytest.approx(element_length_m(14.2, "dipole") / 2)


def test_an_end_fed_half_wave_is_the_same_wire_as_a_dipole():
    assert element_length_m(7.15, "efhw") == pytest.approx(element_length_m(7.15, "dipole"))


def test_a_loop_runs_long_and_a_wire_runs_short():
    """The sign of the correction, which is the thing people get backwards."""
    free_space = wavelength_m(14.2)
    assert element_length_m(14.2, "dipole") < free_space * 0.5
    assert element_length_m(14.2, "loop") > free_space


def test_lengths_scale_inversely_with_frequency():
    assert element_length_m(7.1, "dipole") == pytest.approx(element_length_m(14.2, "dipole") * 2)


def test_an_unknown_antenna_is_an_error_rather_than_a_length():
    with pytest.raises(AntennaError, match="unknown antenna"):
        element_length_m(14.2, "beverage")


def test_the_cut_chart_covers_every_antenna_in_both_units():
    chart = cut_chart(14.2)
    assert [row["id"] for row in chart] == [entry["id"] for entry in ANTENNAS]
    for row in chart:
        assert row["feet"] == pytest.approx(row["metres"] * FEET_PER_METRE, abs=0.01)
        assert row["metres"] > 0


# --- feedline ---------------------------------------------------------------


@pytest.mark.parametrize("entry", COAX, ids=lambda e: e["id"])
def test_the_model_reproduces_each_published_point(entry):
    """The curve must pass through the two numbers the table states.

    If it does not, the table is decoration and every figure below it is made
    up. This is the check that keeps COAX honest.
    """
    for freq, published in entry["at"]:
        got = matched_loss_db(entry["id"], freq, HUNDRED_FEET_M)
        assert got == pytest.approx(published, rel=1e-6), f"{entry['id']} at {freq} MHz"


# Figures an operator would recognise, at frequencies *between and outside* the
# two published points, so they test the curve rather than the table.
@pytest.mark.parametrize(
    ("coax_id", "freq_mhz", "expected_db", "tolerance"),
    [
        ("lmr400", 146.0, 1.5, 0.2),
        ("lmr400", 14.2, 0.45, 0.1),
        ("lmr400", 1000.0, 4.1, 0.6),
        ("rg213", 14.2, 0.7, 0.15),
        ("rg213", 146.0, 2.3, 0.3),
        ("rg58", 146.0, 5.0, 0.5),
        ("rg58", 28.4, 2.1, 0.4),
        ("rg8x", 14.2, 1.3, 0.3),
        ("ldf4", 146.0, 0.75, 0.15),
    ],
)
def test_a_hundred_feet_costs_what_the_datasheets_say(coax_id, freq_mhz, expected_db, tolerance):
    got = matched_loss_db(coax_id, freq_mhz, HUNDRED_FEET_M)
    assert got == pytest.approx(expected_db, abs=tolerance), (
        f"{coax_id} at {freq_mhz} MHz: {got:.2f} dB, expected about {expected_db}"
    )


def test_loss_rises_with_frequency_and_with_length():
    for entry in COAX:
        low = matched_loss_db(entry["id"], 14.0, HUNDRED_FEET_M)
        high = matched_loss_db(entry["id"], 146.0, HUNDRED_FEET_M)
        assert high > low, entry["id"]
        assert matched_loss_db(entry["id"], 146.0, 2 * HUNDRED_FEET_M) == pytest.approx(2 * high)


def test_the_cables_rank_the_way_the_catalogue_does():
    """Better cable is less lossy at every frequency, or the table has a typo."""
    order = ["rg174", "rg58", "rg8x", "rg213", "lmr400", "lmr600", "ldf4"]
    for freq in (7.0, 50.0, 146.0, 446.0):
        losses = [matched_loss_db(c, freq, HUNDRED_FEET_M) for c in order]
        assert losses == sorted(losses, reverse=True), f"at {freq} MHz: {losses}"


def test_zero_length_costs_nothing():
    assert matched_loss_db("rg213", 146.0, 0.0) == 0.0


def test_an_unknown_cable_or_a_negative_length_is_an_error():
    with pytest.raises(AntennaError, match="unknown coax"):
        matched_loss_db("wet string", 14.0, 10.0)
    with pytest.raises(AntennaError, match="negative"):
        matched_loss_db("rg213", 14.0, -1.0)


def test_two_identical_reference_points_are_rejected_rather_than_dividing_by_zero():
    with pytest.raises(AntennaError, match="not independent"):
        loss_constants((100.0, 2.0), (100.0, 2.0))


def test_a_quarter_wave_of_cable_is_shorter_than_a_quarter_wave_of_air():
    """The single most common way a home-made matching section ends up wrong."""
    air = wavelength_m(14.2) * 0.25
    for entry in COAX:
        cable = electrical_length_m(14.2, entry["id"])
        assert cable == pytest.approx(air * entry["vf"])
        assert cable < air


# --- SWR --------------------------------------------------------------------


def test_a_perfect_match_reflects_nothing():
    figures = swr_figures(1.0)
    assert figures["rho"] == 0.0
    assert figures["reflected_pct"] == 0.0
    assert figures["mismatch_loss_db"] == 0.0
    assert not math.copysign(1, figures["mismatch_loss_db"]) < 0, "rendered as -0.0 dB"
    assert figures["return_loss_db"] is None, "infinite return loss is published as null"


@pytest.mark.parametrize(
    ("swr", "reflected_pct", "return_loss_db"),
    [(1.5, 4.0, 13.98), (2.0, 11.11, 9.54), (3.0, 25.0, 6.02), (5.0, 44.44, 3.52)],
)
def test_the_textbook_swr_figures(swr, reflected_pct, return_loss_db):
    figures = swr_figures(swr)
    assert figures["reflected_pct"] == pytest.approx(reflected_pct, abs=0.01)
    assert figures["return_loss_db"] == pytest.approx(return_loss_db, abs=0.01)


def test_an_open_or_a_short_reflects_everything():
    figures = swr_figures(math.inf)
    assert figures["rho"] == 1.0
    assert figures["reflected_pct"] == 100.0
    assert figures["swr"] is None
    assert figures["mismatch_loss_db"] is None


def test_an_swr_below_one_is_an_error():
    """Below 1:1 is not a good match, it is a broken meter."""
    with pytest.raises(AntennaError, match="below 1.0"):
        swr_figures(0.9)


def test_mismatch_loss_rises_with_swr():
    values = [swr_figures(s)["mismatch_loss_db"] for s in (1.0, 1.5, 2.0, 3.0, 5.0, 10.0)]
    assert values == sorted(values)


# --- the point of the whole thing -------------------------------------------


def test_swr_costs_almost_nothing_on_a_good_short_line():
    """Because "high SWR is bad" is the belief this panel exists to complicate."""
    matched = matched_loss_db("lmr400", 14.2, 10.0)
    total = total_line_loss_db("lmr400", 14.2, 10.0, 3.0)
    assert total - matched < 0.15, "a 3:1 SWR on 10 m of LMR-400 at 20 m should barely matter"


def test_the_same_swr_is_expensive_on_a_long_lossy_line():
    matched = matched_loss_db("rg58", 146.0, 30.0)
    total = total_line_loss_db("rg58", 146.0, 30.0, 3.0)
    assert total - matched > 0.8, "a 3:1 SWR on 30 m of RG-58 at 2 m should cost real power"


def test_a_matched_line_costs_exactly_its_matched_loss():
    for coax in ("rg58", "lmr400"):
        assert total_line_loss_db(coax, 14.2, 20.0, 1.0) == pytest.approx(
            matched_loss_db(coax, 14.2, 20.0)
        )


def test_total_loss_is_never_less_than_matched_loss():
    for coax in [entry["id"] for entry in COAX]:
        for swr in (1.0, 1.5, 2.0, 5.0, 10.0):
            matched = matched_loss_db(coax, 50.0, 25.0)
            assert total_line_loss_db(coax, 50.0, 25.0, swr) >= matched - 1e-9


def test_power_after_loss_is_the_arithmetic_people_can_check():
    assert power_after_loss(100.0, 3.0) == pytest.approx(50.1, abs=0.2)
    assert power_after_loss(100.0, 0.0) == 100.0
    assert power_after_loss(100.0, 10.0) == pytest.approx(10.0)


def test_negative_power_is_an_error():
    with pytest.raises(AntennaError, match="negative"):
        power_after_loss(-5.0, 1.0)


# --- the published payload --------------------------------------------------


def test_the_reference_payload_is_json_and_complete():
    payload = reference()
    assert json.loads(json.dumps(payload)) == payload
    assert [entry["id"] for entry in payload["antennas"]] == list(ANTENNA_BY_ID)
    assert [entry["id"] for entry in payload["coax"]] == list(COAX_BY_ID)
    assert payload["wire_shortening"] == WIRE_SHORTENING


def test_every_coax_entry_is_plausible():
    for entry in COAX:
        assert 0.5 < entry["vf"] <= 1.0, f"{entry['id']} has an impossible velocity factor"
        assert entry["ohms"] in (50, 75, 300, 450), entry["id"]
        (f1, l1), (f2, l2) = entry["at"]
        assert f2 > f1 and l2 > l1, f"{entry['id']}'s reference points are not ordered"


def test_every_antenna_entry_is_plausible():
    for entry in ANTENNAS:
        assert 0 < entry["factor"] <= 2.0, entry["id"]
        assert isinstance(entry["wire"], bool)


# --- and the browser agrees -------------------------------------------------


def test_the_browser_calculator_matches_this_module():
    """web/lib/antenna.js is a second implementation, and those drift.

    The browser does this arithmetic itself so the panel works with the network
    down. That means two copies of every formula, so this runs the JavaScript
    the panel loads, over the same published tables, and demands the same
    answers to the last decimal place the panel displays.
    """
    node = shutil.which("node")
    if node is None:
        pytest.skip("node not installed")

    root = Path(__file__).resolve().parents[1]
    payload = reference()
    freqs = [1.85, 7.15, 14.2, 28.4, 50.1, 146.0, 446.0, 1296.0]
    lengths = [0.0, 3.0, 15.24, 30.48, 100.0]
    swrs = [1.0, 1.15, 1.5, 2.0, 2.7, 5.0, 10.0]

    with tempfile.TemporaryDirectory() as tmp:
        ref_path = Path(tmp) / "antenna.json"
        ref_path.write_text(json.dumps(payload), encoding="utf-8")

        driver = Path(tmp) / "cmp.mjs"
        driver.write_text(
            f"""
import {{ readFileSync }} from "fs";
import {{
  cutChart, electricalLengthM, matchedLossDb, powerAfterLoss, swrFigures,
  totalLineLossDb, wavelengthM,
}} from "{root / "web/lib/antenna.js"}";

const p = JSON.parse(readFileSync({str(ref_path)!r}, "utf8"));
const out = {{
  wave: {{}}, cut: {{}}, loss: {{}}, stub: {{}},
  swr: {{}}, total: {{}}, power: {{}},
}};

for (const f of {json.dumps(freqs)}) {{
  out.wave[f] = wavelengthM(f);
  out.cut[f] = cutChart(f, p);
  out.loss[f] = {{}};
  out.stub[f] = {{}};
  out.total[f] = {{}};
  for (const coax of p.coax) {{
    out.loss[f][coax.id] = {json.dumps(lengths)}.map(
      (m) => matchedLossDb(coax, f, m, p.feet_per_metre));
    out.stub[f][coax.id] = electricalLengthM(f, coax);
    out.total[f][coax.id] = {json.dumps(swrs)}.map(
      (s) => totalLineLossDb(coax, f, 25, s, p.feet_per_metre));
  }}
}}
for (const s of {json.dumps(swrs)}) out.swr[s] = swrFigures(s);
out.swr["inf"] = swrFigures(Infinity);
for (const db of [0, 0.5, 1, 3, 6, 10]) out.power[db] = powerAfterLoss(100, db);
console.log(JSON.stringify(out));
""",
            encoding="utf-8",
        )

        result = subprocess.run(  # noqa: S603
            [node, str(driver)], capture_output=True, text=True, timeout=120
        )
        assert result.returncode == 0, result.stderr
        js = json.loads(result.stdout)

    for freq in freqs:
        key = repr(freq) if freq != int(freq) else str(int(freq))
        key = key if key in js["wave"] else str(freq)
        assert js["wave"][key] == pytest.approx(wavelength_m(freq)), f"wavelength({freq})"
        assert js["cut"][key] == cut_chart(freq), f"cutChart({freq})"

        for entry in COAX:
            got = js["loss"][key][entry["id"]]
            want = [matched_loss_db(entry["id"], freq, m) for m in lengths]
            assert got == pytest.approx(want), f"loss({entry['id']}, {freq})"

            assert js["stub"][key][entry["id"]] == pytest.approx(
                electrical_length_m(freq, entry["id"])
            ), f"stub({entry['id']}, {freq})"

            got_total = js["total"][key][entry["id"]]
            want_total = [total_line_loss_db(entry["id"], freq, 25.0, s) for s in swrs]
            assert got_total == pytest.approx(want_total), f"total({entry['id']}, {freq})"

    for swr in swrs:
        key = str(int(swr)) if swr == int(swr) else str(swr)
        assert js["swr"][key] == swr_figures(swr), f"swrFigures({swr})"
    assert js["swr"]["inf"] == swr_figures(math.inf)

    for db in (0, 0.5, 1, 3, 6, 10):
        key = str(int(db)) if db == int(db) else str(db)
        assert js["power"][key] == pytest.approx(power_after_loss(100.0, db)), f"power({db})"
