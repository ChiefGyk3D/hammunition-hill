# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Opaque imagery: the gate between an upstream's bytes and our origin.

The security case is the whole reason this feature waited: an upstream that
serves SVG instead of PNG is handing us a document that can run script, now on
an origin where the CSP trusts 'self'. Everything here flows from that --
identify the payload by its own bytes, never the header, and refuse anything
that is not a raster.
"""

from __future__ import annotations

import json

import httpx
import pytest

from hammunition_hill.collector import run_tile_once
from hammunition_hill.config import Config, ImageryTile, ServerConfig
from hammunition_hill.egress import EgressGuard
from hammunition_hill.tiles import (
    MAX_TILE_BYTES,
    TileError,
    sniff,
    write_tile,
    write_tile_failure,
)

PNG = b"\x89PNG\r\n\x1a\n" + b"x" * 64
GIF = b"GIF89a" + b"x" * 64
JPG = b"\xff\xd8\xff\xe0" + b"x" * 64
WEBP = b"RIFF\x00\x00\x00\x00WEBP" + b"x" * 64
SVG = b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>'


# --- sniffing ----------------------------------------------------------------


@pytest.mark.parametrize(
    ("payload", "extension"),
    [(PNG, "png"), (GIF, "gif"), (JPG, "jpg"), (WEBP, "webp")],
)
def test_rasters_are_identified_by_their_bytes(payload, extension):
    assert sniff(payload) == extension


def test_svg_is_rejected_by_name():
    """The finding, not a puzzle: the message says the upstream sent SVG."""
    with pytest.raises(TileError) as caught:
        sniff(SVG)
    assert "SVG" in str(caught.value)
    assert "script" in str(caught.value)


@pytest.mark.parametrize("junk", [b"", b"hello", b"<html><body>", b"%PDF-1.7", b"\x00" * 40])
def test_everything_else_is_rejected(junk):
    with pytest.raises(TileError):
        sniff(junk)


def test_the_header_is_never_consulted():
    """sniff takes bytes and nothing else; this pins that signature.

    The upstream's Content-Type is the one thing an evil or broken upstream
    controls, so the function is deliberately unable to see it.
    """
    import inspect

    parameters = list(inspect.signature(sniff).parameters)
    assert parameters == ["payload"]


# --- writing -----------------------------------------------------------------


def test_write_then_format_change_leaves_one_image(tmp_path):
    write_tile(tmp_path, "radar", PNG, "png")
    assert (tmp_path / "tiles" / "radar.png").exists()

    meta = write_tile(tmp_path, "radar", GIF, "gif")
    assert (tmp_path / "tiles" / "radar.gif").exists()
    assert not (tmp_path / "tiles" / "radar.png").exists(), (
        "an upstream switching formats must not leave both files behind"
    )
    assert meta["src"] == "data/tiles/radar.gif"
    assert meta["content_type"] == "image/gif"

    sidecar = json.loads((tmp_path / "tiles" / "radar.json").read_text())
    assert sidecar["src"] == "data/tiles/radar.gif"
    assert "error" not in sidecar


def test_a_failure_keeps_the_last_good_image(tmp_path):
    """A stale radar frame with an honest error beats a broken-image icon."""
    write_tile(tmp_path, "radar", PNG, "png")
    write_tile_failure(tmp_path, "radar", "HTTPError: 503")

    assert (tmp_path / "tiles" / "radar.png").exists()
    sidecar = json.loads((tmp_path / "tiles" / "radar.json").read_text())
    assert sidecar["src"] == "data/tiles/radar.png", "the last good image is still named"
    assert sidecar["error"] == "HTTPError: 503"


# --- the collector cycle -----------------------------------------------------


def make_config(tmp_path, url, mode="opaque"):
    return Config(
        server=ServerConfig(host="127.0.0.1", port=8073),
        sources=(),
        data_dir=tmp_path,
        web_dir=tmp_path,
        imagery=(ImageryTile(id="t", name="T", url=url, mode=mode),),
    )


def transport(payload, content_type="image/png", status=200):
    def respond(request):
        return httpx.Response(status, content=payload, headers={"content-type": content_type})

    return httpx.MockTransport(respond)


async def cycle(tmp_path, payload, *, content_type="image/png", status=200, host="tiles.example"):
    config = make_config(tmp_path, f"https://{host}/x.png")
    # Marked local so the guard skips DNS: the conftest network guard refuses
    # real resolution, which is the same pattern the collector tests use.
    guard = EgressGuard.build({host}, {host})
    async with httpx.AsyncClient(transport=transport(payload, content_type, status)) as client:
        return await run_tile_once(client, guard, config.imagery[0], config)


async def test_a_good_tile_lands_on_disk(tmp_path):
    assert await cycle(tmp_path, PNG) is True
    assert (tmp_path / "tiles" / "t.png").read_bytes() == PNG


async def test_a_lying_content_type_does_not_matter(tmp_path):
    """image/png in the header, SVG in the body: the body loses."""
    assert await cycle(tmp_path, SVG, content_type="image/png") is False
    assert not (tmp_path / "tiles" / "t.png").exists()
    sidecar = json.loads((tmp_path / "tiles" / "t.json").read_text())
    assert "SVG" in sidecar["error"]


async def test_the_size_cap_stops_the_download(tmp_path):
    huge = PNG + b"\x00" * MAX_TILE_BYTES
    assert await cycle(tmp_path, huge) is False
    assert not (tmp_path / "tiles" / "t.png").exists()


async def test_an_unlisted_host_is_refused_by_the_guard(tmp_path):
    config = make_config(tmp_path, "https://evil.example/x.png")
    guard = EgressGuard.build({"tiles.example"}, set())
    async with httpx.AsyncClient(transport=transport(PNG)) as client:
        assert await run_tile_once(client, guard, config.imagery[0], config) is False
    sidecar = json.loads((tmp_path / "tiles" / "t.json").read_text())
    assert "EgressDenied" in sidecar["error"]


# --- config wiring -----------------------------------------------------------


def test_an_opaque_host_moves_from_the_csp_to_the_allowlist(tmp_path):
    """The whole payoff, asserted from both sides.

    Direct: the browser fetches, so the CSP names the host and the collector
    may not reach it. Opaque: exactly inverted. A host in both lists would be
    a tile paid for twice; a host in neither is a tile that cannot load.
    """
    direct = make_config(tmp_path, "https://tiles.example/x.png", mode="direct")
    allowed, _ = direct.allowlist()
    assert "tiles.example" not in allowed
    assert "tiles.example" in direct.csp_hosts()

    opaque = make_config(tmp_path, "https://tiles.example/x.png", mode="opaque")
    allowed, _ = opaque.allowlist()
    assert "tiles.example" in allowed
    assert "tiles.example" not in opaque.csp_hosts()


def test_an_unknown_mode_is_refused_with_both_options(tmp_path):
    from hammunition_hill.config import ConfigError, load_config

    config = tmp_path / "config.toml"
    config.write_text(
        '[server]\nhost = "127.0.0.1"\nport = 8073\n'
        '[station]\ncallsign = "N0CALL"\ngrid = "FN31pr"\n'
        '[[imagery]]\nid = "x"\nname = "X"\nurl = "https://tiles.example/x.png"\n'
        'mode = "proxy"\n'
    )
    with pytest.raises(ConfigError) as caught:
        load_config(config)
    assert "direct" in str(caught.value) and "opaque" in str(caught.value)
