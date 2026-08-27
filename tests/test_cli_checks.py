# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""The two CLI behaviours CI depends on, and one trap it exposed."""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest

from hammunition_hill.cli import _web_dir_problem, main
from hammunition_hill.config import parse_config

ROOT = Path(__file__).resolve().parents[1]


def write_config(tmp_path: Path, *, web_dir: Path | None = None, extra: str = "") -> Path:
    web = web_dir if web_dir is not None else ROOT / "web"
    path = tmp_path / "config.toml"
    path.write_text(
        f"""
[server]
host = "127.0.0.1"
port = 8099

[station]
callsign = "N0CALL"
grid = "DM79"

[paths]
data_dir = "{tmp_path / "data"}"
web_dir = "{web}"

[[sources]]
id = "hamqsl"
kind = "hamqsl"
url = "https://www.hamqsl.com/solarxml.php"
{extra}
""",
        encoding="utf-8",
    )
    return path


# --- the packaging trap ---------------------------------------------------
def test_missing_web_dir_is_detected(tmp_path):
    """pip install gives you the CLI and no web/. That must not be silent.

    Without this the symptom is a dashboard that 404s everything, with nothing
    anywhere saying why -- and the cause (the wheel does not carry web assets)
    is not something a user could reasonably deduce.
    """
    config = parse_config(
        tomllib.loads(write_config(tmp_path, web_dir=tmp_path / "absent").read_text()),
        base_dir=tmp_path,
    )
    problem = _web_dir_problem(config)
    assert problem is not None
    assert "absent" in problem


def test_web_dir_without_index_is_detected(tmp_path):
    """A directory that exists but is not a dashboard is its own failure mode."""
    empty = tmp_path / "web"
    empty.mkdir()
    config = parse_config(
        tomllib.loads(write_config(tmp_path, web_dir=empty).read_text()), base_dir=tmp_path
    )
    assert "index.html" in (_web_dir_problem(config) or "")


def test_web_dir_without_panel_index_is_detected(tmp_path):
    """index.html alone renders a shell with no panels."""
    partial = tmp_path / "web"
    partial.mkdir()
    (partial / "index.html").write_text("<h1>hi</h1>")
    config = parse_config(
        tomllib.loads(write_config(tmp_path, web_dir=partial).read_text()), base_dir=tmp_path
    )
    assert "panels/index.json" in (_web_dir_problem(config) or "")


def test_the_shipped_web_dir_is_complete():
    config = parse_config(
        {"paths": {"web_dir": str(ROOT / "web")}, "sources": []}, base_dir=ROOT
    )
    assert _web_dir_problem(config) is None


def test_check_exits_nonzero_without_a_dashboard(tmp_path, capsys):
    config_path = write_config(tmp_path, web_dir=tmp_path / "absent")
    assert main(["--config", str(config_path), "--offline", "check"]) == 1
    assert "clone" in capsys.readouterr().err


def test_serve_refuses_without_a_dashboard(tmp_path, capsys):
    """Refusing to start beats binding a port and serving nothing."""
    config_path = write_config(tmp_path, web_dir=tmp_path / "absent")
    assert main(["--config", str(config_path), "serve"]) == 1
    assert "cannot serve" in capsys.readouterr().err


# --- offline check --------------------------------------------------------
def test_offline_check_makes_no_dns_calls(tmp_path, capsys):
    """CI must not depend on NOAA's resolver being healthy.

    The conftest guard blocks outbound network for every test, so a check that
    still resolved would raise here rather than quietly passing -- this asserts
    the flag's whole reason for existing.
    """
    config_path = write_config(tmp_path)
    assert main(["--config", str(config_path), "--offline", "check"]) == 0
    output = capsys.readouterr().out
    assert "offline" in output
    assert "hamqsl" in output


def test_offline_check_still_catches_a_host_off_the_allowlist(tmp_path, capsys):
    """Skipping DNS must not mean skipping the allowlist.

    A source whose host is not derivable from config would be a real config
    error, and offline mode has to keep finding it -- otherwise the flag trades
    a flaky check for a useless one.
    """
    from hammunition_hill.cli import _check
    from hammunition_hill.egress import EgressGuard
    from hammunition_hill.enrich import Enricher, Station
    from hammunition_hill.prefix import PrefixTable

    config = parse_config(
        tomllib.loads(write_config(tmp_path).read_text()), base_dir=tmp_path
    )
    table = PrefixTable(None)
    enricher = Enricher(table, Station.from_config({}, table))
    # A guard built with an empty allowlist stands in for a config whose
    # allowlist and sources have drifted apart.
    empty_guard = EgressGuard.build(set(), set())
    object.__setattr__(config, "sources", config.sources)

    assert _check(config, empty_guard, enricher, offline=True) == 0  # allowlist is derived
    assert "hamqsl" in capsys.readouterr().out


@pytest.mark.parametrize("command", ["check", "serve"])
def test_unknown_config_path_is_a_clear_error(command, tmp_path, capsys):
    assert main(["--config", str(tmp_path / "nope.toml"), command]) == 2
    assert "nope.toml" in capsys.readouterr().err
