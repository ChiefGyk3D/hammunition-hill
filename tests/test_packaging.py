# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""The Debian package, checked without needing dpkg.

A package is a set of promises about somebody else's filesystem: this file
goes there, this service runs as that user, this directory survives a remove
and does not survive a purge. Most of those promises are only testable by
installing it, which CI does in its own job and which was done by hand on a
real Debian 13 machine before this shipped.

What is checked here is the part that can be checked from the tree, and it is
the part most likely to rot quietly: the hardening directives in the unit, the
dependency list, the conffile declaration, and above all the substitution that
moves the data directory out of /etc. That last one is not theoretical -- the
first build of this package shipped a config whose data_dir resolved to
/etc/hammunition-hill/data, ProtectSystem=strict made it read-only, and the
service crash-looped on its very first snapshot write.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from hammunition_hill import __version__

REPO = Path(__file__).resolve().parents[1]
DEBIAN = REPO / "packaging" / "debian"
BUILD = (DEBIAN / "build.sh").read_text(encoding="utf-8")
UNIT = (DEBIAN / "hammunition-hill.service").read_text(encoding="utf-8")
POSTINST = (DEBIAN / "postinst").read_text(encoding="utf-8")
PRERM = (DEBIAN / "prerm").read_text(encoding="utf-8")
POSTRM = (DEBIAN / "postrm").read_text(encoding="utf-8")
EXAMPLE = (REPO / "config.example.toml").read_text(encoding="utf-8")

SCRIPTS = {"postinst": POSTINST, "prerm": PRERM, "postrm": POSTRM}


# --- the unit -------------------------------------------------------------
# Each of these is a boundary the service does not need to cross. They are
# listed rather than spot-checked because the failure mode of losing one is
# silent: the dashboard works exactly as well without ProtectKernelModules.
HARDENING = [
    "NoNewPrivileges=true",
    "ProtectSystem=strict",
    "ProtectHome=true",
    "PrivateTmp=true",
    "PrivateDevices=true",
    "ProtectKernelTunables=true",
    "ProtectKernelModules=true",
    "ProtectControlGroups=true",
    "ProtectClock=true",
    "RestrictSUIDSGID=true",
    "RestrictRealtime=true",
    "RestrictNamespaces=true",
    "LockPersonality=true",
    "MemoryDenyWriteExecute=true",
    "SystemCallArchitectures=native",
    "SystemCallFilter=@system-service",
    "CapabilityBoundingSet=",
]


@pytest.mark.parametrize("directive", HARDENING)
def test_the_unit_keeps_its_hardening(directive):
    assert directive in UNIT, f"the systemd unit lost {directive}"


def test_the_unit_runs_as_the_service_account_not_root():
    assert "User=hamhill" in UNIT
    assert "User=root" not in UNIT


def test_the_unit_can_write_only_its_state_directory():
    """ProtectSystem=strict makes everything read-only; this is the one hole."""
    writable = re.findall(r"^ReadWritePaths=(.+)$", UNIT, re.M)
    assert writable == ["/var/lib/hammunition-hill"], f"unexpected write paths: {writable}"


def test_the_unit_allows_the_address_families_dns_actually_needs():
    """AF_UNIX is not decoration.

    Dropping it looks harmless -- the dashboard speaks IP -- but the resolver
    reaches nscd and systemd-resolved over a unix socket, so without it every
    lookup fails and every upstream looks dead.
    """
    families = re.search(r"^RestrictAddressFamilies=(.+)$", UNIT, re.M).group(1).split()
    assert set(families) == {"AF_INET", "AF_INET6", "AF_UNIX"}


# --- the package metadata -------------------------------------------------
def test_the_package_version_comes_from_the_module():
    """One version, or the .deb filename and `hamhill --version` disagree."""
    assert "__version__" in BUILD
    assert "Version: $version" in BUILD


def test_the_builds_version_regex_still_matches_this_package():
    """The build reads __version__ out of the source with a regex.

    Which means a harmless-looking reformat of __init__.py -- single quotes,
    a type annotation, a line break -- silently produces an empty version and
    a .deb called hammunition-hill__all.deb. Run the same expression here.
    """
    pattern = re.search(r"re\.search\(r'([^']+)'", BUILD).group(1)
    source = (REPO / "src" / "hammunition_hill" / "__init__.py").read_text(encoding="utf-8")
    found = re.search(pattern.replace('\\"', '"'), source)
    assert found, f"the build's version regex no longer matches __init__.py: {pattern}"
    assert found.group(1) == __version__


def test_the_dependencies_are_the_ones_debian_actually_ships():
    """Both are packaged in Debian; vendoring them would make this not a distro package."""
    depends = re.search(r"^Depends: (.+)$", BUILD, re.M).group(1)
    assert "python3-httpx" in depends
    assert "python3-defusedxml" in depends
    assert "python3 (>= 3.11)" in depends


def test_satellites_are_recommended_not_required():
    """One optional panel must not be able to block the install."""
    recommends = re.search(r"^Recommends: (.+)$", BUILD, re.M).group(1)
    assert "python3-sgp4" in recommends
    assert "sgp4" not in re.search(r"^Depends: (.+)$", BUILD, re.M).group(1)


def test_the_config_is_a_conffile():
    """Without this, dpkg silently overwrites an operator's edits on upgrade."""
    assert 'echo "/etc/hammunition-hill/config.toml" > "$stage/DEBIAN/conffiles"' in BUILD


def test_the_build_dereferences_the_web_symlink():
    """cp -rL, with the L load-bearing.

    web/ reaches the package through a symlink so the repository can keep it
    at the root. A plain cp puts a dangling link in the .deb and every file
    the dashboard needs answers 404 -- which is how this broke in the wheel.
    """
    assert "cp -rL" in BUILD


def test_the_package_does_not_carry_the_builders_uid():
    assert "--root-owner-group" in BUILD


# --- the data directory, which is the bug this package already had --------
def test_the_example_config_still_has_the_line_the_build_rewrites():
    """The build fails loudly if this line moves. So does this test, sooner."""
    assert '# data_dir = "/var/lib/hammunition-hill"' in EXAMPLE


def test_the_build_refuses_to_ship_a_config_it_could_not_fix():
    """A substitution that silently does nothing is how the EROFS crash returns."""
    assert "sys.exit(" in BUILD
    assert "no longer carries the commented data_dir line" in BUILD


def test_the_shipped_config_points_at_the_writable_directory():
    assert 'data_dir = "/var/lib/hammunition-hill"' in BUILD


# --- maintainer scripts ---------------------------------------------------
@pytest.mark.parametrize("name", sorted(SCRIPTS))
def test_maintainer_scripts_are_strict_shell(name):
    body = SCRIPTS[name]
    assert body.startswith("#!/bin/sh\n") or body.startswith("#!/bin/sh")
    assert "\nset -e\n" in body, f"{name} does not set -e; a failed step would pass silently"


@pytest.mark.parametrize("name", sorted(SCRIPTS))
def test_maintainer_scripts_do_not_leave_a_debhelper_token(name):
    """#DEBHELPER# is substituted by debhelper, and this package does not use it.

    Left in, the token is an inert comment that looks exactly like the thing
    that was supposed to handle the service. The first draft had three.

    A token on its own line is the substitution point; the string inside a
    sentence explaining why there is no substitution is prose, and an
    assertion that cannot tell them apart fails on its own documentation --
    which is what the first version of this test did.
    """
    bare = [line for line in SCRIPTS[name].splitlines() if line.strip() == "#DEBHELPER#"]
    assert not bare, f"{name} still has a #DEBHELPER# substitution point"


def test_postinst_creates_the_account_only_if_it_is_missing():
    """postinst runs again on every upgrade; adduser twice is an error."""
    assert 'if ! getent passwd "$USER" >/dev/null; then' in POSTINST


def test_postinst_does_not_re_enable_a_deliberately_disabled_service():
    """An operator's `systemctl disable` must survive an upgrade."""
    assert "was-enabled" in POSTINST


def test_postinst_protects_the_config_from_other_accounts():
    """It carries a callsign, and can carry a lookup API key."""
    assert "chmod 0640 /etc/hammunition-hill/config.toml" in POSTINST


def _case_branch(script: str, label: str) -> str:
    """The body of one `case` branch, from its label to its `;;`.

    Written because the first version of the test below split the file on
    "purge)" and inspected everything *before* it -- which is not where the
    remove branch lives, so the assertion was reading a region that could
    never contain what it was looking for. It passed on a postrm that deleted
    the operator's data on remove. A check that cannot fail is worse than no
    check, so this one parses the branch it means.
    """
    start = script.index(f"{label})")
    end = script.index(";;", start)
    return script[start:end]


def test_purge_takes_the_operators_data():
    assert 'rm -rf "$STATE"' in _case_branch(POSTRM, "  purge")


def test_remove_keeps_the_operators_data():
    """Debian policy, and the difference between reinstalling and starting over."""
    branch = _case_branch(POSTRM, "  remove")
    assert 'rm -rf "$STATE"' not in branch, "remove must not delete the state directory"
    assert "deluser" not in branch, "remove must not delete the service account"


def test_prerm_stops_the_service_on_remove_but_not_on_upgrade():
    """postinst restarts it; stopping here too is a second outage for nothing."""
    assert "remove|deconfigure)" in PRERM
    assert "upgrade)" not in PRERM
