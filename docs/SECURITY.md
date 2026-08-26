# Security

## Threat model

Hammunition Hill assumes it is running on a machine you control, on a network
you control, reachable only by people you trust. Every design decision below
follows from that assumption — and the assumption is load-bearing. If you break
it by exposing the dashboard, nothing here protects you.

**In scope.** A hostile or compromised *upstream* — a feed that starts serving
something unexpected, a URL typo that points somewhere it should not, an
upstream host that gets taken over. Also: accidental exposure, where a bind
address gets changed without the operator understanding the consequences.

**Out of scope.** An attacker who can already reach the port. There is no
authentication to defeat, so there is nothing to say about defeating it. Also
out of scope: an attacker with local access to the machine, who has already won.

## Why there is no authentication

The most common way a self-hosted dashboard gets compromised is not a clever
exploit. It is an authentication system with a flaw in it — a default password,
a session fixation bug, a JWT verified with `none`, a password reset flow that
leaks. Every one of those requires having built a login in the first place.

We did not build one. There is no login, no session, no cookie, no token, no
user table, and no request that mutates anything. The HTTP server reads files
from two directories and sends them.

That is a real security property, and it is also a real constraint: **the
network is the access control.** Both halves are true, and you do not get the
first without honouring the second.

## Network stance

Bind to loopback. If you need the dashboard elsewhere, use ZTNA or a VPN.

**Zero Trust Network Access — preferred.** Twingate, NetBird, Tailscale,
Headscale, Zscaler Private Access. Cloudflare Tunnel *only* with Access policies
in front of it — a bare tunnel is a public URL with extra steps.

**Conventional VPN — acceptable.** WireGuard, OpenVPN.

**Not acceptable.** Port forwarding. A public VPS with the port open. A bare
tunnel. Security through an unguessable URL.

A reverse proxy with basic auth or mTLS in front is better than nothing, and
strictly better than raw exposure. It is not equivalent to ZTNA: it
authenticates a request after the packet has arrived, where ZTNA authenticates
the device and the identity before the packet is routed to your host at all.

## Controls

### Egress allowlist (`egress.py`)

Every outbound fetch is checked first, against two rules, both closed by
default:

1. **The host must be in the allowlist.** It is built from the sources and embed
   hosts in your config. There is no wildcard syntax, deliberately.
2. **The host must not resolve to a private, loopback, link-local, multicast,
   or reserved address** — unless the source is explicitly marked
   `local = true`.

All resolved addresses are checked, not just the first: a host that resolves to
one public and one RFC1918 address is refused. Partial trust is not trust.
`169.254.169.254` — the cloud metadata endpoint, and the single most valuable
SSRF target there is — is covered by rule 2 and has its own test.

Only `http` and `https` are ever originated. `file:`, `ftp:`, `data:`, and the
rest are refused by scheme rather than filtered by pattern, because a scheme
allowlist cannot rot.

**Known limitation.** There is a TOCTOU window between the DNS check and the
connection: a hostile resolver could answer the check with a public address and
the connection with a private one. Closing it properly means pinning the
resolved address through the connection, which fights TLS SNI and connection
pooling. Given that the allowlist is closed and operator-controlled, we accept
the window in v0.1 and document it rather than pretending it is not there.

### No request-driven fetching

The collector's schedule is fixed at config load. There is no code path from
the HTTP server into the collector — not an endpoint that triggers a refresh,
not a cache-warming hook, nothing. This is the property everything else rests
on, and it is worth defending in review: a "just add a refresh button" endpoint
would undo it.

### Redirects are not followed

`follow_redirects=False`. An upstream that moves should be fixed in your config,
not chased at runtime — following a redirect would let an upstream send the
collector to a host the allowlist never approved.

`trust_env=False` is also set, so ambient `HTTP_PROXY` / `HTTPS_PROXY`
environment variables never silently reroute the collector's traffic.

### Streams are one-directional

The DX cluster, WSJT-X, and rigctld clients hold sockets open. Each one *emits*;
nothing any of them receives can change what the collector fetches or from where.

- **DX cluster.** We send only the callsign and the setup commands from your
  config. No command is ever built from data the cluster sent us. A hostile node
  can fill your spot list with nonsense -- which the UI treats as untrusted text
  -- but it cannot make the client do anything.
- **rigctld.** Read-only, structurally. The client sends two get commands, `f`
  and `m`. There is no code path that sets frequency, mode, or PTT, because none
  was written. A dashboard must never be able to key a transmitter, and there is
  a test that fails if a write path is ever added.
- **WSJT-X.** Listen-only. We bind a UDP socket and never send. WSJT-X's protocol
  has reply messages that change the running instance's state; implementing them
  would make this a remote control with no authentication in front of it.

Stream URLs go through the same allowlist and the same private-address rule as
HTTP fetches -- only the accepted scheme set differs, so a stream is not a way
around egress policy. Local streams (rigctld, WSJT-X) are on loopback by
definition and must be declared `local = true` like any other LAN source.

### Untrusted binary input

WSJT-X datagrams are parsed with a bounded reader: every field is length-checked
against the datagram it came from, and a string length larger than the maximum
datagram size is refused rather than allocated. A malformed or hostile datagram
costs us that datagram and nothing else. Cluster lines are length-capped and
comments truncated before they reach a snapshot.

### Your log never leaves the machine

The ADIF log is read from disk by a local source that makes no network calls at
all -- there is no URL involved, so it bypasses the egress guard by construction
rather than by exception. Callsigns from your log are resolved locally against
the prefix table. Nothing derived from it is sent anywhere.

This is worth being explicit about because it is the one place where the
dashboard touches genuinely private data. A hosted dashboard offering the same
feature has to receive your log; this one does not.

### Response size cap

Responses are streamed and cut off at 4 MB. An upstream cannot fill a Pi's disk,
whether by accident or otherwise.

### XML parsing

HamQSL serves XML and RSS is XML. Both are parsed with `defusedxml`, not stock
`ElementTree`, which will happily follow entity declarations into billion-laughs
and file-disclosure territory.

### Feed sanitization

Feed content is untrusted input. The collector strips markup, decodes entities,
collapses whitespace, truncates, and drops any link whose scheme is not `http`
or `https` — before anything is written to a snapshot. The frontend then renders
with `textContent`, never `innerHTML`. Both layers, on purpose.

### HTTP response headers

Set on every response:

| Header | Value |
|---|---|
| `Content-Security-Policy` | `default-src 'none'`, opened one directive at a time |
| `X-Content-Type-Options` | `nosniff` |
| `X-Frame-Options` | `DENY` |
| `Referrer-Policy` | `no-referrer` |
| `Permissions-Policy` | camera, microphone, geolocation, usb, payment all denied |
| `Cross-Origin-Opener-Policy` | `same-origin` |
| `Cross-Origin-Resource-Policy` | `same-origin` |
| `Cache-Control` | `no-store` on snapshots |

The CSP is generated from your config rather than hand-maintained, so it cannot
drift from what the panels actually declare. Tier 2 embed hosts are the only
external origins that ever appear in it, and only in `img-src` and `frame-src` —
never in `script-src` or `connect-src`. Run `hamhill check` to see the exact
policy your config produces.

### Path handling

The server serves exactly two directories. Traversal components are dropped
rather than resolved, and the final resolved path is verified to sit inside its
root — which also catches a symlink inside either directory pointing outward.
Directory listings return 404. `POST`, `PUT`, `DELETE`, and `PATCH` return 405.

There is a test for each of those, including percent-encoded and doubled-up
traversal forms.

### Configuration cannot execute code

Source kinds are looked up in a static registry. There is no plugin autoloader
and no dynamic import by name, so a config file cannot make the collector import
or execute something arbitrary. Source ids are validated as filename-safe,
because they become filenames under the data directory.

## Running as a service

When packaging (v0.5), run as a dedicated unprivileged user with a read-only
root filesystem, one writable data directory, and no added capabilities. The
process needs to bind one port and write one directory. Nothing else.

## Reporting a vulnerability

Open a GitHub issue for anything that is not itself sensitive. For something
that is, contact the maintainer privately rather than filing publicly.

Two things that are **not** vulnerabilities:

- "There is no authentication." That is documented, intentional, and explained
  above.
- "The dashboard I exposed to the internet got accessed." See the top of this
  file.
