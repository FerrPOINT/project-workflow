# project-workflow — Makefile

.PHONY: test test-verbose coverage coverage-html lint lint-fix clean install-dev

# --- testing ---------------------------------------------------------------

test:
	pytest -q --tb=short

test-verbose:
	pytest -v --tb=short

coverage:
	pytest --cov=project_workflow --cov-report=term-missing -q --tb=short

coverage-html:
	pytest --cov=project_workflow --cov-report=html -q --tb=short

# --- lint ------------------------------------------------------------------

lint:
	ruff check .
	mypy project_workflow scripts

lint-fix:
	ruff check --fix .

# --- dev setup -------------------------------------------------------------

install-dev:
	pip install -e ".[dev,ui]"

clean:
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name '*.pyc' -delete 2>/dev/null || true
	rm -rf .coverage htmlcov/ .pytest_cache/
