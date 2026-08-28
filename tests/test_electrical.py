# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Ohm's law, decibels, wire and batteries -- and the browser copy of each.

Arithmetic a field operator bets a deployment on. The interesting assertions
are the ones a plausible implementation gets wrong: the round trip in a
voltage-drop run, the overdetermined power wheel, and the derate that keeps a
lead-acid battery from being "empty" at the moment it is being ruined.
"""

from __future__ import annotations

import json
import math
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

from hammunition_hill.electrical import (
    AWG_OHMS_PER_KFT,
    ElectricalError,
    battery_runtime,
    db_between_watts,
    db_from_power_ratio,
    ohm,
    power_ratio_from_db,
    reference,
    voltage_drop,
)

# --- the power wheel ---------------------------------------------------------


@pytest.mark.parametrize(
    "given",
    [
        {"volts": 13.8, "amps": 7.25},
        {"volts": 13.8, "ohms": 50.0},
        {"volts": 13.8, "watts": 100.0},
        {"amps": 2.0, "ohms": 50.0},
        {"amps": 2.0, "watts": 100.0},
        {"ohms": 50.0, "watts": 100.0},
    ],
)
def test_every_pair_round_trips(given):
    """Whatever pair you start from, the four answers satisfy both laws."""
    result = ohm(**given)
    assert result["volts"] == pytest.approx(result["amps"] * result["ohms"], rel=1e-9)
    assert result["watts"] == pytest.approx(result["volts"] * result["amps"], rel=1e-9)
    for name, value in given.items():
        assert result[name] == pytest.approx(value)


def test_one_or_three_inputs_are_refused():
    """Silently ignoring an input turns a typo into an answer."""
    with pytest.raises(ElectricalError):
        ohm(volts=12.0)
    with pytest.raises(ElectricalError):
        ohm(volts=12.0, amps=1.0, ohms=12.0)


def test_the_100w_at_138v_case():
    result = ohm(volts=13.8, watts=100.0)
    assert result["amps"] == pytest.approx(7.246, abs=0.001)


# --- decibels ---------------------------------------------------------------


def test_the_landmarks_every_operator_knows():
    assert db_from_power_ratio(2.0) == pytest.approx(3.0103, abs=1e-4)
    assert db_from_power_ratio(10.0) == pytest.approx(10.0)
    assert db_between_watts(5.0, 100.0) == pytest.approx(13.0103, abs=1e-4)
    # One S-unit is 6 dB by convention: four times the power.
    assert power_ratio_from_db(6.0) == pytest.approx(3.981, abs=0.001)


def test_db_round_trips():
    for db in (-20.0, -3.0, 0.0, 3.0, 10.0, 30.0):
        assert db_from_power_ratio(power_ratio_from_db(db)) == pytest.approx(db)


# --- wire -------------------------------------------------------------------


def test_voltage_drop_uses_the_round_trip():
    """The classic mistake is computing one conductor.

    Ten metres of cable is twenty metres of copper: current goes out one wire
    and back the other. Halving the answer is the error a plausible
    implementation makes, so the expected value here is computed from the raw
    table entry, both conductors, by hand.
    """
    result = voltage_drop(12, one_way_m=10.0, amps=20.0, supply_volts=13.8)
    round_trip_ft = 2 * 10.0 * 3.28084
    expected = 1.588 * round_trip_ft / 1000 * 20.0
    assert result["drop_volts"] == pytest.approx(expected)
    assert result["drop_volts"] > 2.0, "a one-conductor answer would be about half this"


def test_thicker_wire_drops_less():
    drops = [voltage_drop(awg, 5.0, 20.0)["drop_volts"] for awg in sorted(AWG_OHMS_PER_KFT)]
    assert drops == sorted(drops), "drop must rise monotonically with AWG number"


def test_an_unknown_gauge_is_refused_with_the_menu():
    with pytest.raises(ElectricalError) as caught:
        voltage_drop(13, 5.0, 20.0)
    assert "13" in str(caught.value)


# --- batteries --------------------------------------------------------------


def test_chemistry_derates_are_applied():
    lifepo4 = battery_runtime(20.0, "lifepo4", 60.0)
    lead = battery_runtime(20.0, "lead_acid", 60.0)
    assert lifepo4["hours"] == pytest.approx(20.0 * 12.8 * 0.90 / 60.0)
    assert lead["hours"] == pytest.approx(20.0 * 12.8 * 0.50 / 60.0)
    assert lifepo4["hours"] > 1.7 * lead["hours"], (
        "the whole point of the derate is that nameplate Ah are not equal"
    )


def test_battery_nonsense_is_refused():
    for bad in (
        {"amp_hours": 0.0, "chemistry": "lifepo4", "load_watts": 60.0},
        {"amp_hours": 20.0, "chemistry": "unobtainium", "load_watts": 60.0},
        {"amp_hours": 20.0, "chemistry": "agm", "load_watts": 0.0},
    ):
        with pytest.raises(ElectricalError):
            battery_runtime(**bad)


# --- and the browser agrees --------------------------------------------------


def test_the_browser_calculator_matches_this_module():
    """web/lib/electrical.js is a second implementation, and those drift."""
    node = shutil.which("node")
    if node is None:
        pytest.skip("node not installed")

    root = Path(__file__).resolve().parents[1]
    payload = reference()
    pairs = [
        {"volts": 13.8, "amps": 7.25},
        {"volts": 13.8, "watts": 100.0},
        {"amps": 2.0, "ohms": 50.0},
        {"ohms": 50.0, "watts": 100.0},
    ]
    drops = [[12, 5.0, 20.0], [10, 30.0, 25.0], [18, 2.0, 1.0]]
    batteries = [[20.0, "lifepo4", 60.0], [100.0, "lead_acid", 250.0], [9.0, "agm", 30.0]]

    with tempfile.TemporaryDirectory() as tmp:
        driver = Path(tmp) / "cmp.mjs"
        driver.write_text(
            f"""
import {{
  batteryRuntime, dbBetweenWatts, dbFromPowerRatio, ohm, powerRatioFromDb, voltageDrop,
}} from "{root / "web/lib/electrical.js"}";
const ref = {json.dumps(payload)};
const out = {{ ohm: [], db: [], drop: [], battery: [] }};
for (const pair of {json.dumps(pairs)}) out.ohm.push(ohm(pair));
for (const [a, b] of [[5, 100], [100, 5], [1, 1], [0.5, 1000]]) out.db.push(dbBetweenWatts(a, b));
for (const db of [-20, -3, 0, 3, 10, 30]) out.db.push(powerRatioFromDb(db));
for (const [awg, m, amps] of {json.dumps(drops)}) {{
  out.drop.push(voltageDrop(ref.awg_ohms_per_kft, {3.28084}, awg, m, amps, 13.8));
}}
for (const [ah, chem, w] of {json.dumps(batteries)}) {{
  out.battery.push(batteryRuntime(ref.battery_usable, ah, chem, w, 12.8));
}}
console.log(JSON.stringify(out));
""",
            encoding="utf-8",
        )
        result = subprocess.run(  # noqa: S603
            [node, str(driver)], capture_output=True, text=True, timeout=120
        )
        assert result.returncode == 0, result.stderr
        js = json.loads(result.stdout)

    for got, pair in zip(js["ohm"], pairs, strict=True):
        want = ohm(**pair)
        for key in ("volts", "amps", "ohms", "watts"):
            assert got[key] == pytest.approx(want[key], rel=1e-12), (pair, key)

    want_db = [db_between_watts(a, b) for a, b in [(5, 100), (100, 5), (1, 1), (0.5, 1000)]]
    want_db += [power_ratio_from_db(db) for db in (-20, -3, 0, 3, 10, 30)]
    assert js["db"] == pytest.approx(want_db, rel=1e-12)

    for got, args in zip(js["drop"], drops, strict=True):
        want = voltage_drop(args[0], args[1], args[2], 13.8)
        for key, value in want.items():
            assert got[key] == pytest.approx(value, rel=1e-12), (args, key)

    for got, args in zip(js["battery"], batteries, strict=True):
        want = battery_runtime(args[0], args[1], args[2], 12.8)
        for key, value in want.items():
            assert got[key] == pytest.approx(value, rel=1e-12), (args, key)


def test_infinity_survives_the_json_boundary():
    """R with zero current is infinite in both languages, and JSON has no inf.

    The drift test ships answers through JSON.stringify, which turns Infinity
    into null -- so the drift cases above avoid it, and this test pins the
    behaviour on each side directly instead.
    """
    assert ohm(volts=12.0, amps=0.0)["ohms"] == math.inf
    node = shutil.which("node")
    if node is None:
        pytest.skip("node not installed")
    root = Path(__file__).resolve().parents[1]
    script = (
        f'import {{ ohm }} from "{root / "web/lib/electrical.js"}";'
        # A string sentinel, not a boolean: console.log(true) comes out
        # wrapped in ANSI colour codes wherever node decides the stream
        # deserves them, which on the CI runners it did.
        'console.log(ohm({volts: 12, amps: 0}).ohms === Infinity ? "ok" : "broken");'
    )
    result = subprocess.run(  # noqa: S603
        [shutil.which("node"), "--input-type=module", "-e", script],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.stdout.strip() == "ok", result.stderr
