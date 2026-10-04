# Security Policy

## Supported versions

The latest tagged release is supported (currently v1.2.0). Fixes land on
`main` and ship in the next tag; older tags are not patched.

## Reporting a vulnerability

Please report security issues **privately**, not in a public issue or pull
request. Use GitHub's private vulnerability reporting on this repository:
[Report a vulnerability](https://github.com/ChiefGyk3D/hammunition-hill/security/advisories/new).

Please include the affected panel, source, setting or file, what you expected
and what happened, and the steps to reproduce it. Do not include a callsign,
grid square, hostname or any other station detail you want kept private.

## What is in scope

- The collector and server under `src/hammunition_hill/`: the egress guard and
  its allowlist, the snapshot reader, the HTTP server and the headers it sends,
  the Content-Security-Policy derived from configuration.
- The browser code under `web/`, in particular anything that would let data a
  source returned run as script or load a foreign origin.
- Anything that lets a request cause an outbound fetch, or reach a private,
  loopback or reserved address the configuration did not open.
- The container image and the packaging under `packaging/`.

The dashboard has no authentication by design and is meant for loopback or a
network you control; exposing it to the internet is a configuration this
project advises against, not a vulnerability in it. The threat model is in
[docs/SECURITY.md](docs/SECURITY.md).

Vulnerabilities in the upstream services the dashboard reads, or in
Hammunition itself, belong with those projects; tell us if something here
should change because of one.

## What to expect

Hammunition Hill has a sole maintainer. Expect an acknowledgement within a
week and a fix or a written assessment as soon as practical after that. There
is no bug bounty. Reporters are credited in the changelog entry for the fix
unless they ask not to be.
