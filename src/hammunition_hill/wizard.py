# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""``hamhill setup``: a guided first config, in the terminal.

The dashboard has no settings page, and that absence is the security model --
config.toml is the only control and it lives on this machine. Which leaves the
first-run experience: copy the example, open an editor, read four hundred
lines of comments. Fine for the operator who wants that; a wall for the one
who wants a working display in two minutes. This is the ramp for the second
operator: every question states what saying yes costs (a callsign sent, a port
listened on), the answers become an ordinary config.toml, and nothing here is
reachable over HTTP -- it runs where the file lives, as the user who owns it.

The interview is a plain function taking an ``ask`` callback so the tests can
run the whole script with canned answers; only the CLI wrapper touches a TTY.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

# Maidenhead, 4 or 6 characters. The 6-char form is what the propagation
# model and bearings want; 4 is accepted because it is what people remember.
_GRID = re.compile(r"^[A-Ra-r]{2}[0-9]{2}([A-Xa-x]{2})?$")
_CALLSIGN = re.compile(r"^[A-Za-z0-9/]{3,14}$")
_STATE = re.compile(r"^[A-Za-z]{2}$")
_HOSTPORT = re.compile(r"^[A-Za-z0-9.-]+:[0-9]{1,5}$")

LICENSE_CLASSES = ("novice", "technician", "general", "advanced", "extra")


@dataclass
class Answers:
    callsign: str = "N0CALL"
    grid: str = ""
    license_class: str = ""
    space_weather: bool = True
    activity: bool = True
    nws_state: str = ""
    cluster: str = ""  # host:port, empty = off
    rbn: bool = False
    pskreporter: bool = False
    wspr: bool = False
    wsjtx: bool = False
    rigctld: bool = False
    adif_path: str = ""
    lan: bool = False
    notes: list[str] = field(default_factory=list)


Ask = Callable[..., str]


def _yes(ask: Ask, prompt: str, default: bool = False) -> bool:
    hint = "Y/n" if default else "y/N"
    answer = ask(f"{prompt} [{hint}]", default="y" if default else "n").strip().lower()
    return answer in ("y", "yes")


def _valid(ask: Ask, prompt: str, pattern: re.Pattern[str], default: str, why: str) -> str:
    """Re-ask until the answer matches or is the (possibly empty) default."""
    while True:
        answer = ask(f"{prompt}", default=default).strip()
        if answer == default or pattern.match(answer):
            return answer
        # The reprompt says what shape was wanted; silence teaches nothing.
        answer2 = ask(f"  that does not look right ({why}) — try again", default=default).strip()
        if answer2 == default or pattern.match(answer2):
            return answer2


def interview(ask: Ask, say: Callable[[str], None]) -> Answers:
    """Run the whole script. `ask(prompt, default=...)` returns the reply."""
    a = Answers()

    say("This writes a config.toml for the machine you are on. Nothing is sent")
    say("anywhere by answering; every question that WOULD send something says so.")
    say("Enter accepts the [default]. See config.example.toml for everything else.")
    say("")

    a.callsign = (
        _valid(
            ask,
            "Your callsign (stays on this machine unless a later answer says otherwise)",
            _CALLSIGN,
            "N0CALL",
            "letters, digits, optional /",
        ).upper()
        or "N0CALL"
    )
    a.grid = _valid(
        ask,
        "Your grid square, 4 or 6 characters — bearings, distances and the "
        "propagation model all hang off it (blank to skip)",
        _GRID,
        "",
        "like FN31 or FN31pr",
    ).upper()
    license_class = (
        ask(
            f"Licence class, one of {', '.join(LICENSE_CLASSES)} "
            "(blank to guess from the callsign)",
            default="",
        )
        .strip()
        .lower()
    )
    a.license_class = license_class if license_class in LICENSE_CLASSES else ""

    say("")
    say("Tier 1 — public feeds the collector polls. No account, nothing about you sent.")
    a.space_weather = _yes(
        ask, "Space weather: NOAA dials, MUF, aurora, band conditions", default=True
    )
    a.activity = _yes(
        ask, "Activity: POTA and SOTA spots, satellite TLEs, AMSAT news", default=True
    )
    a.nws_state = _valid(
        ask,
        "NWS weather alerts: your two-letter state, e.g. CO (blank to skip; US only)",
        _STATE,
        "",
        "two letters",
    ).upper()

    say("")
    say("Opt-ins that send your callsign. Each is one line to remove later.")
    if _yes(ask, f"DX cluster spots (logs in to a node AS {a.callsign})"):
        a.cluster = _valid(
            ask,
            "Cluster node as host:port",
            _HOSTPORT,
            "dxc.nc7j.com:7373",
            "host:port",
        )
    a.rbn = _yes(ask, f"Reverse Beacon Network (connects AS {a.callsign}, shows who hears you)")
    a.pskreporter = _yes(
        ask, f"PSK Reporter (queries pskreporter.info FOR {a.callsign} every 10 min)"
    )
    a.wspr = _yes(ask, f"WSPR reception reports (queries wspr.live FOR {a.callsign})")

    say("")
    say("Local hardware and files. Nothing leaves the machine.")
    a.wsjtx = _yes(ask, "WSJT-X decodes (listens on UDP 2237; enable UDP Server in WSJT-X)")
    a.rigctld = _yes(ask, "Rig frequency/mode from Hamlib rigctld on localhost:4532 (read-only)")
    a.adif_path = ask(
        "Path to an ADIF log export, e.g. ~/logs/mylog.adi (blank to skip; "
        "colours spots by what you still need)",
        default="",
    ).strip()

    say("")
    a.lan = _yes(
        ask,
        "Serve beyond this machine (0.0.0.0)? There is NO login — the network "
        "is the only access control, and startup will warn every time",
    )
    return a


# --- rendering -----------------------------------------------------------
# String templates that mirror config.example.toml stanza for stanza, so a
# wizard config and a hand-written one read the same and the example stays
# the reference for everything not asked about.

_CORE_SPACE_WEATHER = """
[[sources]]
id = "hamqsl"
kind = "hamqsl"
url = "https://www.hamqsl.com/solarxml.php"
interval = 900

[[sources]]
id = "kindex"
kind = "swpc"
url = "https://services.swpc.noaa.gov/products/noaa-planetary-k-index.json"
interval = 900
options = { product = "planetary_k_index" }

[[sources]]
id = "solarflux"
kind = "swpc"
url = "https://services.swpc.noaa.gov/products/10cm-flux-30-day.json"
interval = 3600
options = { product = "f107_flux" }

[[sources]]
id = "xray"
kind = "swpc"
url = "https://services.swpc.noaa.gov/json/goes/primary/xrays-1-day.json"
interval = 600
options = { product = "xray_flux" }

[[sources]]
id = "protons"
kind = "swpc"
url = "https://services.swpc.noaa.gov/json/goes/primary/integral-protons-1-day.json"
interval = 600
options = { product = "proton_flux" }

[[sources]]
id = "aurora"
kind = "aurora"
url = "https://services.swpc.noaa.gov/json/ovation_aurora_latest.json"
interval = 900

[[sources]]
id = "scales"
kind = "noaa_scales"
url = "https://services.swpc.noaa.gov/products/noaa-scales.json"
interval = 600

[[sources]]
id = "alerts"
kind = "swpc_alerts"
url = "https://services.swpc.noaa.gov/products/alerts.json"
interval = 900
"""

_CORE_ACTIVITY = """
[[sources]]
id = "amsat"
kind = "rss"
url = "https://www.amsat.org/feed/"
interval = 3600

[[sources]]
id = "pota"
kind = "pota"
url = "https://api.pota.app/spot/activator"
interval = 120

[[sources]]
id = "sota"
kind = "sota"
url = "https://api2.sota.org.uk/api/spots/50/all"
interval = 300

[[sources]]
id = "tle"
kind = "tle"
url = "https://celestrak.org/NORAD/elements/gp.php?GROUP=amateur&FORMAT=tle"
interval = 43200
"""


def render_config(a: Answers) -> str:
    """The interview as TOML. Everything else stays in config.example.toml."""
    out: list[str] = [
        "# Written by `hamhill setup`. Edit freely — config.example.toml documents",
        "# every option, and `hamhill check` validates any change offline.",
        "",
        "[server]",
        f'host = "{"0.0.0.0" if a.lan else "127.0.0.1"}"',
        "port = 8073",
        "",
        "[station]",
        f'callsign = "{a.callsign}"',
    ]
    if a.grid:
        out.append(f'grid = "{a.grid}"')
    if a.license_class:
        out.append(f'license_class = "{a.license_class}"')
    if a.space_weather:
        out.append(_CORE_SPACE_WEATHER.rstrip())
    if a.activity:
        out.append(_CORE_ACTIVITY.rstrip())
    if a.nws_state:
        out += [
            "",
            "[[sources]]",
            'id = "wxalerts"',
            'kind = "nws_alerts"',
            f'url = "https://api.weather.gov/alerts/active?area={a.nws_state}"',
            "interval = 300",
        ]
    if a.cluster:
        out += [
            "",
            "# Logs in with your callsign; node operators can see and ban clients.",
            "[[sources]]",
            'id = "cluster"',
            'kind = "dxcluster"',
            f'url = "telnet://{a.cluster}"',
            f'options = {{ callsign = "{a.callsign}" }}',
        ]
    if a.rbn:
        out += [
            "",
            "[[sources]]",
            'id = "rbn"',
            'kind = "rbn"',
            'url = "telnet://telnet.reversebeacon.net:7000"',
            f'options = {{ callsign = "{a.callsign}", watch = ["{a.callsign}"], '
            "window_seconds = 600 }",
        ]
    if a.pskreporter:
        out += [
            "",
            "# Your callsign IS the query; pskreporter.info asks for 5-minute spacing.",
            "[[sources]]",
            'id = "pskreporter"',
            'kind = "pskreporter"',
            'url = "https://retrieve.pskreporter.info/query"',
            "interval = 600",
            f'options = {{ callsign = "{a.callsign}", window_minutes = 15 }}',
        ]
    if a.wspr:
        out += [
            "",
            "[[sources]]",
            'id = "wspr"',
            'kind = "wspr"',
            'url = "https://db1.wspr.live/"',
            "interval = 600",
            f'options = {{ callsign = "{a.callsign}", window_minutes = 30 }}',
        ]
    if a.wsjtx:
        out += [
            "",
            "# Listen-only. Enable Settings -> Reporting -> UDP Server in WSJT-X.",
            "[[sources]]",
            'id = "wsjtx"',
            'kind = "wsjtx"',
            'url = "udp://127.0.0.1:2237"',
            "local = true",
        ]
    if a.rigctld:
        out += [
            "",
            "# Read-only: two get commands, no code path that could key the rig.",
            "[[sources]]",
            'id = "rig"',
            'kind = "rigctl"',
            'url = "tcp://127.0.0.1:4532"',
            "local = true",
            "options = { poll_seconds = 1.0 }",
        ]
    if a.adif_path:
        out += [
            "",
            "[[sources]]",
            'id = "log"',
            'kind = "adif"',
            f'path = "{a.adif_path}"',
            "interval = 300",
        ]
    out.append("")
    return "\n".join(out)


def summarize(a: Answers) -> list[str]:
    """What was chosen and what it costs, printed back before writing."""
    lines = [f"station: {a.callsign}" + (f" at {a.grid}" if a.grid else " (no grid — no bearings)")]
    on = [
        name
        for name, enabled in (
            ("space weather", a.space_weather),
            ("POTA/SOTA/satellites/news", a.activity),
            (f"NWS alerts for {a.nws_state}", bool(a.nws_state)),
            (f"DX cluster ({a.cluster})", bool(a.cluster)),
            ("RBN", a.rbn),
            ("PSK Reporter", a.pskreporter),
            ("WSPR", a.wspr),
            ("WSJT-X", a.wsjtx),
            ("rigctld", a.rigctld),
            (f"ADIF log ({a.adif_path})", bool(a.adif_path)),
        )
        if enabled
    ]
    lines.append("enabled: " + (", ".join(on) if on else "nothing — tier 0 reference only"))
    sends = [
        name
        for name, enabled in (
            ("the DX cluster node", bool(a.cluster)),
            ("the Reverse Beacon Network", a.rbn),
            ("pskreporter.info", a.pskreporter),
            ("wspr.live", a.wspr),
        )
        if enabled
    ]
    lines.append(
        f"your callsign will be sent to: {', '.join(sends)}"
        if sends
        else "nothing sends your callsign"
    )
    lines.append(
        "binding: 0.0.0.0 — NO login; anyone reaching the port sees everything"
        if a.lan
        else "binding: 127.0.0.1 (loopback only)"
    )
    return lines


def validate(toml_text: str) -> Any:
    """The same validation `hamhill check` runs, on the text before it is saved."""
    import tomllib
    from pathlib import Path

    from .config import parse_config

    return parse_config(tomllib.loads(toml_text), base_dir=Path.cwd())


def run(target: Any, ask: Ask, say: Callable[[str], None]) -> int:
    """The whole session: interview, summary, confirm, validate, write.

    `target` is a Path. Returns an exit code; writes nothing without a yes,
    and never writes a config that its own validator rejects -- a wizard that
    can emit a config `hamhill check` refuses has a bug, and the operator
    should see the message, not the file.
    """
    import shutil
    from pathlib import Path

    from .config import ConfigError

    target = Path(target)
    if target.exists():
        say(f"{target} already exists.")
        if not _yes(ask, f"Overwrite it? The current file is kept as {target.name}.bak"):
            say("Nothing written. config.example.toml documents every option.")
            return 1

    a = interview(ask, say)
    say("")
    say("Summary — nothing is written yet:")
    for line in summarize(a):
        say(f"  {line}")
    if not _yes(ask, "Write this config", default=True):
        say("Nothing written.")
        return 1

    text = render_config(a)
    try:
        validate(text)
    except ConfigError as exc:
        say(f"the wizard produced a config its own validator rejects — not writing it: {exc}")
        say("this is a bug worth reporting; config.example.toml still works by hand.")
        return 2

    if target.exists():
        shutil.copy2(target, target.with_name(target.name + ".bak"))
    target.write_text(text, encoding="utf-8")
    say("")
    say(f"wrote {target}")
    say("next:  hamhill check     validates it, no network needed")
    say("then:  hamhill serve     and open http://127.0.0.1:8073")
    return 0
