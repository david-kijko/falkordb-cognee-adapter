PY ?= /home/david/.venvs/archie-1.0/bin/python
PIP := $(PY) -m pip
PYTEST := $(PY) -m pytest
RUFF := $(PY) -m ruff

.PHONY: help install test test-contract test-fitness freeze-cognee-contract fmt lint clean

help:
	@echo "Targets: install, test, test-contract, test-fitness, freeze-cognee-contract, fmt, lint, clean"

install:
	$(PIP) install -e '.[dev]'

test:
	$(PYTEST) -q

test-contract: freeze-cognee-contract
	$(PYTEST) -q tests/test_smoke.py

test-fitness:
	$(PYTEST) -q

freeze-cognee-contract:
	$(PY) scripts/freeze_cognee_contract.py

fmt:
	$(RUFF) format src tests scripts

lint:
	$(RUFF) check src tests scripts

clean:
	rm -rf .pytest_cache .ruff_cache build dist *.egg-info src/*.egg-info
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
	find . -type f -name '*.pyc' -delete
