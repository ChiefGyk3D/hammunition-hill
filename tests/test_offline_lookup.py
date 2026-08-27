# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Provider chains, the offline FCC index, and what happens when the WAN dies."""

import io
import zipfile

import httpx
import pytest

from hammunition_hill.config import ConfigError, parse_config
from hammunition_hill.egress import EgressGuard
from hammunition_hill.lookup.base import LookupError, LookupResult
from hammunition_hill.lookup.cache import LookupCache
from hammunition_hill.lookup.fcc import FccUlsProvider
from hammunition_hill.lookup.resolver import OFFLINE_AFTER_FAILURES, Resolver
from hammunition_hill.lookup.uls import UlsIndex, build_index


def base_cfg(**overrides):
    base = {
        "server": {"host": "127.0.0.1", "port": 8073},
        "sources": [
            {"id": "hamqsl", "kind": "hamqsl", "url": "https://www.hamqsl.com/solarxml.php"}
        ],
    }
    base.update(overrides)
    return base


# --- building a synthetic ULS archive -------------------------------------
def hd(call, status="A", grant="01/15/2020", expires="01/15/2030"):
    # Positional, per the FCC layout: record type, usi, file no, ebf, call...
    row = ["HD", "1", "", "", call, status, "HA", grant, expires]
    return "|".join(row)


def en(call, entity="", first="", last="", city="DENVER", state="CO", zipcode="80202"):
    row = ["EN", "1", "", "", call, "I", "", entity, first, "", last, ""]
    row += ["", "", "", "123 MAIN ST", city, state, zipcode]
    return "|".join(row)


def am(call, klass="E"):
    return "|".join(["AM", "1", "", "", call, klass, "A"])


def archive(tmp_path, hd_lines, en_lines, am_lines, name="l_amat.zip"):
    path = tmp_path / name
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as zf:
        zf.writestr("HD.dat", "\n".join(hd_lines) + "\n")
        zf.writestr("EN.dat", "\n".join(en_lines) + "\n")
        zf.writestr("AM.dat", "\n".join(am_lines) + "\n")
    path.write_bytes(buffer.getvalue())
    return path


# --- the importer ---------------------------------------------------------
def test_imports_a_licence(tmp_path):
    src = archive(
        tmp_path,
        [hd("W1AW")],
        [en("W1AW", entity="ARRL HQ OPERATORS CLUB")],
        [am("W1AW", "E")],
    )
    db = tmp_path / "uls.sqlite3"
    stats = build_index(src, db)

    assert stats.indexed == 1
    index = UlsIndex(db)
    row = index.lookup("W1AW")
    assert row["name"] == "ARRL HQ OPERATORS CLUB"
    assert row["operator_class"] == "Amateur Extra"
    assert row["state"] == "CO"
    index.close()


def test_individual_name_is_assembled_from_first_and_last(tmp_path):
    """Clubs populate entity_name; individuals populate first/last. Both occur."""
    src = archive(tmp_path, [hd("K0ABC")], [en("K0ABC", first="JANE", last="DOE")], [am("K0ABC")])
    db = tmp_path / "uls.sqlite3"
    build_index(src, db)
    assert UlsIndex(db).lookup("K0ABC")["name"] == "JANE DOE"


def test_inactive_licences_are_not_indexed(tmp_path):
    """The panel asks who this *is*, not who it was."""
    src = archive(
        tmp_path,
        [hd("W1AW"), hd("K0DEAD", status="E"), hd("K0GONE", status="C")],
        [en("W1AW"), en("K0DEAD"), en("K0GONE")],
        [am("W1AW"), am("K0DEAD"), am("K0GONE")],
    )
    db = tmp_path / "uls.sqlite3"
    stats = build_index(src, db)
    assert stats.indexed == 1
    assert stats.inactive == 2
    assert UlsIndex(db).lookup("K0DEAD") is None


def test_all_six_operator_classes_including_the_retired_ones(tmp_path):
    """Novice and Advanced are no longer issued but are still held and on air."""
    calls = {"N0NOV": "N", "K0TEC": "T", "K0GEN": "G", "K0ADV": "A", "K0EXT": "E", "K0TP": "P"}
    src = archive(
        tmp_path,
        [hd(c) for c in calls],
        [en(c) for c in calls],
        [am(c, k) for c, k in calls.items()],
    )
    db = tmp_path / "uls.sqlite3"
    build_index(src, db)
    index = UlsIndex(db)
    assert index.lookup("N0NOV")["operator_class"] == "Novice"
    assert index.lookup("K0ADV")["operator_class"] == "Advanced"
    assert index.lookup("K0TP")["operator_class"] == "Technician Plus"
    index.close()


def test_malformed_lines_are_counted_not_fatal(tmp_path):
    """A positional parser against a format we cannot re-verify must not abort."""
    src = archive(
        tmp_path,
        [hd("W1AW"), "HD|1|too|short", "GARBAGE|not|a|record", hd("K0ABC")],
        [en("W1AW"), "EN|1|short", en("K0ABC")],
        [am("W1AW"), "AM|1", am("K0ABC")],
    )
    db = tmp_path / "uls.sqlite3"
    stats = build_index(src, db)
    assert stats.indexed == 2
    assert sum(stats.skipped.values()) >= 3
    assert UlsIndex(db).lookup("W1AW") is not None


def test_non_ascii_names_do_not_abort_the_import(tmp_path):
    """The FCC files are Latin-1 and contain names that are not ASCII."""
    line = en("K0ABC", first="JOSÉ", last="MUÑOZ").encode("latin-1")
    path = tmp_path / "l_amat.zip"
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as zf:
        zf.writestr("HD.dat", hd("K0ABC") + "\n")
        zf.writestr("EN.dat", line + b"\n")
        zf.writestr("AM.dat", am("K0ABC") + "\n")
    path.write_bytes(buffer.getvalue())

    db = tmp_path / "uls.sqlite3"
    build_index(path, db)
    assert "MU" in UlsIndex(db).lookup("K0ABC")["name"]


def test_a_non_zip_is_refused_with_the_real_url(tmp_path):
    bad = tmp_path / "l_amat.zip"
    bad.write_text("<html>404</html>")
    with pytest.raises(ValueError, match="l_amat.zip"):
        build_index(bad, tmp_path / "uls.sqlite3")


def test_import_is_atomic(tmp_path):
    """A half-built index must never be queried."""
    src = archive(tmp_path, [hd("W1AW")], [en("W1AW")], [am("W1AW")])
    db = tmp_path / "uls.sqlite3"
    build_index(src, db)
    assert db.is_file()
    assert not db.with_suffix(".building").exists()


def test_street_address_is_not_carried_into_the_index(tmp_path):
    """Anything published here is readable by everyone on the LAN.

    City and state are useful on a dashboard. A house number is not, and the
    source file has one for every licensee in the country.
    """
    src = archive(tmp_path, [hd("K0ABC")], [en("K0ABC", first="JANE", last="DOE")], [am("K0ABC")])
    db = tmp_path / "uls.sqlite3"
    build_index(src, db)
    row = UlsIndex(db).lookup("K0ABC")
    assert "123 MAIN ST" not in str(row)
    assert "street" not in " ".join(row.keys()).lower()


# --- the provider ---------------------------------------------------------
@pytest.mark.asyncio
async def test_provider_resolves_from_the_index(tmp_path):
    src = archive(tmp_path, [hd("W1AW")], [en("W1AW", entity="ARRL")], [am("W1AW", "E")])
    db = tmp_path / "uls.sqlite3"
    build_index(src, db)

    provider = FccUlsProvider(db)
    async with httpx.AsyncClient(transport=httpx.MockTransport(_never_called)) as client:
        result = await provider.resolve(client, "w1aw")
    assert result.callsign == "W1AW"
    assert result.license_class == "Amateur Extra"
    assert result.source == "fcc_uls"


@pytest.mark.asyncio
async def test_provider_declines_a_callsign_not_on_file(tmp_path):
    """Declining is a real answer, and it is what lets a chain fall through."""
    src = archive(tmp_path, [hd("W1AW")], [en("W1AW")], [am("W1AW")])
    db = tmp_path / "uls.sqlite3"
    build_index(src, db)
    provider = FccUlsProvider(db)
    async with httpx.AsyncClient(transport=httpx.MockTransport(_never_called)) as client:
        assert await provider.resolve(client, "DL1ABC") is None


@pytest.mark.asyncio
async def test_a_missing_index_raises_rather_than_declining(tmp_path):
    """ "No index" is a config problem, not "not on file".

    Declining would cache a miss for a day for a callsign that is in fact on
    file, and would stop the chain falling through to a network provider.
    """
    provider = FccUlsProvider(tmp_path / "absent.sqlite3")
    async with httpx.AsyncClient(transport=httpx.MockTransport(_never_called)) as client:
        with pytest.raises(LookupError, match="fcc-import"):
            await provider.resolve(client, "W1AW")


def _never_called(request):  # pragma: no cover - asserts the offline promise
    raise AssertionError(f"the offline provider made a network request to {request.url}")


# --- config ---------------------------------------------------------------
def test_single_provider_still_works(tmp_path):
    """Every config written before chains existed must keep working."""
    config = parse_config(base_cfg(lookup={"provider": "callook"}), base_dir=tmp_path)
    assert config.lookup.providers == ("callook",)
    assert config.lookup.provider == "callook"
    assert config.lookup.enabled


def test_chain_parses_in_order(tmp_path):
    config = parse_config(base_cfg(lookup={"providers": ["fcc_uls", "qrz"]}), base_dir=tmp_path)
    assert config.lookup.providers == ("fcc_uls", "qrz")


def test_both_forms_at_once_is_refused(tmp_path):
    with pytest.raises(ConfigError, match="not both"):
        parse_config(
            base_cfg(lookup={"provider": "qrz", "providers": ["fcc_uls"]}), base_dir=tmp_path
        )


def test_none_cannot_be_a_link_in_a_chain(tmp_path):
    with pytest.raises(ConfigError, match="cannot be combined"):
        parse_config(base_cfg(lookup={"providers": ["none", "qrz"]}), base_dir=tmp_path)


def test_none_alone_disables_lookup(tmp_path):
    config = parse_config(base_cfg(lookup={"providers": ["none"]}), base_dir=tmp_path)
    assert config.lookup.providers == ()
    assert not config.lookup.enabled


def test_duplicate_provider_is_refused(tmp_path):
    with pytest.raises(ConfigError, match="listed twice"):
        parse_config(base_cfg(lookup={"providers": ["qrz", "qrz"]}), base_dir=tmp_path)


def test_every_chain_provider_reaches_the_egress_allowlist(tmp_path):
    config = parse_config(base_cfg(lookup={"providers": ["fcc_uls", "hamqth"]}), base_dir=tmp_path)
    allowed, _ = config.allowlist()
    assert "www.hamqth.com" in allowed


def test_fcc_uls_grants_no_egress_reach(tmp_path):
    """Configuring the offline provider must not widen what this process can contact."""
    config = parse_config(base_cfg(lookup={"providers": ["fcc_uls"]}), base_dir=tmp_path)
    allowed, _ = config.allowlist()
    assert allowed == {"www.hamqsl.com"}  # the source only; nothing from lookup


# --- chain behaviour ------------------------------------------------------
class FakeProvider:
    """A provider whose behaviour per callsign is scripted by the test."""

    needs_credentials = False
    worldwide = True

    def __init__(self, name, answers, *, offline=False, hosts=()):
        self.name = name
        self.hosts = hosts
        self.offline = offline
        self._answers = answers
        self.asked = []

    async def resolve(self, client, callsign):
        self.asked.append(callsign)
        answer = self._answers.get(callsign, None)
        if isinstance(answer, Exception):
            raise answer
        if answer is None:
            return None
        return LookupResult(callsign=callsign, source=self.name, name=answer)


def guard_for(*hosts):
    return EgressGuard.build(set(hosts), set(hosts))


async def drain(resolver, calls):
    async with httpx.AsyncClient(transport=httpx.MockTransport(_never_called)) as client:
        return await resolver.resolve_batch(client, calls)


@pytest.mark.asyncio
async def test_first_provider_to_answer_wins(tmp_path):
    local = FakeProvider("local", {"W1AW": "ARRL"}, offline=True)
    net = FakeProvider("net", {"W1AW": "should not be asked"})
    resolver = Resolver([local, net], LookupCache(tmp_path), guard_for())

    await drain(resolver, ["W1AW"])
    assert net.asked == []
    assert resolver.cache.get("W1AW")["source"] == "local"


@pytest.mark.asyncio
async def test_a_decline_falls_through_to_the_next_provider(tmp_path):
    """An offline US index declines DL1ABC for free; the paid one covers it.

    This is the whole reason to put a local provider first: the network provider
    only ever sees the callsigns it is actually needed for.
    """
    local = FakeProvider("local", {}, offline=True)
    net = FakeProvider("net", {"DL1ABC": "Hans"})
    resolver = Resolver([local, net], LookupCache(tmp_path), guard_for())

    await drain(resolver, ["DL1ABC"])
    assert local.asked == ["DL1ABC"]
    assert resolver.cache.get("DL1ABC")["source"] == "net"


@pytest.mark.asyncio
async def test_an_error_falls_through_too(tmp_path):
    broken = FakeProvider("broken", {"W1AW": LookupError("index missing")}, offline=True)
    net = FakeProvider("net", {"W1AW": "ARRL"})
    resolver = Resolver([broken, net], LookupCache(tmp_path), guard_for())

    await drain(resolver, ["W1AW"])
    assert resolver.cache.get("W1AW")["source"] == "net"


@pytest.mark.asyncio
async def test_every_provider_failing_does_not_cache_a_miss(tmp_path):
    """A dead WAN must not hide a callsign for a day after it comes back."""
    a = FakeProvider("a", {"W1AW": httpx.ConnectError("no route")})
    b = FakeProvider("b", {"W1AW": httpx.ConnectError("no route")})
    resolver = Resolver([a, b], LookupCache(tmp_path), guard_for())

    await drain(resolver, ["W1AW"])
    assert resolver.cache.get("W1AW") is None
    assert not resolver.cache.knows("W1AW")
    assert resolver.failed == 1


@pytest.mark.asyncio
async def test_everyone_declining_does_cache_a_miss(tmp_path):
    """Genuinely not on file is a fact worth remembering, unlike a failure."""
    a = FakeProvider("a", {}, offline=True)
    b = FakeProvider("b", {})
    resolver = Resolver([a, b], LookupCache(tmp_path), guard_for())

    await drain(resolver, ["ZZ9ZZ"])
    assert resolver.cache.knows("ZZ9ZZ")
    assert resolver.cache.get("ZZ9ZZ") == {}


@pytest.mark.asyncio
async def test_wan_down_stops_waiting_on_network_providers(tmp_path):
    """The POTA case: keep resolving from disk instead of timing out per callsign."""
    local = FakeProvider("local", {"W1AW": "ARRL", "K0ABC": "Jane"}, offline=True)
    net = FakeProvider("net", {}, hosts=())
    net._answers = dict.fromkeys(
        ["DL1ABC", "G0XYZ", "F5ABC"], httpx.ConnectError("network unreachable")
    )
    resolver = Resolver([local, net], LookupCache(tmp_path), guard_for())

    # Enough foreign callsigns to trip the offline threshold.
    await drain(resolver, ["DL1ABC", "G0XYZ", "F5ABC"])
    assert resolver.network_is_down
    asked_before = len(net.asked)

    # Local calls still resolve, and the dead provider is no longer consulted.
    await drain(resolver, ["W1AW", "K0ABC"])
    assert len(net.asked) == asked_before
    assert resolver.cache.get("W1AW")["source"] == "local"


@pytest.mark.asyncio
async def test_one_failure_is_a_blip_not_an_outage(tmp_path):
    """Marking the network down on a single timeout would make a cluster flap."""
    net = FakeProvider("net", {"A": httpx.ConnectError("blip")})
    resolver = Resolver([net], LookupCache(tmp_path), guard_for())
    await drain(resolver, ["A"])
    assert OFFLINE_AFTER_FAILURES > 1
    assert not resolver.network_is_down


@pytest.mark.asyncio
async def test_network_coming_back_clears_the_offline_state(tmp_path):
    net = FakeProvider("net", dict.fromkeys(["A", "B"], httpx.ConnectError("down")))
    resolver = Resolver([net], LookupCache(tmp_path), guard_for())
    await drain(resolver, ["A", "B"])
    assert resolver.network_is_down

    resolver._offline_until = 0.0  # the retry window elapsing
    net._answers = {"C": "back"}
    await drain(resolver, ["C"])
    assert not resolver.network_is_down


@pytest.mark.asyncio
async def test_a_refused_provider_does_not_disable_the_working_one(tmp_path):
    """A blocked network provider must not take the offline half down with it."""
    local = FakeProvider("local", {"W1AW": "ARRL"}, offline=True)
    net = FakeProvider("net", {}, hosts=("blocked.example",))
    resolver = Resolver([local, net], LookupCache(tmp_path), EgressGuard.build(set(), set()))

    assert resolver._allowed() is True
    assert [p.name for p in resolver.providers] == ["local"]


@pytest.mark.asyncio
async def test_offline_lookups_are_not_rate_limited(tmp_path):
    """Sleeping a second per callsign against local SQLite would be absurd."""
    import time

    local = FakeProvider("local", {f"K{i}ABC": "x" for i in range(8)}, offline=True)
    resolver = Resolver([local], LookupCache(tmp_path), guard_for())

    started = time.monotonic()
    await drain(resolver, [f"K{i}ABC" for i in range(8)])
    assert time.monotonic() - started < 1.0
    assert resolver.resolved == 8


@pytest.mark.asyncio
async def test_snapshot_reports_the_chain(tmp_path):
    local = FakeProvider("local", {"W1AW": "ARRL"}, offline=True)
    net = FakeProvider("net", {})
    resolver = Resolver([local, net], LookupCache(tmp_path), guard_for())
    await drain(resolver, ["W1AW"])

    snap = resolver.snapshot()
    assert [p["name"] for p in snap["providers"]] == ["local", "net"]
    assert snap["offline_capable"] is True
    assert snap["resolved_by"] == {"local": 1}


# --- the cache, offline ---------------------------------------------------
def stale_entry(cache, callsign, hours):
    from datetime import UTC, datetime, timedelta

    when = datetime.now(UTC) - timedelta(hours=hours)
    cache._entries[callsign] = {
        "cached_at": when.isoformat().replace("+00:00", "Z"),
        "result": LookupResult(callsign=callsign, source="qrz", name="Jane").to_dict(),
    }


def test_stale_hits_are_published_and_flagged(tmp_path):
    """A month-old licence record beats a blank panel in a field."""
    cache = LookupCache(tmp_path, ttl_hours=720)
    stale_entry(cache, "W1AW", hours=1000)

    hits = cache.hits()
    assert "W1AW" in hits
    assert hits["W1AW"]["stale"] is True
    assert hits["W1AW"]["age_hours"] >= 1000


def test_fresh_hits_are_not_flagged(tmp_path):
    cache = LookupCache(tmp_path, ttl_hours=720)
    stale_entry(cache, "W1AW", hours=1)
    assert "stale" not in cache.hits()["W1AW"]


def test_serve_stale_can_be_turned_off(tmp_path):
    cache = LookupCache(tmp_path, ttl_hours=720, serve_stale=False)
    stale_entry(cache, "W1AW", hours=1000)
    assert cache.hits() == {}


def test_a_stale_entry_is_still_refetched(tmp_path):
    """Publishing it must not stop us asking again when we can."""
    cache = LookupCache(tmp_path, ttl_hours=720)
    stale_entry(cache, "W1AW", hours=1000)
    assert not cache.knows("W1AW")
    assert "W1AW" in cache.hits()


def test_eviction_keeps_stale_hits_over_expired_misses(tmp_path):
    """The offline answer is the thing worth keeping when space runs short."""
    cache = LookupCache(tmp_path, ttl_hours=1, max_entries=2)
    stale_entry(cache, "W1AW", hours=500)
    cache._entries["MISS1"] = {"cached_at": "2020-01-01T00:00:00Z", "miss": True}
    cache._entries["MISS2"] = {"cached_at": "2020-01-02T00:00:00Z", "miss": True}
    cache.put("K0ABC", LookupResult(callsign="K0ABC", source="qrz"))

    assert "W1AW" in cache._entries
    assert "MISS1" not in cache._entries


def test_stats_report_offline_readiness(tmp_path):
    cache = LookupCache(tmp_path, ttl_hours=720)
    stale_entry(cache, "W1AW", hours=1000)
    stats = cache.stats()
    assert stats["stale_served"] == 1
    assert stats["serve_stale"] is True


def test_import_memory_does_not_scale_with_the_database(tmp_path):
    """The import must stream, not buffer. This is a Pi-or-not property.

    An earlier version collected every record into a dict and wrote the database
    at the end: ~770 bytes per licence, about 620 MB at the real 800,000-licence
    scale, which is more RAM than a Pi Zero has. Streaming holds one batch, so
    peak is flat.

    The bound here is chosen to sit well below what buffering this many records
    would cost and well above what streaming does, so it discriminates between
    the two designs rather than measuring noise.
    """
    import tracemalloc

    count = 30_000
    src = archive(
        tmp_path,
        [hd(f"K{i:07d}") for i in range(count)],
        [en(f"K{i:07d}", first=f"FIRST{i}", last=f"LASTNAME{i}") for i in range(count)],
        [am(f"K{i:07d}") for i in range(count)],
    )

    tracemalloc.start()
    stats = build_index(src, tmp_path / "uls.sqlite3")
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    assert stats.indexed == count
    assert peak < 12_000_000, f"peak {peak / 1e6:.0f} MB suggests the import is buffering"


def test_expired_licences_do_not_gain_names_from_a_later_pass(tmp_path):
    """The status filter has to hold across all three passes, not just the first.

    EN and AM update rows that exist, so an entity record for an expired licence
    updates nothing. Worth pinning: switching those to INSERT OR REPLACE would
    silently resurrect every expired licence in the country.
    """
    src = archive(
        tmp_path,
        [hd("W1AW"), hd("K0DEAD", status="E")],
        [en("W1AW"), en("K0DEAD", first="GHOST", last="RECORD")],
        [am("W1AW"), am("K0DEAD")],
    )
    db = tmp_path / "uls.sqlite3"
    stats = build_index(src, db)
    assert stats.indexed == 1
    index = UlsIndex(db)
    assert index.lookup("K0DEAD") is None
    index.close()
