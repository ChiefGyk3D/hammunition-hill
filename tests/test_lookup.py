# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Callsign lookup: providers, cache, and the scheduled resolver."""

import httpx
import pytest

from hammunition_hill.config import parse_config
from hammunition_hill.egress import EgressGuard
from hammunition_hill.enrich import SEEN_CALLSIGN_LIMIT, Enricher, Station
from hammunition_hill.lookup import (
    CredentialsRequired,
    build_provider,
    provider_hosts,
)
from hammunition_hill.lookup.base import LookupResult
from hammunition_hill.lookup.cache import LookupCache
from hammunition_hill.lookup.callook import CallookProvider
from hammunition_hill.lookup.resolver import Resolver
from hammunition_hill.lookup.session_xml import HamQthProvider, QrzProvider
from hammunition_hill.prefix import PrefixTable

CALLOOK_OK = """{
 "status":"VALID","type":"PERSON","callsign":"W1AW",
 "name":"ARRL HQ OPERATORS CLUB",
 "address":{"line1":"225 MAIN ST","line2":"NEWINGTON, CT 06111"},
 "location":{"latitude":"41.714","longitude":"-72.727","gridsquare":"FN31pr"},
 "current":{"callsign":"W1AW","operClass":"CLUB"},
 "otherInfo":{"expiryDate":"2030-01-01","frn":"0001234567"}
}"""

CALLOOK_INVALID = '{"status":"INVALID"}'


def client_for(body, status=200, content_type="application/json"):
    transport = httpx.MockTransport(
        lambda request: httpx.Response(status, text=body, headers={"content-type": content_type})
    )
    return httpx.AsyncClient(transport=transport)


# --- registry -----------------------------------------------------------
def test_none_builds_no_provider():
    assert build_provider("none", None, None) is None
    assert build_provider("", None, None) is None


def test_callook_needs_no_credentials():
    assert build_provider("callook", None, None) is not None


@pytest.mark.parametrize("name", ["hamqth", "qrz"])
def test_account_providers_refuse_without_credentials(name):
    with pytest.raises(CredentialsRequired, match="username and password"):
        build_provider(name, None, None)


@pytest.mark.parametrize("name", ["hamqth", "qrz"])
def test_account_providers_build_with_credentials(name):
    assert build_provider(name, "user", "pass") is not None


def test_unknown_provider_lists_the_options():
    with pytest.raises(ValueError, match="available: none, callook, fcc_uls, hamqth, qrz"):
        build_provider("nonsense", None, None)


def test_fcc_uls_is_built_now(tmp_path):
    """It used to be in PLANNED with an error saying so. It is real now."""
    provider = build_provider("fcc_uls", None, None, data_dir=tmp_path)
    assert provider is not None
    assert provider.offline is True
    # It grants the collector no reach: the import is a separate command.
    assert provider.hosts == ()


@pytest.mark.parametrize("name,host", [
    ("callook", "callook.info"),
    ("hamqth", "www.hamqth.com"),
    ("qrz", "xmldata.qrz.com"),
])
def test_providers_declare_their_hosts(name, host):
    """A provider cannot reach anywhere it has not declared."""
    assert provider_hosts(name) == (host,)


def test_none_declares_no_hosts():
    assert provider_hosts("none") == ()


# --- callook ------------------------------------------------------------
async def test_callook_parses_a_valid_licence():
    async with client_for(CALLOOK_OK) as client:
        result = await CallookProvider().resolve(client, "w1aw")
    assert result.callsign == "W1AW"
    assert result.name == "ARRL HQ OPERATORS CLUB"
    assert result.grid == "FN31pr"
    assert result.license_class == "CLUB"
    assert result.country == "United States"
    assert result.source == "callook"


async def test_callook_returns_none_for_an_invalid_callsign():
    """Not-on-file is an answer, not an error."""
    async with client_for(CALLOOK_INVALID) as client:
        assert await CallookProvider().resolve(client, "ZZ9ZZZ") is None


async def test_callook_rejects_non_json():
    from hammunition_hill.lookup.base import LookupError

    async with client_for("<html>nope</html>", content_type="text/html") as client:
        with pytest.raises(LookupError, match="not JSON"):
            await CallookProvider().resolve(client, "W1AW")


# --- session providers ---------------------------------------------------
HAMQTH_SESSION = (
    '<?xml version="1.0"?><HamQTH><session>'
    "<session_id>abc123</session_id></session></HamQTH>"
)
HAMQTH_REJECTED = (
    '<?xml version="1.0"?><HamQTH><session><error>Wrong</error></session></HamQTH>'
)
HAMQTH_RESULT = (
    '<?xml version="1.0"?><HamQTH><search><callsign>ok1abc</callsign>'
    "<nick>Petr</nick><grid>JO70</grid><country>Czech Republic</country></search></HamQTH>"
)
QRZ_SESSION = '<?xml version="1.0"?><QRZDatabase><Session><Key>xyz789</Key></Session></QRZDatabase>'
QRZ_RESULT = (
    '<?xml version="1.0"?><QRZDatabase><Callsign><call>W1AW</call><fname>Hiram</fname>'
    "<name>Maxim</name><grid>FN31pr</grid><country>United States</country>"
    "<state>CT</state><class>E</class></Callsign></QRZDatabase>"
)


def scripted_client(responses):
    """Answers each request in order, so login-then-query can be tested."""
    calls = iter(responses)

    def handler(request):
        return httpx.Response(200, text=next(calls), headers={"content-type": "text/xml"})

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


async def test_hamqth_logs_in_then_queries():
    async with scripted_client([HAMQTH_SESSION, HAMQTH_RESULT]) as client:
        result = await HamQthProvider("user", "pass").resolve(client, "OK1ABC")
    assert result.callsign == "OK1ABC"
    assert result.name == "Petr"
    assert result.grid == "JO70"
    assert result.source == "hamqth"


async def test_qrz_logs_in_then_queries():
    async with scripted_client([QRZ_SESSION, QRZ_RESULT]) as client:
        result = await QrzProvider("user", "pass").resolve(client, "W1AW")
    assert result.name == "Hiram Maxim"
    assert result.state == "CT"
    assert result.license_class == "E"


async def test_a_rejected_login_is_an_error_not_a_silent_miss():
    from hammunition_hill.lookup.base import LookupError

    async with scripted_client([HAMQTH_REJECTED]) as client:
        with pytest.raises(LookupError, match="login rejected"):
            await HamQthProvider("user", "bad").resolve(client, "OK1ABC")


async def test_credentials_never_reach_the_result():
    async with scripted_client([QRZ_SESSION, QRZ_RESULT]) as client:
        result = await QrzProvider("secret-user", "secret-pass").resolve(client, "W1AW")
    rendered = str(result.to_dict())
    assert "secret-user" not in rendered
    assert "secret-pass" not in rendered


# --- cache ---------------------------------------------------------------
def result_for(call="W1AW"):
    return LookupResult(callsign=call, source="test", name="Someone")


def test_cache_roundtrip(tmp_path):
    cache = LookupCache(tmp_path)
    cache.put("W1AW", result_for())
    assert cache.get("W1AW")["name"] == "Someone"


def test_cache_is_case_insensitive(tmp_path):
    cache = LookupCache(tmp_path)
    cache.put("w1aw", result_for())
    assert cache.get("W1AW") is not None


def test_a_miss_is_remembered_as_an_empty_result(tmp_path):
    """So we do not ask again immediately for a callsign that is not on file."""
    cache = LookupCache(tmp_path)
    cache.put("ZZ9ZZZ", None)
    assert cache.get("ZZ9ZZZ") == {}
    assert cache.knows("ZZ9ZZZ") is True


def test_unknown_callsigns_are_not_known(tmp_path):
    assert LookupCache(tmp_path).knows("W1AW") is False


def test_entries_expire(tmp_path):
    cache = LookupCache(tmp_path, ttl_hours=0)
    cache.put("W1AW", result_for())
    assert cache.get("W1AW") is None


def test_cache_persists_across_instances(tmp_path):
    first = LookupCache(tmp_path)
    first.put("W1AW", result_for())
    first.save()

    second = LookupCache(tmp_path)
    second.load()
    assert second.get("W1AW")["name"] == "Someone"


def test_a_corrupt_cache_starts_empty(tmp_path):
    (tmp_path / "lookup_cache.json").write_text("{not json")
    cache = LookupCache(tmp_path)
    cache.load()
    assert cache.knows("W1AW") is False


def test_cache_is_bounded(tmp_path):
    cache = LookupCache(tmp_path, max_entries=10)
    for i in range(50):
        cache.put(f"W1AA{i}", result_for(f"W1AA{i}"))
    assert cache.stats()["entries"] <= 10


def test_only_fresh_hits_are_published(tmp_path):
    cache = LookupCache(tmp_path)
    cache.put("W1AW", result_for())
    cache.put("ZZ9ZZZ", None)
    hits = cache.hits()
    assert "W1AW" in hits
    assert "ZZ9ZZZ" not in hits


# --- resolver ------------------------------------------------------------
@pytest.fixture
def guard():
    return EgressGuard.build({"callook.info"}, set())


async def test_resolver_skips_what_is_already_cached(tmp_path, guard):
    cache = LookupCache(tmp_path)
    cache.put("W1AW", result_for())
    resolver = Resolver(CallookProvider(), cache, guard)

    async with client_for(CALLOOK_OK) as client:
        assert await resolver.resolve_batch(client, ["W1AW"]) == 0


async def test_resolver_respects_the_per_cycle_cap(tmp_path, guard):
    """A busy cluster must not become hundreds of requests to a free service."""
    cache = LookupCache(tmp_path)
    resolver = Resolver(CallookProvider(), cache, guard, max_per_cycle=3)

    async with client_for(CALLOOK_OK) as client:
        attempted = await resolver.resolve_batch(client, [f"W1AA{i}" for i in range(20)])
    assert attempted == 3


async def test_a_failed_lookup_is_not_cached(tmp_path, guard):
    """A rate limit or blip must not lock in a miss for a day."""
    cache = LookupCache(tmp_path)
    resolver = Resolver(CallookProvider(), cache, guard)

    async with client_for("<html>500</html>", content_type="text/html") as client:
        await resolver.resolve_batch(client, ["W1AW"])
    assert cache.knows("W1AW") is False
    assert resolver.failed == 1


async def test_resolver_refuses_a_provider_outside_the_allowlist(tmp_path):
    closed = EgressGuard.build(set(), set())
    resolver = Resolver(CallookProvider(), LookupCache(tmp_path), closed)
    assert resolver._allowed() is False


async def test_resolver_snapshot_shape(tmp_path, guard):
    cache = LookupCache(tmp_path)
    resolver = Resolver(CallookProvider(), cache, guard)
    async with client_for(CALLOOK_OK) as client:
        await resolver.resolve_batch(client, ["W1AW"])

    snapshot = resolver.snapshot()
    assert snapshot["provider"] == "callook"
    assert snapshot["results"]["W1AW"]["name"] == "ARRL HQ OPERATORS CLUB"
    assert snapshot["resolved"] == 1


# --- config --------------------------------------------------------------
def base_cfg(**lookup):
    return {"sources": [], "lookup": lookup} if lookup else {"sources": []}


def test_lookup_defaults_to_off(tmp_path):
    config = parse_config(base_cfg(), base_dir=tmp_path)
    assert config.lookup.enabled is False
    assert config.lookup.query_endpoint is False


def test_provider_hosts_join_the_allowlist(tmp_path):
    config = parse_config(base_cfg(provider="callook"), base_dir=tmp_path)
    allowed, _ = config.allowlist()
    assert "callook.info" in allowed


def test_no_provider_adds_no_hosts(tmp_path):
    allowed, _ = parse_config(base_cfg(), base_dir=tmp_path).allowlist()
    assert allowed == set()


def test_provider_name_is_normalized(tmp_path):
    config = parse_config(base_cfg(provider="  CallOok "), base_dir=tmp_path)
    assert config.lookup.provider == "callook"


# --- seen callsigns ------------------------------------------------------
def test_enricher_records_callsigns_from_spots():
    enricher = Enricher(PrefixTable(None), Station.from_config({"grid": "FN31pr"}))
    enricher.enrich_spot({"call": "JA1XYZ", "khz": 14074.0})
    assert "JA1XYZ" in enricher.seen_callsigns()


def test_seen_callsigns_are_newest_first():
    enricher = Enricher(PrefixTable(None), Station.from_config({}))
    for call in ("AAA", "BBB", "CCC"):
        enricher.note_callsign(call)
    assert enricher.seen_callsigns()[:3] == ["CCC", "BBB", "AAA"]


def test_reseeing_a_callsign_moves_it_to_the_front():
    enricher = Enricher(PrefixTable(None), Station.from_config({}))
    for call in ("AAA", "BBB", "AAA"):
        enricher.note_callsign(call)
    assert enricher.seen_callsigns()[0] == "AAA"
    assert len(enricher.seen_callsigns()) == 2


def test_seen_callsigns_are_bounded():
    """A contest weekend is a lot of callsigns."""
    enricher = Enricher(PrefixTable(None), Station.from_config({}))
    for i in range(SEEN_CALLSIGN_LIMIT + 500):
        enricher.note_callsign(f"W{i}ABC")
    assert len(enricher.seen_callsigns()) == SEEN_CALLSIGN_LIMIT


# --- the Element truthiness trap ------------------------------------------
def test_session_element_with_attributes_but_no_children_is_used():
    """`root.find(...) or root` was wrong here, in a way that reads as correct.

    An ElementTree element is falsy when it has no *child elements*. So for a
    response whose session element carries its data in attributes, or is simply
    empty, the `or` fired and the code searched the whole document instead of
    the element it had just found.

    Caught by CI on Python 3.12+, where the deprecation warning for this fires;
    3.11 is silent, which is why it survived. Python is also changing the
    truthiness to always-True, which would have flipped the behaviour a second
    time. `is None` is the only test that means the right thing in both.
    """
    from defusedxml import ElementTree as DefusedET

    from hammunition_hill.lookup.session_xml import _first

    # A session element that is empty of children: falsy today, truthy later.
    root = DefusedET.fromstring(
        '<HamQTH><session id="x"><session_id>abc123</session_id></session></HamQTH>'
    )
    found = _first(root, ".//{*}session")
    assert found.tag.endswith("session"), "must return the found element, not the root"

    empty = DefusedET.fromstring('<HamQTH><session id="x"/></HamQTH>')
    assert _first(empty, ".//{*}session") is not empty, "an empty match is still a match"

    absent = DefusedET.fromstring("<HamQTH><other/></HamQTH>")
    assert _first(absent, ".//{*}session") is absent, "no match falls back to root"


def test_no_source_file_tests_an_element_for_truth():
    """Whatever else changes, this pattern must not come back.

    It is silent on 3.11, a warning on 3.12+, and a behaviour change after that
    -- the worst combination for something a test suite might not exercise.
    """
    import ast
    from pathlib import Path

    offenders = []
    for path in sorted(Path("src").rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            # `x.find(...) or y` and `if x.find(...)` are both the same mistake.
            candidates = []
            if isinstance(node, ast.BoolOp):
                candidates = node.values
            elif isinstance(node, ast.If):
                candidates = [node.test]
            for value in candidates:
                call = value.operand if isinstance(value, ast.UnaryOp) else value
                if (
                    isinstance(call, ast.Call)
                    and isinstance(call.func, ast.Attribute)
                    and call.func.attr in ("find", "findall")
                ):
                    offenders.append(f"{path}:{node.lineno}")

    assert not offenders, (
        "these test an ElementTree result for truth instead of `is None`: "
        + ", ".join(offenders)
    )
