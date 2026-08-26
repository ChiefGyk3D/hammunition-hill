"""Hammunition Hill - a local-first ham radio dashboard.

The architecture in one sentence: a collector polls upstream sources on a fixed
schedule and writes JSON snapshots to disk; a static file server hands those
files to the browser. The HTTP surface is "read bytes from disk, send bytes."

Nothing an attacker sends can steer an outbound fetch, because the fetch
schedule and the host allowlist are both fixed when the config loads.
"""

__version__ = "0.1.0"
