# project-workflow — Makefile

UV ?= uv run --isolated --with-requirements constraints.txt --all-extras
PYTEST ?= $(UV) pytest

.PHONY: test test-verbose test-integration coverage coverage-html lint lint-fix quality warnings compose-ready clean install-dev

# --- testing ---------------------------------------------------------------

test:
	$(PYTEST) -q --timeout=60

test-verbose:
	$(PYTEST) -v --timeout=60

test-integration:
	$(PYTEST) -q -m integration tests/test_postgres_integration.py --timeout=120

coverage:
	$(PYTEST) --cov=project_workflow --cov-report=term --timeout=60

coverage-html:
	$(PYTEST) --cov=project_workflow --cov-report=html --timeout=60

warnings:
	$(PYTEST) -q --timeout=60 -W error::ResourceWarning -W error::pytest.PytestUnraisableExceptionWarning

# --- lint ------------------------------------------------------------------

lint:
	$(UV) ruff check .
	$(UV) mypy project_workflow scripts

lint-fix:
	$(UV) ruff check --fix .

quality: test test-integration coverage lint

compose-ready:
	docker compose up --build -d --wait
	curl --fail http://127.0.0.1:8812/health

# --- dev setup -------------------------------------------------------------

install-dev:
	pip install -e ".[dev,ui]"

clean:
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name '*.pyc' -delete 2>/dev/null || true
	rm -rf .coverage htmlcov/ .pytest_cache/
