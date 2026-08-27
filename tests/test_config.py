# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import pytest

from hammunition_hill.config import ConfigError, parse_config


def cfg(**overrides):
    base = {
        "server": {"host": "127.0.0.1", "port": 8073},
        "sources": [
            {"id": "hamqsl", "kind": "hamqsl", "url": "https://www.hamqsl.com/solarxml.php"}
        ],
    }
    base.update(overrides)
    return base


def test_minimal_config(tmp_path):
    config = parse_config(cfg(), base_dir=tmp_path)
    assert config.server.is_loopback_only
    assert config.sources[0].id == "hamqsl"
    assert config.sources[0].host == "www.hamqsl.com"


def test_defaults_to_loopback(tmp_path):
    assert parse_config({}, base_dir=tmp_path).server.is_loopback_only


def test_lan_bind_is_detected(tmp_path):
    config = parse_config(cfg(server={"host": "0.0.0.0", "port": 8073}), base_dir=tmp_path)
    assert not config.server.is_loopback_only


def test_duplicate_ids_rejected(tmp_path):
    raw = cfg(
        sources=[
            {"id": "dup", "kind": "rss", "url": "https://a.example/f"},
            {"id": "dup", "kind": "rss", "url": "https://b.example/f"},
        ]
    )
    with pytest.raises(ConfigError, match="duplicate id"):
        parse_config(raw, base_dir=tmp_path)


def test_id_must_be_filename_safe(tmp_path):
    """Ids become filenames under the data directory."""
    raw = cfg(sources=[{"id": "../../etc/passwd", "kind": "rss", "url": "https://a.example/f"}])
    with pytest.raises(ConfigError, match="alphanumeric"):
        parse_config(raw, base_dir=tmp_path)


def test_interval_floor_protects_upstreams(tmp_path):
    raw = cfg(sources=[{"id": "fast", "kind": "rss", "url": "https://a.example/f", "interval": 5}])
    with pytest.raises(ConfigError, match="below the 30s floor"):
        parse_config(raw, base_dir=tmp_path)


def test_missing_required_key(tmp_path):
    with pytest.raises(ConfigError, match="missing required key 'kind'"):
        parse_config(cfg(sources=[{"id": "x", "url": "https://a.example/f"}]), base_dir=tmp_path)


# --- url vs path --------------------------------------------------------
def test_a_source_needs_either_url_or_path(tmp_path):
    with pytest.raises(ConfigError, match="exactly one of url or path"):
        parse_config(cfg(sources=[{"id": "x", "kind": "rss"}]), base_dir=tmp_path)


def test_a_source_cannot_have_both(tmp_path):
    raw = cfg(
        sources=[{"id": "x", "kind": "adif", "url": "https://a.example/f", "path": "log.adi"}]
    )
    with pytest.raises(ConfigError, match="exactly one of url or path"):
        parse_config(raw, base_dir=tmp_path)


def test_file_sources_are_recognized(tmp_path):
    raw = cfg(sources=[{"id": "log", "kind": "adif", "path": "~/log.adi", "interval": 300}])
    source = parse_config(raw, base_dir=tmp_path).sources[0]
    assert source.is_file_source
    assert source.host == ""


def test_file_sources_add_nothing_to_the_allowlist(tmp_path):
    """A local file read must not widen egress policy."""
    raw = cfg(sources=[{"id": "log", "kind": "adif", "path": "~/log.adi"}])
    allowed, local = parse_config(raw, base_dir=tmp_path).allowlist()
    assert allowed == set()
    assert local == set()


def test_cty_dat_path_is_expanded(tmp_path):
    config = parse_config(cfg(log={"cty_dat": "~/cty.dat"}), base_dir=tmp_path)
    assert config.cty_dat is not None
    assert "~" not in str(config.cty_dat)


def test_cty_dat_defaults_to_none(tmp_path):
    assert parse_config(cfg(), base_dir=tmp_path).cty_dat is None


def test_allowlist_separates_local_sources(tmp_path):
    raw = cfg(
        sources=[
            {"id": "remote", "kind": "rss", "url": "https://a.example/f"},
            {"id": "pistar", "kind": "rss", "url": "http://pi-star.local/f", "local": True},
        ]
    )
    allowed, local = parse_config(raw, base_dir=tmp_path).allowlist()
    assert allowed == {"a.example", "pi-star.local"}
    assert local == {"pi-star.local"}


def test_embed_hosts_join_the_allowlist(tmp_path):
    raw = cfg(embeds={"allow_hosts": ["radar.weather.gov"]})
    allowed, _ = parse_config(raw, base_dir=tmp_path).allowlist()
    assert "radar.weather.gov" in allowed


def test_port_range_validated(tmp_path):
    with pytest.raises(ConfigError, match="out of range"):
        parse_config(cfg(server={"port": 99999}), base_dir=tmp_path)
