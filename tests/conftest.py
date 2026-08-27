# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Shared fixtures, and one guard that applies to every test.

## No test may reach the network

This project's entire argument is that the collector only ever contacts hosts an
operator named, on a schedule, through one guard. A test suite that quietly
reaches the real internet undermines that in three separate ways:

1. **It makes CI a liar.** A green run would depend on NOAA being up, on DNS, and
   on whatever a free API decided to return that morning. Failures would look
   like our bugs and wouldn't be.
2. **It hides missing mocks.** A source test that "passes" by fetching the live
   endpoint is not testing the parser, it is testing NOAA. The day the endpoint
   changes shape, the test goes red for a reason nobody can reproduce offline.
3. **It is rude.** These are free services run by volunteers and government
   agencies. Every CI run on every push is not a reasonable thing to point at
   them.

So sockets to anywhere that isn't loopback raise, loudly, naming the test. The
few tests that legitimately bind or connect locally -- the UDP stream, the port
conflict test, the HTTP server -- are unaffected, because loopback is allowed.

If you are adding a source and this fires, the fix is `httpx.MockTransport`, not
an exemption. There is no opt-out fixture on purpose.
"""

from __future__ import annotations

import ipaddress
import socket

import pytest

_real_socket = socket.socket
_real_create_connection = socket.create_connection
_real_getaddrinfo = socket.getaddrinfo


class NetworkAccessDenied(RuntimeError):
    """A test tried to reach a host outside this machine."""


def _is_local(host: object) -> bool:
    """True for loopback and the unspecified address, which bind() uses."""
    if host in (None, "", "localhost", "localhost.localdomain"):
        return True
    if not isinstance(host, str):
        return False
    try:
        address = ipaddress.ip_address(host.strip("[]"))
    except ValueError:
        # A hostname that is not an IP literal. Resolving it to decide would be
        # the very network call we are trying to prevent, so refuse by default.
        return False
    return address.is_loopback or address.is_unspecified


def _refuse(where: str, host: object) -> NetworkAccessDenied:
    return NetworkAccessDenied(
        f"{where}: this test tried to reach {host!r}. Tests must not use the real "
        f"network -- use httpx.MockTransport, or a local server on 127.0.0.1. "
        f"See the note in tests/conftest.py."
    )


@pytest.fixture(autouse=True)
def _no_outbound_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """Block every socket operation that leaves this machine."""

    def guarded_getaddrinfo(host, port, *args, **kwargs):  # type: ignore[no-untyped-def]
        if not _is_local(host):
            raise _refuse("getaddrinfo", host)
        return _real_getaddrinfo(host, port, *args, **kwargs)

    def guarded_create_connection(address, *args, **kwargs):  # type: ignore[no-untyped-def]
        host = address[0] if isinstance(address, tuple) else address
        if not _is_local(host):
            raise _refuse("create_connection", host)
        return _real_create_connection(address, *args, **kwargs)

    class GuardedSocket(_real_socket):  # type: ignore[misc,valid-type]
        def connect(self, address):  # type: ignore[no-untyped-def]
            host = address[0] if isinstance(address, tuple) else address
            if not _is_local(host):
                raise _refuse("socket.connect", host)
            return super().connect(address)

        def connect_ex(self, address):  # type: ignore[no-untyped-def]
            host = address[0] if isinstance(address, tuple) else address
            if not _is_local(host):
                raise _refuse("socket.connect_ex", host)
            return super().connect_ex(address)

        def sendto(self, data, *args):  # type: ignore[no-untyped-def]
            # UDP needs no connect, so it would otherwise slip straight past.
            address = args[-1] if args else None
            host = address[0] if isinstance(address, tuple) else None
            if host is not None and not _is_local(host):
                raise _refuse("socket.sendto", host)
            return super().sendto(data, *args)

    monkeypatch.setattr(socket, "socket", GuardedSocket)
    monkeypatch.setattr(socket, "getaddrinfo", guarded_getaddrinfo)
    monkeypatch.setattr(socket, "create_connection", guarded_create_connection)
