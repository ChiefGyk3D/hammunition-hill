# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Outbound request policy.

Every fetch the collector makes passes through :class:`EgressGuard` first. Two
rules, both closed by default:

1. The host must appear in the allowlist, which is built from the operator's
   config and the panel manifests. There is no wildcard.
2. The host must not resolve to a private, loopback, link-local, or otherwise
   reserved address -- unless the source is explicitly marked ``local = true``.

Rule 2 is what stops a hijacked or mistyped upstream URL from being used to
probe the LAN the dashboard is sitting on. Panels that legitimately point at
local infrastructure (Pi-Star, OpenWebRX+, dump1090) opt in by saying so.
"""

from __future__ import annotations

import ipaddress
import socket
from dataclasses import dataclass, field
from urllib.parse import urlsplit

# Schemes we will originate. Everything else -- file:, ftp:, gopher:, data: --
# is refused rather than filtered, because a scheme allowlist cannot rot.
ALLOWED_SCHEMES = frozenset({"http", "https"})

# Long-lived connections: a DX cluster over telnet, rigctld and WSJT-X over
# their own sockets. Same allowlist and same private-address rule -- only the
# scheme set differs, so a stream cannot become a way around the policy.
STREAM_SCHEMES = frozenset({"telnet", "tcp", "udp"})


class EgressDenied(Exception):
    """Raised when a fetch is refused by policy. Never caught silently."""


def _is_reserved(addr: str) -> bool:
    """True if an address is anything other than an ordinary public host."""
    ip = ipaddress.ip_address(addr)
    return (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    )


def resolve_all(host: str) -> list[str]:
    """Every address a host resolves to, v4 and v6.

    We check all of them, not just the first. A host that resolves to one public
    address and one RFC1918 address is refused: partial trust is not trust.
    """
    try:
        infos = socket.getaddrinfo(host, None, proto=socket.IPPROTO_TCP)
    except socket.gaierror as exc:
        raise EgressDenied(f"{host}: DNS resolution failed ({exc})") from exc
    return sorted({info[4][0] for info in infos})


@dataclass(frozen=True)
class EgressGuard:
    """A closed allowlist of hosts the collector may contact."""

    allowed_hosts: frozenset[str] = field(default_factory=frozenset)
    local_hosts: frozenset[str] = field(default_factory=frozenset)

    @classmethod
    def build(cls, allowed: set[str], local: set[str]) -> EgressGuard:
        norm = {h.strip().lower().rstrip(".") for h in allowed if h.strip()}
        loc = {h.strip().lower().rstrip(".") for h in local if h.strip()}
        # A local host is still a host we are willing to contact.
        return cls(frozenset(norm | loc), frozenset(loc))

    def check(self, url: str, *, schemes: frozenset[str] = ALLOWED_SCHEMES) -> str:
        """Validate a URL against policy and return its hostname.

        Raises :class:`EgressDenied` with a reason an operator can act on.
        """
        parts = urlsplit(url)
        if parts.scheme not in schemes:
            allowed = " or ".join(sorted(schemes))
            raise EgressDenied(f"{url}: scheme {parts.scheme!r} is not {allowed}")

        host = (parts.hostname or "").lower().rstrip(".")
        if not host:
            raise EgressDenied(f"{url}: no hostname")

        if host not in self.allowed_hosts:
            raise EgressDenied(
                f"{host} is not in the egress allowlist. "
                f"Add a source or panel that declares it, or remove the reference."
            )

        if host in self.local_hosts:
            # Explicitly opted in to LAN access. Nothing further to check.
            return host

        # A bare IP literal is checked directly; a name is checked through DNS.
        try:
            candidates = [str(ipaddress.ip_address(host))]
        except ValueError:
            candidates = resolve_all(host)

        for addr in candidates:
            if _is_reserved(addr):
                raise EgressDenied(
                    f"{host} resolves to {addr}, which is private, loopback, or reserved. "
                    f"If that is intentional, mark the source `local = true`."
                )
        return host

    def check_stream(self, url: str) -> str:
        """Same policy, for a long-lived socket rather than an HTTP fetch."""
        return self.check(url, schemes=STREAM_SCHEMES)

    def csp_hosts(self) -> list[str]:
        """Hosts in a form a Content-Security-Policy directive can use."""
        return sorted(self.allowed_hosts)
