# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""The about card, and the source manifest the header's honesty rests on."""

import re

from hammunition_hill import __version__
from hammunition_hill.about import about_payload, publish_about
from hammunition_hill.cli import _publish_sources
from hammunition_hill.config import Config, ServerConfig, SourceConfig
from hammunition_hill.snapshot import read_snapshot


def config(tmp_path, sources=()):
    return Config(
        server=ServerConfig(),
        sources=tuple(sources),
        data_dir=tmp_path / "data",
        web_dir=tmp_path / "web",
    )


# --- about ---------------------------------------------------------------
def every_string(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for v in value.values():
            yield from every_string(v)
    elif isinstance(value, (list, tuple)):
        for v in value:
            yield from every_string(v)


def test_about_names_the_essentials():
    about = about_payload()
    assert about["project"]["version"] == __version__
    assert about["project"]["repo"] == "https://github.com/ChiefGyk3D/hammunition-hill"
    assert about["author"]["support"]["url"] == "https://support.chiefgyk3d.com"
    assert len(about["author"]["socials"]) >= 10


def test_every_about_url_is_https():
    for text in every_string(about_payload()):
        for url in re.findall(r"[a-z]+://\S+", text):
            assert url.startswith("https://"), f"about card carries a non-https URL: {url}"


def test_the_about_card_carries_no_payment_addresses():
    """Link to the support page; never cache what is on it.

    An address copied into a repository goes stale the day it rotates and
    misdirects money until someone notices. The support page is the only copy
    the author can correct, so the card must point there and carry nothing
    that looks like an address itself. Patterns cover BTC (legacy and bech32),
    EVM, and the long base58 shapes XMR and SOL use.
    """
    address = re.compile(
        r"\b(0x[0-9a-fA-F]{40}|bc1[a-z0-9]{25,}|[13][a-km-zA-HJ-NP-Z1-9]{25,34}"
        r"|[1-9A-HJ-NP-Za-km-z]{43,})\b"
    )
    for text in every_string(about_payload()):
        assert not address.search(text), f"about card appears to embed an address: {text!r}"


def test_about_publishes_as_a_snapshot(tmp_path):
    cfg = config(tmp_path)
    publish_about(cfg)
    snapshot = read_snapshot(cfg.data_dir, "about")
    assert snapshot["data"]["project"]["name"] == "Hammunition Hill"


# --- the source manifest -------------------------------------------------
def test_sources_manifest_lists_what_the_config_runs(tmp_path):
    cfg = config(
        tmp_path,
        sources=[
            SourceConfig(id="kindex", kind="swpc", url="https://example.gov/k.json"),
            SourceConfig(id="wsjtx", kind="wsjtx", url="udp://127.0.0.1:2237", local=True),
            SourceConfig(id="log", kind="adif", path=str(tmp_path / "log.adi")),
        ],
    )
    _publish_sources(cfg)
    rows = read_snapshot(cfg.data_dir, "sources")["data"]["configured"]

    assert [(r["id"], r["transport"]) for r in rows] == [
        ("kindex", "polled"),
        ("wsjtx", "stream"),
        ("log", "file"),
    ]


def test_sources_manifest_never_leaks_urls_or_options(tmp_path):
    """The LAN may see *that* a source runs, never what it talks to.

    A query string can carry an API key and options carry callsigns and file
    paths; the manifest exists so the header can count honestly, and counting
    needs none of that.
    """
    cfg = config(
        tmp_path,
        sources=[
            SourceConfig(
                id="secretive",
                kind="swpc",
                url="https://example.gov/data?apikey=hunter2",
                options={"callsign": "N0CALL"},
            ),
        ],
    )
    _publish_sources(cfg)
    snapshot = read_snapshot(cfg.data_dir, "sources")

    row = snapshot["data"]["configured"][0]
    assert set(row) == {"id", "kind", "interval", "transport"}
    flattened = str(snapshot)
    assert "hunter2" not in flattened
    assert "N0CALL" not in flattened
