# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import json
from datetime import UTC, datetime

from hammunition_hill.snapshot import Snapshot, read_snapshot, write_snapshot


def make(source_id="solar", data=None, error=None):
    return Snapshot(
        source_id=source_id,
        kind="swpc",
        fetched_at=datetime(2026, 8, 26, 12, 0, tzinfo=UTC),
        stale_after_seconds=1800,
        data=data if data is not None else {"flux": 142},
        error=error,
    )


def test_roundtrip(tmp_path):
    write_snapshot(tmp_path, make())
    loaded = read_snapshot(tmp_path, "solar")
    assert loaded["data"] == {"flux": 142}
    assert loaded["fetched_at"] == "2026-08-26T12:00:00Z"
    assert loaded["stale_after_seconds"] == 1800


def test_write_is_atomic_and_leaves_no_temp_files(tmp_path):
    """A browser polling every 10s must never read a half-written file."""
    for _ in range(5):
        write_snapshot(tmp_path, make())
    assert [p.name for p in tmp_path.iterdir()] == ["solar.json"]


def test_replaces_previous_content(tmp_path):
    write_snapshot(tmp_path, make(data={"flux": 100}))
    write_snapshot(tmp_path, make(data={"flux": 200}))
    assert read_snapshot(tmp_path, "solar")["data"]["flux"] == 200


def test_error_field_survives_with_last_good_data(tmp_path):
    """The stale-but-honest case: keep the reading, mark the failure."""
    write_snapshot(tmp_path, make(error="FetchError: timeout"))
    loaded = read_snapshot(tmp_path, "solar")
    assert loaded["error"] == "FetchError: timeout"
    assert loaded["data"] == {"flux": 142}


def test_missing_snapshot_reads_as_none(tmp_path):
    assert read_snapshot(tmp_path, "never-written") is None


def test_corrupt_snapshot_reads_as_none(tmp_path):
    (tmp_path / "broken.json").write_text("{not json")
    assert read_snapshot(tmp_path, "broken") is None


def test_output_is_valid_json(tmp_path):
    path = write_snapshot(tmp_path, make())
    json.loads(path.read_text())
