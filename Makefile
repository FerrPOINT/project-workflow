# WARTZ project-workflow — Makefile

.PHONY: test coverage lint clean install-dev

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
	ruff check project_workflow/ tests/
	mypy project_workflow/

lint-fix:
	ruff check --fix project_workflow/ tests/

# --- dev setup -------------------------------------------------------------

install-dev:
	pip install -e ".[dev,ui]"

clean:
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name '*.pyc' -delete 2>/dev/null || true
	rm -rf .coverage htmlcov/ .pytest_cache/
