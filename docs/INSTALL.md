# Installing Hammunition Hill

For operators who just want it running. If you want to know *why* it works the
way it does, read [ARCHITECTURE.md](ARCHITECTURE.md) afterwards.

> **Before you start:** this binds to `127.0.0.1` and has no login. That is
> deliberate — see [SECURITY.md](SECURITY.md). Do not put it on the internet.

## What you need

- A computer that stays on: a Raspberry Pi 4 or better, a spare mini PC, or the
  shack computer itself.
- **Python 3.11 or newer.** Check with `python3 --version`. Raspberry Pi OS
  (Bookworm or later), Debian 12+, Ubuntu 22.04+, and Fedora all ship something
  recent enough.
- A browser on whatever you want to watch it on.

You do *not* need a database, a web server, an account, or an API key.

## Install

Three ways in. A clone is still the best one for anyone who might edit a panel
or contribute; the other two exist so that nobody has to.

### From a clone

```bash
git clone https://github.com/ChiefGyk3D/hammunition-hill
cd hammunition-hill

python3 -m venv .venv
.venv/bin/pip install -e .

cp config.example.toml config.toml
```

### Bare pip, no clone

```bash
python3 -m venv hamhill && hamhill/bin/pip install hammunition-hill
```

The wheel carries the dashboard files and the question pools; with no checkout
beside the config, the server serves the packaged copy. Write a `config.toml`
(start from
[config.example.toml](https://github.com/ChiefGyk3D/hammunition-hill/blob/main/config.example.toml))
and `hamhill serve --config config.toml`.

### Docker

```bash
docker build -t hammunition-hill https://github.com/ChiefGyk3D/hammunition-hill.git
docker run -d --name hamhill \
  -p 127.0.0.1:8073:8073 \
  -v ./config.toml:/config/config.toml:ro \
  -v hamhill-data:/config/data \
  hammunition-hill
```

Inside the container the config's `[server] host` must be `0.0.0.0` — the
`-p 127.0.0.1:...` binding is what scopes it, and the warning the server
prints about binding wide is aimed at bare-metal installs. The container
changes nothing about the threat model: publish the port to localhost or a
ZTNA/VPN interface, never to an address the internet can reach — see
[SECURITY.md](SECURITY.md).

The core install has **two dependencies**, deliberately. Three features are
behind optional extras rather than in that number, because most operators do
not need them and the ones who do would rather install a thing than have it
installed for them:

```bash
.venv/bin/pip install -e ".[satellites]"   # SGP4, for pass prediction
.venv/bin/pip install -e ".[exam]"         # pypdf, only to re-import a question pool
.venv/bin/pip install -e ".[dev]"          # pytest, ruff, and the rest of `make check`
```

`[satellites]` is the one you are most likely to want. Without it the satellite
panel says so rather than failing quietly. `[exam]` is *not* needed to practise
— all three US question pools ship with the project — only to re-import a pool
from the official PDF when a new one is released, which happens once every four
years per element.

Now open `config.toml` and change two things:

```toml
[station]
callsign = "N0CALL"     # yours
grid = "FN04ga"         # your grid square, 4 or 6 characters
```

That is the minimum. The grid square is what gives you beam headings and
distances; without it those are simply omitted.

## Check before you run

```bash
.venv/bin/hamhill check
```

This validates the config and the egress policy **without making a single
network request**. You get the bind address, your station's resolved
coordinates, the generated Content-Security-Policy, and a line per source
saying whether it is allowed.

Run it after every config edit. It catches typos before they become a panel
that silently shows nothing.

## Run

```bash
.venv/bin/hamhill serve
```

Open <http://127.0.0.1:8073>. Panels fill in as the collector completes its
first cycle — give it a minute. A panel saying "waiting for the first collector
cycle" is normal at startup, not an error.

Stop it with Ctrl-C.

## Watching it from a tablet or another machine

**Read [SECURITY.md](SECURITY.md) first.** Short version: there is no
authentication, so anyone who can reach the port sees everything. Put a VPN or
Zero Trust layer in front and come in through that — Twingate, NetBird,
Tailscale, Headscale, WireGuard. Never port-forward it.

Once you have that:

```bash
.venv/bin/hamhill --listen 0.0.0.0:8073 serve
```

It prints a warning every time you do this. That is on purpose.

### One thing that will confuse you

`http://localhost` is what browsers call a *secure context*.
`http://192.168.1.50` is not. Browser features gated on that — geolocation,
WebUSB, service workers — work on the shack machine and silently fail on the
tablet. This is a browser rule, not something this project can opt out of.

## Running it as a service

### systemd

Create `/etc/systemd/system/hammunition-hill.service`:

```ini
[Unit]
Description=Hammunition Hill
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=hamhill
WorkingDirectory=/opt/hammunition-hill
ExecStart=/opt/hammunition-hill/.venv/bin/hamhill --config /etc/hammunition-hill/config.toml serve
Restart=on-failure
RestartSec=10

# It needs to bind one port and write one directory. Nothing else.
NoNewPrivileges=true
ProtectSystem=strict
ProtectHome=true
PrivateTmp=true
ReadWritePaths=/var/lib/hammunition-hill

[Install]
WantedBy=multi-user.target
```

Then:

```bash
sudo useradd --system --no-create-home hamhill
sudo mkdir -p /var/lib/hammunition-hill
sudo chown hamhill /var/lib/hammunition-hill
sudo systemctl enable --now hammunition-hill
journalctl -u hammunition-hill -f
```

Point `data_dir` at `/var/lib/hammunition-hill` in your config.

### A dedicated shack display

A Pi driving a monitor, showing the dashboard full screen on boot, is the
intended shape of this thing. Run the service as above, then autostart a browser
in kiosk mode:

```bash
chromium-browser --kiosk --noerrdialogs --disable-infobars http://127.0.0.1:8073
```

## Adding your log

This is the feature worth the setup. Export ADIF from your logging program, then:

```toml
[[sources]]
id = "log"
kind = "adif"
path = "~/logs/mylog.adi"
interval = 300
```

Spots now get coloured by what you still need: `NEW` for an entity you have
never worked, `BAND` for one you have but not on that band, `MODE` for a new
mode group. The log is re-read every five minutes, so re-exporting after a
session is enough — no restart.

Your log never leaves the machine. There is no upload and no network path
involved in reading it.

### Better entity accuracy

By default, callsigns resolve through a compact built-in prefix table that is
good for common entities and approximate at the edges. If you have AD1C's
`cty.dat` — most logging programs ship one — point at it:

```toml
[log]
cty_dat = "~/.local/share/hammunition-hill/cty.dat"
```

The Log panel tells you which table is in use.

## Connecting your radio

**Rig frequency and mode** — start Hamlib's `rigctld`, then:

```toml
[[sources]]
id = "rig"
kind = "rigctl"
url = "tcp://127.0.0.1:4532"
local = true
```

Read-only. The client sends two get commands and has no code path that could
change frequency, mode, or PTT.

**WSJT-X decodes** — in WSJT-X, Settings → Reporting → UDP Server, set the
server to `127.0.0.1` and port `2237`. Then:

```toml
[[sources]]
id = "wsjtx"
kind = "wsjtx"
url = "udp://127.0.0.1:2237"
local = true
```

Listen-only. If something else already has that port — GridTracker, JTAlert —
this source retries with backoff and everything else keeps working.

**DX cluster** — needs a real callsign; clusters do not accept anonymous logins.

```toml
[[sources]]
id = "cluster"
kind = "dxcluster"
url = "telnet://dxc.nc7j.com:7373"
options = { callsign = "N0CALL", commands = ["set/ft8"] }
```

Be a good guest: cluster nodes are run by volunteers.

## When something is wrong

**A panel says "waiting for the first collector cycle".** Normal at startup.
If it persists, check the log — the source is probably failing.

**A panel shows "fetch failed" with an age.** The source is down or the URL is
wrong, and you are seeing the last good reading with its real age. That is
working as intended. Run `hamhill check` to confirm the URL is allowed, then
look at the log for the actual error.

**A source says DENIED at startup.** The egress guard refused it. If it points
at your own LAN, it needs `local = true` — that is the guard doing its job.

**Everything is blank and the page will not load.** The collector is not
running, or you are on the wrong port. `hamhill check` prints the bind address.

**It works on the shack machine but not the tablet.** Either you did not pass
`--listen`, or you have hit the secure-context rule above.

**Logs**: `journalctl -u hammunition-hill -f` under systemd, or add `-v` to the
command for debug output.
