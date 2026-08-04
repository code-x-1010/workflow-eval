.PHONY: help dev dev-real stop test lint contract check-ownership eval fmt

# No installable packages under packages/*|services/* (src/-only layout, see
# docs/decisions/0007-uv-workspace-does-not-sync.md) -- mirrors the Dockerfile's
# PYTHONPATH rather than a uv workspace.
export PYTHONPATH := packages/wfeval-core/src:packages/wfeval-adapters/src:.

help:
	@echo "make dev             all 5 services, dependencies STUBBED (always works)"
	@echo "make dev-real        real inter-service calls (expect breakage before D8)"
	@echo "make test            unit tests"
	@echo "make contract        every service satisfies its OpenAPI spec  <- must be green from D3"
	@echo "make lint            ruff + mypy + import-linter"
	@echo "make check-ownership AGENT=P2 make check-ownership"
	@echo "make eval            run the corpus, render the report"

dev:
	WFEVAL_STUB_DEPS=1 docker compose up --build

dev-real:
	WFEVAL_STUB_DEPS=0 docker compose up --build

stop:
	docker compose down -v

test:
	pytest tests/unit -q

contract:
	pytest tests/contract -q

lint:
	ruff check . && mypy --strict packages services && lint-imports

check-ownership:
	python scripts/check_ownership.py

fmt:
	ruff format .

eval:
	python scripts/run_corpus.py --corpus datasets/corpus --out reports/
