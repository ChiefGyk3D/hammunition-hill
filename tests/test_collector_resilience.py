# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""One bad source must never take the collector down.

Regression tests for a real failure: a UDP bind conflict on the WSJT-X port
propagated out of the stream task, through the TaskGroup, and killed every other
source *and* the HTTP server. A port conflict is an ordinary operator situation
-- a second instance, or GridTracker already listening -- and the rest of the
dashboard has no business caring.
"""

import asyncio

import pytest

from hammunition_hill.collector import _stream_loop
from hammunition_hill.config import Config, ServerConfig, SourceConfig
from hammunition_hill.egress import EgressGuard
from hammunition_hill.enrich import Enricher, Station
from hammunition_hill.prefix import PrefixTable
from hammunition_hill.snapshot import read_snapshot


@pytest.fixture
def config(tmp_path):
    return Config(
        server=ServerConfig(),
        sources=(),
        data_dir=tmp_path / "data",
        web_dir=tmp_path / "web",
    )


@pytest.fixture
def enricher():
    return Enricher(PrefixTable(None), Station.from_config({"grid": "FN31pr"}))


@pytest.fixture
def guard():
    return EgressGuard.build({"127.0.0.1"}, {"127.0.0.1"})


def source(kind="wsjtx", url="udp://127.0.0.1:2237"):
    return SourceConfig(id="stream", kind=kind, url=url, local=True)


async def test_a_stream_that_raises_does_not_propagate(config, guard, enricher, monkeypatch):
    """The exact shape of the bug: setup fails, and the failure escapes."""

    class Exploding:
        async def run(self, cfg, emit):
            raise OSError(98, "Address already in use")

    monkeypatch.setattr("hammunition_hill.collector.build_stream", lambda kind: Exploding())
    # Must return, not raise.
    await _stream_loop(guard, source(), config, enricher)


async def test_the_failure_is_recorded_as_a_snapshot(config, guard, enricher, monkeypatch):
    """A dead stream shows up in the UI rather than vanishing silently."""

    class Exploding:
        async def run(self, cfg, emit):
            raise OSError(98, "Address already in use")

    monkeypatch.setattr("hammunition_hill.collector.build_stream", lambda kind: Exploding())
    await _stream_loop(guard, source(), config, enricher)

    snapshot = read_snapshot(config.data_dir, "stream")
    assert snapshot is not None
    assert "Address already in use" in snapshot["error"]


async def test_cancellation_still_propagates(config, guard, enricher, monkeypatch):
    """Shutdown must not be swallowed by the catch-all."""

    class Hanging:
        async def run(self, cfg, emit):
            await asyncio.Event().wait()

    monkeypatch.setattr("hammunition_hill.collector.build_stream", lambda kind: Hanging())
    task = asyncio.create_task(_stream_loop(guard, source(), config, enricher))
    await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


async def test_a_denied_stream_never_starts(config, enricher, monkeypatch):
    """Egress policy is checked before the stream is built, not after."""
    built = False

    def build(kind):
        nonlocal built
        built = True
        raise AssertionError("should not be reached")

    monkeypatch.setattr("hammunition_hill.collector.build_stream", build)
    closed = EgressGuard.build(set(), set())
    await _stream_loop(closed, source(), config, enricher)

    assert not built
    assert "EgressDenied" in read_snapshot(config.data_dir, "stream")["error"]


async def test_sibling_sources_survive_a_failing_stream(config, guard, enricher, monkeypatch):
    """The property that actually matters: everything else keeps running."""
    survivor_ticks = 0

    class Exploding:
        async def run(self, cfg, emit):
            raise OSError(98, "Address already in use")

    async def survivor():
        nonlocal survivor_ticks
        for _ in range(3):
            survivor_ticks += 1
            await asyncio.sleep(0)

    monkeypatch.setattr("hammunition_hill.collector.build_stream", lambda kind: Exploding())

    async with asyncio.TaskGroup() as group:
        group.create_task(_stream_loop(guard, source(), config, enricher))
        group.create_task(survivor())

    assert survivor_ticks == 3


# --- station snapshot ---------------------------------------------------
def test_station_snapshot_carries_derived_coordinates(config, enricher):
    """Panels compute bearings client-side and need lat/lon, not just a grid.

    Regression: the snapshot published the raw config table, so the callsign
    panel had a grid square it could not turn into a heading.
    """
    from hammunition_hill.cli import _publish_station

    _publish_station(config, enricher)
    data = read_snapshot(config.data_dir, "station")["data"]

    assert data["grid"] == "FN31PR"
    assert data["located"] is True
    assert data["lat"] == pytest.approx(41.73, abs=0.05)
    assert data["lon"] == pytest.approx(-72.71, abs=0.05)


def test_station_snapshot_without_a_grid_says_so(config):
    """A station with no location must be explicit, not silently zeroed."""
    from hammunition_hill.cli import _publish_station

    plain = Enricher(PrefixTable(None), Station.from_config({"callsign": "N0CALL"}))
    _publish_station(config, plain)
    data = read_snapshot(config.data_dir, "station")["data"]

    assert data["located"] is False
    assert data["lat"] is None


# --- startup ------------------------------------------------------------
def test_a_taken_port_reports_cleanly_rather_than_traceback(tmp_path, capsys):
    """The common startup failure is another copy of this already running.

    A traceback is a poor way to say that, and the message should name the fix.
    """
    import socket

    from hammunition_hill.cli import _serve
    from hammunition_hill.config import Config, ServerConfig
    from hammunition_hill.egress import EgressGuard

    holder = socket.socket()
    holder.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    holder.bind(("127.0.0.1", 0))
    holder.listen(1)
    port = holder.getsockname()[1]

    # A minimally valid dashboard: _serve checks the web directory before it
    # binds, so that a missing dashboard is reported instead of a port being
    # taken for something that could never serve. This test is about the port,
    # so give it something serveable.
    web = tmp_path / "web"
    (web / "panels").mkdir(parents=True)
    (web / "index.html").write_text("<h1>hi</h1>")
    (web / "panels" / "index.json").write_text('{"dashboards": []}')
    config = Config(
        server=ServerConfig(host="127.0.0.1", port=port),
        sources=(),
        data_dir=tmp_path / "data",
        web_dir=web,
    )
    enricher = Enricher(PrefixTable(None), Station.from_config({}))

    try:
        assert _serve(config, EgressGuard.build(set(), set()), enricher) == 1
    finally:
        holder.close()

    errors = capsys.readouterr().err
    assert "cannot listen" in errors
    assert "--listen" in errors


@pytest.mark.asyncio
async def test_a_tier_zero_config_keeps_serving(tmp_path):
    """No sources must not mean no dashboard.

    `run_collector` returning shuts the HTTP server down, so returning early on
    an empty source list made `hamhill serve` exit immediately -- and the
    configuration it exited on was the offline one. A tier 0 dashboard (CW
    reference, band plan, clock, callsign lookup, beacons) needs no upstream by
    definition, and is exactly what an operator wants portable.

    Found by running the CW panel, which is the first genuinely useful
    zero-source configuration this project has had.
    """
    import asyncio

    from hammunition_hill.collector import run_collector
    from hammunition_hill.config import Config, ServerConfig
    from hammunition_hill.egress import EgressGuard

    config = Config(
        server=ServerConfig(host="127.0.0.1", port=0),
        sources=(),
        data_dir=tmp_path / "data",
        web_dir=tmp_path / "web",
    )
    enricher = Enricher(PrefixTable(None), Station.from_config({}))

    with pytest.raises(TimeoutError):
        # It must still be running when the timeout fires. Returning would mean
        # the server is about to be torn down.
        await asyncio.wait_for(
            run_collector(config, EgressGuard.build(set(), set()), enricher),
            timeout=0.5,
        )
