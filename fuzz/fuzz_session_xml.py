# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Fuzz the HamQTH and QRZ XML responses.

Both providers log in, get a session key and query by callsign; their answers
are XML from a third party, parsed with defusedxml. The target feeds the same
bytes to each provider's parse step (`DefusedET.fromstring` then the session,
result and expiry readers). A document that does not parse is the documented
`LookupError`.
"""

import sys

import atheris

with atheris.instrument_imports():
    from hammunition_hill.lookup.base import LookupError as LookupFailure
    from hammunition_hill.lookup.session_xml import DefusedET, HamQthProvider, QrzProvider

SEEDS = [
    b"",
    b'<?xml version="1.0"?><HamQTH xmlns="https://www.hamqth.com"><session><session_id>abc</session_id></session></HamQTH>',
    b"<HamQTH><search><callsign>N0CALL</callsign><nick>Pat</nick><grid>FN31pr</grid></search></HamQTH>",
    b'<QRZDatabase xmlns="http://xmldata.qrz.com"><Session><Key>k</Key></Session><Callsign><call>N0CALL</call><fname>A</fname><name>B</name></Callsign></QRZDatabase>',
    b"<Session><Error>Session Timeout</Error></Session>",
]

import _support

_TAGS = [
    "HamQTH",
    "session",
    "session_id",
    "search",
    "callsign",
    "nick",
    "adr_name",
    "grid",
    "country",
    "us_state",
    "qth",
    "QRZDatabase",
    "Session",
    "Key",
    "Callsign",
    "call",
    "fname",
    "name",
    "state",
    "class",
    "expdate",
    "Error",
    "Count",
]
_PROVIDERS = (HamQthProvider("N0CALL", "x"), QrzProvider("N0CALL", "x"))


def TestOneInput(data: bytes) -> None:
    fdp = atheris.FuzzedDataProvider(data)
    if fdp.ConsumeBool():
        text = _support.xml_text(fdp, _TAGS)
    else:
        text = fdp.ConsumeBytes(fdp.remaining_bytes()).decode("utf-8", errors="replace")
    try:
        root = DefusedET.fromstring(text)
    except Exception:  # _parse() catches broadly: defusedxml raises several types
        return  # the documented `XML parse failed` path
    for provider in _PROVIDERS:
        try:
            provider._session_from(root)
            provider._result_from(root, "N0CALL")
            provider._expired(root)
        except LookupFailure:
            pass  # the provider's own refusal is the contract; anything else propagates


if __name__ == "__main__":
    atheris.Setup(sys.argv, TestOneInput)
    atheris.Fuzz()
