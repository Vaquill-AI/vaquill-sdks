GIT_ROOT ?= $(shell git rev-parse --show-toplevel)
PY ?= python

help:	## Show all Makefile targets.
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[33m%-30s\033[0m %s\n", $$1, $$2}'

format:	## Run ruff formatter and import sorting.
	$(PY) -m ruff format .
	$(PY) -m ruff check --fix .

lint:	## Run ruff and pyright without changing files.
	$(PY) -m ruff format --check .
	$(PY) -m ruff check .
	$(PY) -m pyright

test:	## Run the offline test suite with coverage (fails under 85 percent).
	$(PY) -m pytest --cov --cov-report=term-missing

live:	## Run the opt-in live smoke test (needs VAQUILL_API_KEY, spends at most 5 credits).
	$(PY) -m pytest -m live -o addopts="" tests/test_live_smoke.py

.PHONY: help format lint test live
