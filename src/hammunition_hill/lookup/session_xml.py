# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""HamQTH and QRZ, which share a shape.

Both authenticate with a username and password to get a session key, then query
with that key. Sessions expire, so both re-authenticate on the error the far end
sends when the key goes stale.

**Credentials are used to obtain a session key and go nowhere else.** They are
never written to a snapshot, never logged, and never sent to the browser -- the
panel only ever sees the resolved result.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx
from defusedxml import ElementTree as DefusedET

from ..sources.base import get_bounded
from .base import CredentialsRequired, LookupError, LookupResult

log = logging.getLogger(__name__)


def _strip_ns(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].lower()


def _fields(node: Any) -> dict[str, str]:
    """Child elements as a lowercase, namespace-free dict."""
    out: dict[str, str] = {}
    for child in node:
        text = (child.text or "").strip()
        if text:
            out[_strip_ns(child.tag)] = text
    return out


class _SessionXmlProvider:
    """Shared login-then-query machinery."""

    name = "session-xml"
    hosts: tuple[str, ...] = ()
    needs_credentials = True
    worldwide = True
    offline = False

    def __init__(self, username: str | None, password: str | None) -> None:
        if not username or not password:
            raise CredentialsRequired(
                f"{self.name} needs [lookup] username and password. "
                f"See docs/CALLSIGN-LOOKUP.md, or use a provider that needs no account."
            )
        self._username = username
        self._password = password
        self._session: str | None = None

    # --- subclass hooks --------------------------------------------------
    def _login_request(self) -> tuple[str, dict[str, str]]: ...
    def _session_from(self, root: Any) -> str | None: ...
    def _query_request(self, session: str, callsign: str) -> tuple[str, dict[str, str]]: ...
    def _result_from(self, root: Any, callsign: str) -> LookupResult | None: ...

    # --- shared ----------------------------------------------------------
    async def _parse(self, client: httpx.AsyncClient, url: str, params: dict[str, str]) -> Any:
        response = await get_bounded(client, httpx.URL(url).copy_merge_params(params))
        try:
            return DefusedET.fromstring(response.text)
        except Exception as exc:
            raise LookupError(f"{self.name}: XML parse failed ({exc})") from exc

    async def _login(self, client: httpx.AsyncClient) -> str:
        url, params = self._login_request()
        root = await self._parse(client, url, params)
        session = self._session_from(root)
        if not session:
            raise LookupError(f"{self.name}: login rejected — check username and password")
        log.info("%s: authenticated", self.name)
        return session

    async def resolve(self, client: httpx.AsyncClient, callsign: str) -> LookupResult | None:
        if self._session is None:
            self._session = await self._login(client)

        url, params = self._query_request(self._session, callsign)
        root = await self._parse(client, url, params)
        result = self._result_from(root, callsign)

        if result is None and self._expired(root):
            # Sessions time out. One retry with a fresh key, then give up --
            # a login loop against someone else's server is not acceptable.
            log.info("%s: session expired, re-authenticating", self.name)
            self._session = await self._login(client)
            url, params = self._query_request(self._session, callsign)
            root = await self._parse(client, url, params)
            result = self._result_from(root, callsign)

        return result

    def _expired(self, root: Any) -> bool:
        text = " ".join(node.text or "" for node in root.iter()).lower()
        return "session" in text and ("timeout" in text or "invalid" in text or "expired" in text)


class HamQthProvider(_SessionXmlProvider):
    """HamQTH -- free, worldwide, needs an account."""

    name = "hamqth"
    hosts = ("www.hamqth.com",)

    _URL = "https://www.hamqth.com/xml.php"

    def _login_request(self) -> tuple[str, dict[str, str]]:
        return self._URL, {"u": self._username, "p": self._password}

    def _session_from(self, root: Any) -> str | None:
        return _fields(root.find(".//{*}session") or root).get("session_id")

    def _query_request(self, session: str, callsign: str) -> tuple[str, dict[str, str]]:
        return self._URL, {
            "id": session,
            "callsign": callsign.lower(),
            "prg": "hammunition-hill",
        }

    def _result_from(self, root: Any, callsign: str) -> LookupResult | None:
        search = root.find(".//{*}search")
        if search is None:
            return None
        data = _fields(search)
        if not data:
            return None
        return LookupResult(
            callsign=(data.get("callsign") or callsign).upper(),
            source=self.name,
            name=data.get("nick") or data.get("adr_name"),
            grid=data.get("grid"),
            country=data.get("country"),
            state=data.get("us_state") or data.get("qth"),
        )


class QrzProvider(_SessionXmlProvider):
    """QRZ.com -- best coverage, needs a paid XML subscription."""

    name = "qrz"
    hosts = ("xmldata.qrz.com",)

    _URL = "https://xmldata.qrz.com/xml/current/"

    def _login_request(self) -> tuple[str, dict[str, str]]:
        return self._URL, {
            "username": self._username,
            "password": self._password,
            "agent": "hammunition-hill",
        }

    def _session_from(self, root: Any) -> str | None:
        return _fields(root.find(".//{*}Session") or root).get("key")

    def _query_request(self, session: str, callsign: str) -> tuple[str, dict[str, str]]:
        return self._URL, {"s": session, "callsign": callsign.upper()}

    def _result_from(self, root: Any, callsign: str) -> LookupResult | None:
        node = root.find(".//{*}Callsign")
        if node is None:
            return None
        data = _fields(node)
        if not data:
            return None
        name = " ".join(part for part in (data.get("fname"), data.get("name")) if part)
        return LookupResult(
            callsign=(data.get("call") or callsign).upper(),
            source=self.name,
            name=name or None,
            grid=data.get("grid"),
            country=data.get("country"),
            state=data.get("state"),
            license_class=data.get("class"),
            expires=data.get("expdate"),
        )
