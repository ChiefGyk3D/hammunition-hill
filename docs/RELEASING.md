# Releasing

A release here is one action — pushing a tag — wrapped in checks that refuse
the tag if the tree behind it disagrees with what the tag claims.

## The version lives in one place

`src/hammunition_hill/__init__.py`:

```python
__version__ = "1.0.0"
```

`pyproject.toml` declares the version *dynamic* and reads it from there, so the
wheel's metadata, `hamhill --version` and `pip show` cannot disagree.
`tests/test_release.py` checks that they don't, and the editable-install case
has bitten already: after a bump, a stale `.dist-info` keeps answering the old
number until you reinstall. The test says so in its failure message.

## Cutting one

1. **Update the changelog.** Move what is under `## [Unreleased]` into a new
   `## [x.y.z] — YYYY-MM-DD` section, and add the link definition at the
   bottom. The tests check the ordering, the dates (nothing in the future) and
   that every section has a link.
2. **Bump `__version__`**, then reinstall so the metadata catches up:
   `uv pip install -e ".[dev,satellites,exam]"`.
3. **Run the gates.** `make check` reproduces CI minus the matrix. For a
   release, also run the heavier ones — they are what CI runs on the tag:

   ```
   make check
   make smoke
   CHROMIUM_PATH=... make render
   make audit
   make build
   ```
4. **Run the live one.** `hamhill check --fetch` on a machine with a WAN, with
   the config you actually ship. This is the check no CI job can make for you:
   it fetches every configured source through the real client, guard and
   parser, and reports what came back. "The host resolves" and "this program
   still understands the answer" rot separately, and only the second one shows
   up as a blank panel three months later.
5. **Merge, then tag:**

   ```
   git tag -a v1.0.0 -m "v1.0.0"
   git push origin v1.0.0
   ```

## What the tag sets off

`.github/workflows/release.yml`:

- **verify** — refuses the tag unless `v$version` equals the tag name *and*
  `CHANGELOG.md` has a section for it. This job exists because the tag is the
  one input a human types by hand.
- **build** — wheel and sdist, `twine check --strict`, then installs the built
  wheel into a fresh virtualenv and runs `hamhill check --offline` against the
  example config. Packaging has broken `web/` once before; publishing an
  unopened box is how that ships. Ends with `sha256sum` over the artefacts.
- **publish** — the only job with `contents: write`, holding it for exactly
  one step, so the token that can write to this repository is never present
  while third-party build dependencies install. Release notes come from the
  changelog section; `--verify-tag` refuses to invent a tag that was not
  pushed.

The write scope is listed in `tests/test_workflows.py::ALLOWED_WRITES` with its
reason, which is the only way a write gets into this repository's CI.

## Debian package

The `.deb` is built from the same tree by `packaging/debian/build.sh` and is
covered in [INSTALL.md](INSTALL.md). It carries the same version, taken from
the same place.

## If a tag goes out wrong

Delete it (`git push origin :refs/tags/vX.Y.Z`), delete the release if one was
created, fix, and tag again with a new patch version rather than reusing the
number. A version that meant two different things at two different times is
worse than a version that was skipped.
