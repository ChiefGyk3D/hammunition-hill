#!/usr/bin/env bash
# Build the Debian package.
#
# Deliberately dpkg-deb over a staged tree rather than a debhelper source
# package. The reasoning: this is a pure-Python application whose three
# dependencies are all packaged in Debian, so there is nothing to compile and
# nothing to vendor -- the whole job is "put these files in these places and
# declare what they need". A source package would add a build-dependency
# toolchain to every machine that wants a .deb, for no gain the operator can
# see. If this ever goes to Debian proper that decision reverses, and the
# staging layout below is the same layout dh_install would produce anyway.
#
# The version is read from the package, never passed in: a .deb whose filename
# disagrees with what `hamhill --version` prints is exactly the confusion the
# rest of the release machinery exists to prevent.
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo="$(cd "$here/../.." && pwd)"
outdir="${1:-$repo/dist}"

version="$(python3 -c "import re,sys; \
    print(re.search(r'__version__ = \"([^\"]+)\"', \
    open('$repo/src/hammunition_hill/__init__.py').read()).group(1))")"

stage="$(mktemp -d)"
trap 'rm -rf "$stage"' EXIT

echo "building hammunition-hill $version"

# --- the files ------------------------------------------------------------
site="$stage/usr/lib/python3/dist-packages"
mkdir -p "$site" "$stage/usr/bin" "$stage/lib/systemd/system" \
         "$stage/etc/hammunition-hill" "$stage/usr/share/doc/hammunition-hill" \
         "$stage/DEBIAN"

# cp -rL, with the L doing real work: web/ reaches the package through a
# symlink (src/hammunition_hill/web -> ../../web) so the repository can keep
# web/ at the root where the Makefile and the render harness expect it. A
# plain cp would put a dangling symlink in the .deb and the dashboard would
# serve 404 for every file it needs -- which is precisely how this has broken
# before, in the wheel.
cp -rL "$repo/src/hammunition_hill" "$site/hammunition_hill"
find "$site" -name '__pycache__' -type d -prune -exec rm -rf {} +
find "$site" -name '*.pyc' -delete

cat > "$stage/usr/bin/hamhill" <<'LAUNCHER'
#!/usr/bin/python3
# Entry point installed by the Debian package. The console script setuptools
# would generate hardcodes an interpreter path from the build machine; this
# one is the distribution's own python3, which is the point of a distro
# package.
import sys

from hammunition_hill.cli import main

if __name__ == "__main__":
    sys.exit(main())
LAUNCHER
chmod 0755 "$stage/usr/bin/hamhill"

install -m 0644 "$here/hammunition-hill.service" "$stage/lib/systemd/system/"
# The shipped config is the example config with one line changed, so every
# source and comment an operator reads in the repository is the same text they
# find in /etc. The one change is load-bearing: data_dir defaults to ./data
# *relative to the config file*, which under /etc means /etc/hammunition-hill/
# data -- and the unit sets ProtectSystem=strict, so the very first snapshot
# write fails with EROFS and the service crash-loops. That is not a
# hypothetical; it is what the first build of this package did on a real
# Debian 13 install, and it is why the package is installed and started in a
# VM before it is allowed to ship.
python3 - "$repo/config.example.toml" "$stage/etc/hammunition-hill/config.toml" <<'PY'
import sys

source, target = sys.argv[1], sys.argv[2]
text = open(source, encoding="utf-8").read()
needle = '# data_dir = "/var/lib/hammunition-hill"'
if needle not in text:
    sys.exit(
        "config.example.toml no longer carries the commented data_dir line this "
        "package rewrites. Fix packaging/debian/build.sh rather than shipping a "
        "config whose data directory lands under /etc."
    )
text = text.replace(
    needle,
    '# Set by the Debian package: /etc is read-only to this service by design\n'
    '# (ProtectSystem=strict in the unit), so snapshots live under /var/lib.\n'
    'data_dir = "/var/lib/hammunition-hill"',
)
open(target, "w", encoding="utf-8").write(text)
PY
chmod 0644 "$stage/etc/hammunition-hill/config.toml"
install -m 0644 "$repo/README.md" "$stage/usr/share/doc/hammunition-hill/"
install -m 0644 "$repo/CHANGELOG.md" "$stage/usr/share/doc/hammunition-hill/"
gzip -9n "$stage/usr/share/doc/hammunition-hill/CHANGELOG.md"
mv "$stage/usr/share/doc/hammunition-hill/CHANGELOG.md.gz" \
   "$stage/usr/share/doc/hammunition-hill/changelog.Debian.gz"
install -m 0644 "$repo/LICENSE" "$stage/usr/share/doc/hammunition-hill/copyright"

# --- the metadata ---------------------------------------------------------
# python3-sgp4 is Recommends, not Depends: satellites are one panel, the
# import is guarded, and the rest of the dashboard does not need it. Debian
# installs Recommends by default, so the normal install gets satellites and
# --no-install-recommends still gets a working dashboard.
cat > "$stage/DEBIAN/control" <<CONTROL
Package: hammunition-hill
Version: $version
Section: hamradio
Priority: optional
Architecture: all
Depends: python3 (>= 3.11), python3-httpx, python3-defusedxml, adduser
Recommends: python3-sgp4
Maintainer: ChiefGyk3D <19499446+ChiefGyk3D@users.noreply.github.com>
Homepage: https://github.com/ChiefGyk3D/hammunition-hill
Description: local-first ham radio dashboard
 Hammunition Hill polls the space weather, propagation, spotting and weather
 sources you name, writes JSON snapshots to disk, and serves them to a browser
 on your own network. No request causes a fetch, so nothing an attacker sends
 can steer an outbound one.
 .
 It has no authentication by design: it binds loopback by default and the
 network is the access control. Reach it over a VPN or ZTNA, never a port
 forward.
CONTROL

# config.toml is a conffile, so dpkg asks before overwriting an operator's
# edits on upgrade rather than silently replacing them.
echo "/etc/hammunition-hill/config.toml" > "$stage/DEBIAN/conffiles"

for script in postinst prerm postrm; do
  install -m 0755 "$here/$script" "$stage/DEBIAN/$script"
done

# --- build ----------------------------------------------------------------
mkdir -p "$outdir"
deb="$outdir/hammunition-hill_${version}_all.deb"
# root:root ownership regardless of who builds, so the package does not carry
# the builder's uid into someone else's filesystem.
dpkg-deb --root-owner-group --build "$stage" "$deb" >/dev/null
echo "$deb"
