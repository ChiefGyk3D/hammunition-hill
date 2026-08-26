# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Feed content is untrusted input. It gets stripped before it reaches a snapshot."""

import pytest

from hammunition_hill.sources.rss import safe_link, to_text


def test_markup_is_stripped():
    assert to_text("<p>Hello <b>world</b></p>") == "Hello world"


def test_script_content_does_not_survive_as_markup():
    assert "<script>" not in to_text("<script>alert(1)</script>ok")


def test_entities_are_decoded_then_flattened():
    assert to_text("a &amp; b") == "a & b"


def test_whitespace_collapses():
    assert to_text("a\n\n   b\t c") == "a b c"


def test_long_text_is_truncated():
    assert len(to_text("x" * 5000, limit=100)) == 100


def test_empty_input():
    assert to_text(None) == ""


@pytest.mark.parametrize("scheme", ["javascript", "data", "file", "vbscript"])
def test_dangerous_link_schemes_are_dropped(scheme):
    assert safe_link(f"{scheme}:alert(1)") is None


@pytest.mark.parametrize("url", ["https://amsat.org/x", "http://amsat.org/x"])
def test_http_links_survive(url):
    assert safe_link(url) == url


def test_whitespace_padded_link_is_normalized():
    assert safe_link("  https://amsat.org/x  ") == "https://amsat.org/x"


# --- element text gathering --------------------------------------------
def _item(xml):
    from defusedxml import ElementTree

    return ElementTree.fromstring(xml)


def test_gather_collects_text_across_inline_markup():
    """Regression: findtext() stops at the first child element.

    A feed writing real markup inside <title> rather than escaped text used to
    lose everything from the first nested tag onward.
    """
    from hammunition_hill.sources.rss import gather

    node = _item("<item><title>AO-91 &amp; the <b>new</b> schedule</title></item>")
    assert to_text(gather(node, "title")) == "AO-91 & the new schedule"


def test_gather_handles_plain_text():
    from hammunition_hill.sources.rss import gather

    assert gather(_item("<item><title>Plain</title></item>"), "title") == "Plain"


def test_gather_returns_none_for_missing_element():
    from hammunition_hill.sources.rss import gather

    assert gather(_item("<item></item>"), "title") is None
