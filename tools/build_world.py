# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Build the bundled world outline from Natural Earth.

Run once, by hand, when the outline needs regenerating. The output is committed,
so the dashboard has no build step and no runtime dependency on this script or
on pyshp.

Natural Earth is public domain (https://www.naturalearthdata.com/about/terms-of-use/).

    .venv/bin/pip install pyshp
    .venv/bin/python tools/build_world.py path/to/naturalearth_lowres.shp
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "web" / "bandplans" / ".." / "world.json"

# Ramer-Douglas-Peucker tolerance in degrees. The globe is a few hundred pixels
# across, so sub-degree detail is invisible and just costs bytes.
TOLERANCE = 0.35

# Drop islands smaller than this (square degrees, rough). Keeps the file small
# without losing anything readable at globe scale.
MIN_AREA = 0.6


def perpendicular_distance(point, start, end):
    (px, py), (sx, sy), (ex, ey) = point, start, end
    dx, dy = ex - sx, ey - sy
    if dx == 0 and dy == 0:
        return math.hypot(px - sx, py - sy)
    t = max(0.0, min(1.0, ((px - sx) * dx + (py - sy) * dy) / (dx * dx + dy * dy)))
    return math.hypot(px - (sx + t * dx), py - (sy + t * dy))


def simplify(points, tolerance):
    """Ramer-Douglas-Peucker, iterative so a long coastline cannot blow the stack."""
    if len(points) < 3:
        return points

    keep = [False] * len(points)
    keep[0] = keep[-1] = True
    stack = [(0, len(points) - 1)]

    while stack:
        first, last = stack.pop()
        worst, index = 0.0, -1
        for i in range(first + 1, last):
            d = perpendicular_distance(points[i], points[first], points[last])
            if d > worst:
                worst, index = d, i
        if worst > tolerance and index != -1:
            keep[index] = True
            stack.append((first, index))
            stack.append((index, last))

    return [p for p, k in zip(points, keep, strict=True) if k]


def ring_area(points):
    """Shoelace, in square degrees. Only used for a size filter."""
    total = 0.0
    for i in range(len(points)):
        x1, y1 = points[i]
        x2, y2 = points[(i + 1) % len(points)]
        total += x1 * y2 - x2 * y1
    return abs(total) / 2.0


def main(shp_path: str) -> int:
    import shapefile  # imported here so the module is only needed when running

    reader = shapefile.Reader(shp_path)
    rings: list[list[list[float]]] = []

    for shape in reader.shapes():
        points = [(float(x), float(y)) for x, y in shape.points]
        parts = list(shape.parts) + [len(points)]
        for start, end in zip(parts, parts[1:], strict=False):
            ring = points[start:end]
            if len(ring) < 4 or ring_area(ring) < MIN_AREA:
                continue
            reduced = simplify(ring, TOLERANCE)
            if len(reduced) >= 4:
                # Round to 2dp: ~1 km, far finer than a globe can show.
                rings.append([[round(x, 2), round(y, 2)] for x, y in reduced])

    payload = {
        "attribution": "Natural Earth (public domain) — naturalearthdata.com",
        "tolerance_degrees": TOLERANCE,
        "rings": rings,
    }
    out = Path(__file__).resolve().parent.parent / "web" / "world.json"
    out.write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")

    points_total = sum(len(r) for r in rings)
    print(f"{len(rings)} rings, {points_total} points, {out.stat().st_size // 1024} KB -> {out}")
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(__doc__)
        raise SystemExit(2)
    raise SystemExit(main(sys.argv[1]))
