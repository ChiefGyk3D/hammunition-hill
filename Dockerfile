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

FROM python:3.13-slim AS build
WORKDIR /src
COPY pyproject.toml README.md ./
COPY src ./src
COPY web ./web
RUN pip install --no-cache-dir build && python -m build --wheel -o /dist

FROM python:3.13-slim
# The wheel carries web/ and the question pools; nothing else from the
# repository is needed at runtime.
COPY --from=build /dist/*.whl /tmp/
RUN pip install --no-cache-dir /tmp/*.whl "sgp4>=2.20" && rm /tmp/*.whl

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
