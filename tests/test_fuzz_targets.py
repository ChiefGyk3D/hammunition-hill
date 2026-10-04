# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""The Atheris targets under fuzz/ keep working, in the ordinary suite.

`python-fuzz.yml` runs each target for a fixed time in its own job, on x86_64
and CPython 3.12+ only, because that is all Atheris publishes wheels for. This
suite runs on 3.11, on ARM and on macOS, so it cannot import the real Atheris
everywhere. What it can do everywhere is call each target's `TestOneInput` on a
handful of inputs, which is what catches the rot that matters here: a parser
renamed or re-signed under a target, an import that moved, an exception the
target no longer expects.

Where Atheris is installed the real one is used. Where it is not, a stand-in
with the same `FuzzedDataProvider` surface the targets use takes its place; a
target that reaches for a method the stand-in lacks fails here, loudly, rather
than only in the weekly run.
"""

from __future__ import annotations

import importlib.util
import os
import random
import sys
import tempfile
import types
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest

FUZZ = Path(__file__).resolve().parent.parent / "fuzz"
TARGETS = sorted(FUZZ.glob("fuzz_*.py"))


class _FuzzedDataProvider:
    """The subset of `atheris.FuzzedDataProvider` the targets use, over plain bytes."""

    def __init__(self, data: bytes) -> None:
        self._data = data
        self._at = 0

    def remaining_bytes(self) -> int:
        return len(self._data) - self._at

    def ConsumeBytes(self, count: int) -> bytes:  # noqa: N802 - Atheris's own spelling
        chunk = self._data[self._at : self._at + max(0, count)]
        self._at += len(chunk)
        return chunk

    def ConsumeIntInRange(self, low: int, high: int) -> int:  # noqa: N802
        span = high - low + 1
        raw = int.from_bytes(self.ConsumeBytes(4), "little")
        return low + raw % span

    def ConsumeBool(self) -> bool:  # noqa: N802
        return bool(self.ConsumeIntInRange(0, 1))

    def ConsumeFloat(self) -> float:  # noqa: N802
        return int.from_bytes(self.ConsumeBytes(8), "little") / 1e6 - 1e9

    def ConsumeUnicodeNoSurrogates(self, count: int) -> str:  # noqa: N802
        return self.ConsumeBytes(count).decode("utf-8", errors="replace")


def _stand_in_atheris() -> types.ModuleType:
    module = types.ModuleType("atheris")

    @contextmanager
    def instrument_imports() -> Iterator[None]:
        yield

    module.instrument_imports = instrument_imports  # type: ignore[attr-defined]
    module.FuzzedDataProvider = _FuzzedDataProvider  # type: ignore[attr-defined]
    module.Setup = lambda *a, **k: None  # type: ignore[attr-defined]
    module.Fuzz = lambda *a, **k: None  # type: ignore[attr-defined]
    return module


@pytest.fixture(scope="module", autouse=True)
def atheris_and_path() -> Iterator[None]:
    """Make `import atheris` and `import _support` work for the target modules."""
    added = []
    # HILL_FUZZ_STAND_IN=1 forces the stand-in, to check it against the targets
    # on a machine that does have Atheris.
    if importlib.util.find_spec("atheris") is None or os.environ.get("HILL_FUZZ_STAND_IN"):
        sys.modules.pop("atheris", None)
        sys.modules["atheris"] = _stand_in_atheris()
        added.append("atheris")
    sys.path.insert(0, str(FUZZ))
    try:
        yield
    finally:
        sys.path.remove(str(FUZZ))
        for name in added:
            sys.modules.pop(name, None)


def _load(path: Path) -> types.ModuleType:
    spec = importlib.util.spec_from_file_location(f"fuzz_under_test_{path.stem}", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_there_are_targets_to_check():
    """Guards the parametrised tests below: an empty glob passes vacuously."""
    assert len(TARGETS) >= 7, f"expected the parser targets under {FUZZ}, found {TARGETS}"


@pytest.mark.parametrize("path", TARGETS, ids=lambda p: p.stem)
def test_a_target_has_the_shape_python_fuzz_runs(path):
    """What `python-fuzz.yml` needs of a file: it imports atheris and sets up under __main__."""
    text = path.read_text()
    assert "import atheris" in text
    assert "atheris.instrument_imports()" in text, "without it Atheris sees no coverage"
    assert "def TestOneInput(data: bytes) -> None:" in text
    assert 'if __name__ == "__main__":' in text
    assert "atheris.Setup(sys.argv, TestOneInput)" in text and "atheris.Fuzz()" in text


@pytest.mark.parametrize("path", TARGETS, ids=lambda p: p.stem)
def test_a_target_survives_its_seeds_and_odd_inputs(path):
    module = _load(path)
    seeds = list(module.SEEDS)
    assert seeds, f"{path.name} lists no SEEDS, so nothing shows its valid input still parses"
    rng = random.Random(1337)  # noqa: S311 - a reproducible fixture, not security
    inputs = [
        *seeds,
        b"",
        b"\x00",
        b"\xff" * 64,
        seeds[0] + b"\x00" * 7,
        *(seed[: len(seed) // 2] for seed in seeds),  # truncated documents
        rng.randbytes(64 * 1024),
        *(rng.randbytes(rng.randint(1, 600)) for _ in range(40)),
    ]
    for data in inputs:
        module.TestOneInput(data)  # a raise here is a bug, in the parser or in the target


@pytest.mark.parametrize("path", TARGETS, ids=lambda p: p.stem)
def test_a_target_leaves_the_machine_alone(path, tmp_path, monkeypatch):
    """Targets run unattended on a runner; none may touch HOME or write outside a temp dir."""
    home, scratch = tmp_path / "home", tmp_path / "tmp"
    home.mkdir()
    scratch.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setattr(tempfile, "tempdir", str(scratch))
    module = _load(path)
    for seed in module.SEEDS:
        module.TestOneInput(seed)
    assert not list(home.iterdir()), "a target wrote into HOME"
    assert all(p.name.startswith("hill-fuzz-") for p in scratch.iterdir()), list(scratch.iterdir())
