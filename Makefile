# project-workflow — Makefile

WORKFLOW_QUALITY_UV ?= uv run --python 3.11.15 --frozen --with-requirements constraints.txt --all-extras
UV ?= $(WORKFLOW_QUALITY_UV)
PYTEST ?= $(UV) pytest

.PHONY: test test-verbose test-integration coverage coverage-html lint lint-fix quality warnings compose-ready clean install-dev

# --- testing ---------------------------------------------------------------

test unit integration slow release test-integration coverage lint quality warnings compose-ready:
	WORKFLOW_QUALITY_UV="$(WORKFLOW_QUALITY_UV)" python scripts/quality.py $@

test-verbose:
	$(PYTEST) -v --timeout=60 -m "unit and not integration and not slow"

coverage-html:
	$(PYTEST) --cov=project_workflow --cov-report=html --timeout=60 -m "not postgres"

lint-fix:
	$(UV) ruff check --fix .

# --- dev setup -------------------------------------------------------------

install-dev:
	pip install -e ".[dev,ui]"

clean:
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name '*.pyc' -delete 2>/dev/null || true
	rm -rf .coverage htmlcov/ .pytest_cache/
