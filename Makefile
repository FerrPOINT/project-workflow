# project-workflow — Makefile

WORKFLOW_QUALITY_UV ?= uv run --python 3.11.15 --frozen --with-requirements constraints.txt --all-extras
UV ?= $(WORKFLOW_QUALITY_UV)

.PHONY: test test-verbose test-integration coverage coverage-html lint lint-fix quality warnings compose-ready clean install-dev

# A combined XML/HTML request owns one prepared operation, including make -j.
COVERAGE_OWNER = $(or $(firstword $(filter coverage coverage-html,$(MAKECMDGOALS))),$@)
COVERAGE_TARGET = $(if $(filter coverage-html,$(MAKECMDGOALS)),coverage-html,$@)

# --- testing ---------------------------------------------------------------

test unit test-verbose integration slow release test-integration lint quality warnings compose-ready:
	WORKFLOW_QUALITY_UV="$(WORKFLOW_QUALITY_UV)" python scripts/quality.py $@

coverage coverage-html:
	@if [ "$@" = "$(COVERAGE_OWNER)" ]; then \
		WORKFLOW_QUALITY_UV="$(WORKFLOW_QUALITY_UV)" python scripts/quality.py $(COVERAGE_TARGET); \
	fi

lint-fix:
	$(UV) ruff check --fix .

# --- dev setup -------------------------------------------------------------

install-dev:
	pip install -e ".[dev,ui]"

clean:
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name '*.pyc' -delete 2>/dev/null || true
	rm -rf .coverage htmlcov/ .pytest_cache/
