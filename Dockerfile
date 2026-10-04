# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
#
# Hammunition Hill, containerised.
#
# The container changes nothing about the threat model: the dashboard still
# has no authentication, and the network is still the only access control.
# Publish the port to localhost or a ZTNA/VPN interface, never 0.0.0.0 on a
# machine the internet can reach -- see docs/SECURITY.md.
#
#   docker build -t hammunition-hill .
#   docker run -d --name hamhill \
#     -p 127.0.0.1:8073:8073 \
#     -v ./config.toml:/config/config.toml:ro \
#     -v hamhill-data:/config/data \
#     hammunition-hill
#
# The config's [server] host must be 0.0.0.0 *inside* the container -- that is
# what the -p binding scopes, and the warning the server prints about it is
# aimed at bare-metal installs. Set data_dir = "/config/data" or leave it
# defaulted; it is derived from the config file's directory.

# Both stages are pinned by digest, and every pip install below is hash-checked
# from requirements/ (compiled with `uv pip compile --generate-hashes`; the
# command is the first lines of each lock). Dependabot moves the digest and the
# lock files.
FROM python:3.13-slim@sha256:3dd7cc108ec1493442514f5c2a871af6af0ec31d768ff6e378a93340c3b3db5f AS build
WORKDIR /src
COPY requirements/build.txt ./requirements/build.txt
RUN pip install --no-cache-dir --require-hashes -r requirements/build.txt
COPY pyproject.toml README.md ./
COPY src ./src
COPY web ./web
RUN python -m build --no-isolation --wheel -o /dist

FROM python:3.13-slim@sha256:3dd7cc108ec1493442514f5c2a871af6af0ec31d768ff6e378a93340c3b3db5f
# The wheel carries web/ and the question pools; nothing else from the
# repository is needed at runtime. Dependencies (sgp4 included) come from the
# hash-checked lock, the wheel itself without a second resolution.
COPY requirements/runtime.txt /tmp/runtime.txt
COPY --from=build /dist/*.whl /tmp/
# pip is removed once the install is done: nothing needs it at runtime, and its
# vendored urllib3 and msgpack are otherwise copies this image would ship and
# could not update. libpcre2 is upgraded in place because the base image's
# digest still carries the version before Debian's security fix; the digest is
# the pin for everything else (the apt line cannot be version-pinned while the
# fix is newer than the base).
RUN pip install --no-cache-dir --require-hashes -r /tmp/runtime.txt \
    && pip install --no-cache-dir --no-deps /tmp/*.whl \
    && pip uninstall -y pip \
    && rm /tmp/*.whl /tmp/runtime.txt \
    && apt-get update -qq \
    && apt-get install -y --no-install-recommends --only-upgrade libpcre2-8-0 \
    && rm -rf /var/lib/apt/lists/*

# An unprivileged user, a config mount point, and nothing writable but data.
RUN useradd --system --create-home --shell /usr/sbin/nologin hamhill \
    && mkdir -p /config/data && chown -R hamhill:hamhill /config
USER hamhill
WORKDIR /config
VOLUME /config/data
EXPOSE 8073

# No shell wrapper: signals reach the process, and `docker stop` is clean.
ENTRYPOINT ["hamhill"]
CMD ["serve", "--config", "/config/config.toml"]
