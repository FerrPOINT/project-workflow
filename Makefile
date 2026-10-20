# project-workflow — Makefile

WORKFLOW_QUALITY_UV ?= uv run --python 3.11.15 --frozen --all-extras
UV ?= $(WORKFLOW_QUALITY_UV)

.PHONY: test unit test-verbose test-integration coverage coverage-html release lint lint-fix quality warnings compose-ready clean install-dev

# Release owns coverage prerequisites; report requests only add outputs to it.
COVERAGE_OWNER = $(or $(firstword $(filter release coverage coverage-html,$(MAKECMDGOALS))),$@)
COVERAGE_TARGET = $(if $(filter release,$(MAKECMDGOALS)),release,$(if $(filter coverage-html,$(MAKECMDGOALS)),coverage-html,$@))
COVERAGE_OPTIONS = $(if $(and $(filter release,$(MAKECMDGOALS)),$(filter coverage-html,$(MAKECMDGOALS))),--html-report,)

# --- testing ---------------------------------------------------------------

# An explicit release owns its unit/static overlap; depend on the actual report
# owner so goal order and make -j preserve one operation and its failure.
ifneq ($(filter release,$(MAKECMDGOALS)),)
test unit lint quality: $(COVERAGE_OWNER)
else
ifneq ($(filter quality,$(MAKECMDGOALS)),)
test unit lint: quality
else
test: unit
unit lint:
	WORKFLOW_QUALITY_UV="$(WORKFLOW_QUALITY_UV)" python scripts/quality.py $@
endif
quality:
	WORKFLOW_QUALITY_UV="$(WORKFLOW_QUALITY_UV)" python scripts/quality.py $@
endif

test-verbose integration slow test-integration warnings compose-ready:
	WORKFLOW_QUALITY_UV="$(WORKFLOW_QUALITY_UV)" python scripts/quality.py $@

release coverage coverage-html:
	@if [ "$@" = "$(COVERAGE_OWNER)" ]; then \
		WORKFLOW_QUALITY_UV="$(WORKFLOW_QUALITY_UV)" python scripts/quality.py $(COVERAGE_OPTIONS) $(COVERAGE_TARGET); \
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
