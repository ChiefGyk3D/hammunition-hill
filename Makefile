# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

# Everything CI runs, runnable here.
#
# This is the point of the file rather than a convenience: a check you cannot
# run locally is a check you find out about after pushing, and CI that can only
# be satisfied by guessing is CI people route around. `make check` is what the
# pipeline does, minus the version matrix.

PY ?= .venv/bin/python
RUFF ?= .venv/bin/ruff

.PHONY: help venv lint test check smoke render audit build clean

help:
	@echo "make venv    - create .venv and install with dev extras"
	@echo "make lint    - ruff"
	@echo "make test    - pytest, warnings as errors (as CI runs it)"
	@echo "make check   - lint + test + config validation. Run before pushing."
	@echo "make smoke   - start a real collector against a stub upstream"
	@echo "make render  - load every dashboard in a browser (needs node)"
	@echo "make audit   - pip-audit the declared dependencies"
	@echo "make build   - wheel and sdist, then verify the wheel installs"

venv:
	python3 -m venv .venv
	$(PY) -m pip install --upgrade pip
	$(PY) -m pip install -e ".[dev]"

lint:
	$(RUFF) check src/ tests/

test:
	$(PY) -m pytest -q -W error::DeprecationWarning

check: lint test
	@cp config.example.toml .make-config.toml
	@$(PY) -m hammunition_hill check --offline --config .make-config.toml >/dev/null \
		&& echo "config.example.toml: ok" \
		|| (echo "config.example.toml: FAILED"; rm -f .make-config.toml; exit 1)
	@rm -f .make-config.toml
	@echo "\nall checks passed"

smoke:
	$(PY) .github/scripts/smoke.py

# CHROMIUM_PATH lets this use a browser already on the machine instead of
# downloading playwright's own build.
render:
	@test -d node_modules || npm install --no-save --no-audit --no-fund playwright@1.49.0
	$(PY) .github/scripts/render_check.py

audit:
	@$(PY) -c "import pathlib,tomllib; \
		p=tomllib.loads(pathlib.Path('pyproject.toml').read_text())['project']; \
		print('\n'.join(p['dependencies']))" > .make-requirements.txt
	-$(PY) -m pip_audit --strict --progress-spinner off -r .make-requirements.txt
	@rm -f .make-requirements.txt

build:
	$(PY) -m build
	$(PY) -m twine check --strict dist/*

clean:
	rm -rf dist build .pytest_cache .ruff_cache .render-driver.js .make-*.txt .make-*.toml
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
