# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Fuzz the FCC ULS importer: the positional `.dat` parser and the index it writes.

The archive is a 160 MB download from a third party; its lines are positional,
pipe-delimited and Latin-1. The target writes the fuzzer's bytes into the
three members of an `l_amat.zip` inside a temp directory, builds the index and
looks every callsign up. A file that is not a zip is the importer's documented
refusal (`ValueError`).
"""

import atexit
import os
import shutil
import sys
import tempfile
import zipfile
from pathlib import Path

import atheris

with atheris.instrument_imports():
    from hammunition_hill.lookup.uls import UlsIndex, build_index

SEEDS = [
    b"",
    b"HD|1|2|3|W1AW|A|HA|01/01/2020|01/01/2030\nEN|1|2|3|W1AW|L|5|ARRL|Hiram|M|Maxim|||||225 Main|Newington|CT|06111\nAM|1|2|3|W1AW|E\n",
    b"HD|1|2|3|W1AW|A\nEN|short\nAM",
]

_WORK = Path(tempfile.mkdtemp(prefix="hill-fuzz-uls-"))
atexit.register(shutil.rmtree, _WORK, ignore_errors=True)


def TestOneInput(data: bytes) -> None:
    fdp = atheris.FuzzedDataProvider(data)
    # Four-way split of the input over HD, EN, AM and one more member name.
    members = {
        "HD.dat": fdp.ConsumeBytes(fdp.ConsumeIntInRange(0, 1024)),
        "EN.dat": fdp.ConsumeBytes(fdp.ConsumeIntInRange(0, 1024)),
        "AM.dat": fdp.ConsumeBytes(fdp.ConsumeIntInRange(0, 1024)),
    }
    # A callsign worth looking up: the one the seeds use, plus whatever the data names.
    probes = ["W1AW", fdp.ConsumeUnicodeNoSurrogates(12)]
    not_a_zip = fdp.ConsumeBool()
    if not not_a_zip and fdp.ConsumeBool():
        # Records with the right tag and field count, every field the fuzzer's.
        for name, tag, width in (("HD.dat", "HD", 9), ("EN.dat", "EN", 19), ("AM.dat", "AM", 6)):
            lines = []
            for _ in range(fdp.ConsumeIntInRange(1, 5)):
                fields = [tag] + [fdp.ConsumeUnicodeNoSurrogates(10) for _ in range(width - 1)]
                if fdp.ConsumeBool():
                    fields[4] = "W1AW"
                if fdp.ConsumeBool():
                    fields[5] = "A"
                lines.append("|".join(f.replace("\n", " ") for f in fields))
            members[name] = "\n".join(lines).encode("latin-1", errors="replace")
    archive = _WORK / "l_amat.zip"
    db = _WORK / "uls.sqlite3"
    if not_a_zip:
        archive.write_bytes(fdp.ConsumeBytes(fdp.remaining_bytes()))
    else:
        # Keep the rest of the input as a text tail so each member can carry real lines.
        tail = fdp.ConsumeBytes(fdp.remaining_bytes())
        members["HD.dat"] += b"\n" + tail
        members["EN.dat"] += b"\n" + tail
        members["AM.dat"] += b"\n" + tail
        with zipfile.ZipFile(archive, "w") as handle:
            for name, content in members.items():
                handle.writestr(name, content)
    try:
        build_index(archive, db)
    except ValueError:
        return  # "is not a zip archive": the documented refusal
    except zipfile.BadZipFile:
        return  # a corrupt archive the zip reader itself rejects
    index = UlsIndex(db)
    try:
        for probe in probes:
            index.lookup(probe)
        index.meta()
    finally:
        index.close()
        for stale in (db, db.with_suffix(".building")):
            if stale.exists():
                os.unlink(stale)


if __name__ == "__main__":
    atheris.Setup(sys.argv, TestOneInput)
    atheris.Fuzz()
