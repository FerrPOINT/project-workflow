# project-workflow — Makefile

WORKFLOW_QUALITY_UV ?= uv run --python 3.11.15 --frozen --all-extras
UV ?= $(WORKFLOW_QUALITY_UV)

.PHONY: test unit integration slow release test-verbose test-integration coverage coverage-html lint lint-fix quality warnings compose-ready clean install-dev .workflow-quality

FAST_QUALITY_GOALS = $(or $(filter test unit test-verbose lint quality warnings install-dev,$(MAKECMDGOALS)),test)

# One report owner per Make invocation, including -j and reversed goal order.
COVERAGE_OWNER = $(or $(firstword $(filter release coverage coverage-html,$(MAKECMDGOALS))),$@)
COVERAGE_TARGET = $(if $(filter release,$(MAKECMDGOALS)),release,$(if $(filter coverage,$(MAKECMDGOALS)),coverage,coverage-html))
COVERAGE_OPTIONS = $(if $(and $(filter release coverage,$(MAKECMDGOALS)),$(filter coverage-html,$(MAKECMDGOALS))),--html-report,)

# --- testing ---------------------------------------------------------------

test unit test-verbose lint quality warnings install-dev: .workflow-quality

# A shared prerequisite runs once even for overlapping goals and make -j.
.workflow-quality:
	WORKFLOW_QUALITY_UV="$(WORKFLOW_QUALITY_UV)" python scripts/quality.py $(foreach goal,$(wordlist 2,$(words $(FAST_QUALITY_GOALS)),$(FAST_QUALITY_GOALS)),--also $(goal)) $(firstword $(FAST_QUALITY_GOALS))

integration slow test-integration compose-ready:
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

.PHONY: repository-hygiene repository-hygiene-ref
repository-hygiene:
	python3 -B scripts/check_repository_hygiene.py --index

repository-hygiene-ref:
	python3 -B scripts/check_repository_hygiene.py --ref HEAD
