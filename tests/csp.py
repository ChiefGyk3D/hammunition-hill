# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Reading a Content-Security-Policy the way a browser does, for the tests."""


def csp_sources(policy: str, directive: str) -> list[str]:
    """The source list of one CSP directive, parsed rather than substring-matched.

    ``"https://x.example" in policy`` also passes for ``https://x.example.evil``
    and for a host named in the wrong directive, which is exactly what the CSP
    tests exist to catch.
    """
    for part in (d.strip() for d in policy.split(";")):
        name, _, rest = part.partition(" ")
        if name == directive:
            return rest.split()
    raise AssertionError(f"no {directive} directive in {policy!r}")
