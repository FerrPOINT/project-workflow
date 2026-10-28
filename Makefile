# project-workflow — Makefile

WORKFLOW_QUALITY_UV ?= uv run --python 3.11.15 --frozen --all-extras
UV ?= $(WORKFLOW_QUALITY_UV)

.PHONY: test unit integration slow release test-verbose test-integration coverage coverage-html lint lint-fix quality warnings compose-ready clean install-dev

# One report owner per Make invocation, including -j and reversed goal order.
COVERAGE_OWNER = $(or $(firstword $(filter release coverage coverage-html,$(MAKECMDGOALS))),$@)
COVERAGE_TARGET = $(if $(filter release,$(MAKECMDGOALS)),release,$(if $(filter coverage,$(MAKECMDGOALS)),coverage,coverage-html))
COVERAGE_OPTIONS = $(if $(and $(filter release coverage,$(MAKECMDGOALS)),$(filter coverage-html,$(MAKECMDGOALS))),--html-report,)

# --- testing ---------------------------------------------------------------

test unit test-verbose integration slow test-integration lint quality warnings compose-ready install-dev:
	WORKFLOW_QUALITY_UV="$(WORKFLOW_QUALITY_UV)" python scripts/quality.py $@

release coverage coverage-html:
	@if [ "$@" = "$(COVERAGE_OWNER)" ]; then \
		WORKFLOW_QUALITY_UV="$(WORKFLOW_QUALITY_UV)" python scripts/quality.py $(COVERAGE_OPTIONS) $(COVERAGE_TARGET); \
	fi

lint-fix:
	$(UV) ruff check --fix .

clean:
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name '*.pyc' -delete 2>/dev/null || true
	rm -rf .coverage htmlcov/ .pytest_cache/
