# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""The shower table, and the date arithmetic that reads it.

Two separate risks, so two separate halves.

The **table** is hand-maintained data, and hand-maintained data goes wrong
quietly: a declination past the pole, a peak outside the shower's own run, a
radiant typed in hours instead of degrees. None of those throw; they just put a
shower in the wrong part of the sky. So the schema is checked the way
`tests/test_bandplan.py` checks band segments.

The **arithmetic** is the Quadrantids. They begin on 28 December and peak on 3
January, so any comparison that assumes start < end reports the strongest
shower of the year as never running, for its entire duration, and renders a
perfectly plausible table while doing it. That one is walked through a real
year under node.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
TABLE = json.loads((ROOT / "web" / "meteors.json").read_text(encoding="utf-8"))
SHOWERS = TABLE["showers"]

REQUIRED = {"id", "name", "start", "peak", "end", "zhr", "ra", "dec", "velocity_kms"}


def ids(shower: dict) -> str:
    return shower["id"]


def test_the_table_is_not_empty():
    assert len(SHOWERS) >= 10, "the IMO working list has more majors than this"


def test_shower_ids_are_unique():
    seen = [s["id"] for s in SHOWERS]
    assert len(seen) == len(set(seen)), f"duplicate shower ids: {seen}"


@pytest.mark.parametrize("shower", SHOWERS, ids=ids)
def test_every_shower_has_the_required_fields(shower):
    missing = REQUIRED - set(shower)
    assert not missing, f"{shower.get('id')}: missing {sorted(missing)}"


@pytest.mark.parametrize("shower", SHOWERS, ids=ids)
def test_radiants_are_on_the_sphere(shower):
    """RA in degrees, not hours. 24 would be a legal RA and a typo."""
    assert 0.0 <= shower["ra"] < 360.0, f"{shower['id']}: right ascension {shower['ra']}"
    assert -90.0 <= shower["dec"] <= 90.0, f"{shower['id']}: declination {shower['dec']}"


@pytest.mark.parametrize("shower", SHOWERS, ids=ids)
def test_dates_are_month_day_and_real(shower):
    for field in ("start", "peak", "end"):
        value = shower[field]
        assert isinstance(value, str) and len(value) == 5 and value[2] == "-", (
            f"{shower['id']}: {field} is {value!r}, want MM-DD"
        )
        # A real date in a leap year, so 02-29 would be accepted if anyone
        # ever needed it.
        datetime.strptime(f"2024-{value}", "%Y-%m-%d")  # noqa: DTZ007


@pytest.mark.parametrize("shower", SHOWERS, ids=ids)
def test_the_peak_falls_inside_the_shower(shower):
    """Including the ones that wrap the year, which is the whole difficulty."""
    day = lambda md: datetime.strptime(f"2001-{md}", "%Y-%m-%d").timetuple().tm_yday  # noqa: E731, DTZ007
    start, peak, end = (day(shower[f]) for f in ("start", "peak", "end"))
    if start <= end:
        assert start <= peak <= end, f"{shower['id']}: peak {peak} outside {start}..{end}"
    else:
        assert peak >= start or peak <= end, (
            f"{shower['id']}: peak {peak} outside the wrapped run {start}..{end}"
        )


@pytest.mark.parametrize("shower", SHOWERS, ids=ids)
def test_velocities_are_physically_possible(shower):
    """11 km/s is Earth escape; 72 is the head-on limit. Outside that is a typo."""
    assert 11 <= shower["velocity_kms"] <= 72, f"{shower['id']}: {shower['velocity_kms']} km/s"


@pytest.mark.parametrize("shower", SHOWERS, ids=ids)
def test_zhr_is_a_rate_or_a_declared_variable(shower):
    """0 is how the table spells "variable"; the panel renders it as `var`."""
    assert isinstance(shower["zhr"], int) and 0 <= shower["zhr"] <= 1000


def test_the_headline_showers_are_present_and_roughly_where_they_belong():
    """A guard against the table being replaced by something plausible but wrong.

    The Perseids peak in August and the Geminids in December. If either of
    those moves, the table is not the IMO list any more, whatever it says.
    """
    by_id = {s["id"]: s for s in SHOWERS}
    assert by_id["PER"]["peak"].startswith("08-")
    assert by_id["GEM"]["peak"].startswith("12-")
    assert by_id["QUA"]["peak"].startswith("01-")
    # The one that makes the wrap case real.
    assert by_id["QUA"]["start"].startswith("12-")


# --- the arithmetic, run under node ---------------------------------------
def _window_over_a_year(shower_id: str) -> dict[str, dict]:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node not installed")

    # Every day of a full year, so no part of a shower's run is unsampled.
    # Sampled at midnight UTC because that is where the peaks themselves sit:
    # sampling at noon puts every peak exactly half a day from two samples at
    # once, and "which of the two is nearest" then turns on a tie-break rather
    # than on anything about the shower.
    days = [
        (datetime(2026, 1, 1, tzinfo=UTC) + timedelta(days=n)).isoformat().replace("+00:00", "Z")
        for n in range(370)
    ]

    with tempfile.TemporaryDirectory() as tmp:
        driver = Path(tmp) / "showers.mjs"
        driver.write_text(
            f"""
import {{ showerWindow }} from "{ROOT / "web/panels/meteors/panel.js"}";
import {{ readFileSync }} from "node:fs";

const table = JSON.parse(readFileSync("{ROOT / "web/meteors.json"}", "utf8"));
const shower = table.showers.find((s) => s.id === {json.dumps(shower_id)});
const out = {{}};
for (const stamp of {json.dumps(days)}) {{
  const run = showerWindow(shower, new Date(stamp));
  out[stamp] = {{
    active: run.active,
    daysToPeak: run.daysToPeak,
    peak: new Date(run.peak).toISOString().slice(0, 10),
  }};
}}
console.log(JSON.stringify(out));
""",
            encoding="utf-8",
        )
        result = subprocess.run(  # noqa: S603
            [node, str(driver)], capture_output=True, text=True, timeout=120
        )
        assert result.returncode == 0, result.stderr
        return json.loads(result.stdout)


def test_the_quadrantids_are_active_across_the_new_year():
    """The bug this test exists for: a shower that wraps reads as never running."""
    over = _window_over_a_year("QUA")
    active = [stamp[:10] for stamp, run in over.items() if run["active"]]
    assert active, "the Quadrantids were never active on any day of a whole year"

    # 28 Dec to 12 Jan, so both sides of the boundary must be in there.
    assert any(day.startswith("2026-01-0") for day in active), "not active in early January"
    assert any(day.startswith("2026-12-3") for day in active), "not active in late December"
    assert "2026-06-15" not in active, "active in June, which it is not"


def test_a_showers_days_to_peak_counts_down_and_through_zero():
    over = _window_over_a_year("PER")
    # The sample nearest the crossing, which with midnight sampling is the
    # peak itself.
    peak_day = min(over, key=lambda stamp: abs(over[stamp]["daysToPeak"]))
    assert peak_day.startswith("2026-08-12"), f"Perseid peak landed on {peak_day}"
    assert over[peak_day]["daysToPeak"] == 0.0
    assert over[peak_day]["active"] is True

    ordered = [over[stamp]["daysToPeak"] for stamp in sorted(over) if over[stamp]["active"]]
    assert ordered == sorted(ordered, reverse=True), (
        "days-to-peak must decrease monotonically through an active run"
    )


def test_a_shower_that_is_not_running_points_at_its_next_peak():
    """Out of season the panel should say when it comes back, not go blank."""
    over = _window_over_a_year("GEM")
    off_season = over["2026-06-15T00:00:00Z"]
    assert off_season["active"] is False
    assert off_season["daysToPeak"] > 0, "a future peak must be ahead, not behind"
    assert off_season["peak"] == "2026-12-14"
