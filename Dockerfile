# syntax=docker/dockerfile:1
FROM python:3.11-slim-bookworm@sha256:0bee7276f83efd4a1ee05bbbf4281d95ed28e079220a9457f25a93e3f1e3c31b AS builder

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml constraints.txt ./
ENV PIP_CONSTRAINT=/app/constraints.txt
RUN --mount=type=cache,target=/root/.cache/pip,sharing=locked \
    python -m venv /opt/venv \
    && python -c "import tomllib; from pathlib import Path; p=tomllib.loads(Path('pyproject.toml').read_text()); Path('/tmp/runtime-deps.txt').write_text('\n'.join(p['project']['dependencies'] + p['project']['optional-dependencies']['ui']))" \
    && /opt/venv/bin/python -m pip install --no-compile --constraint constraints.txt -r /tmp/runtime-deps.txt

ARG SOURCE_REVISION=""
ARG SOURCE_ARCHIVE_SHA256=""
ARG RUNTIME_BUNDLE_SHA256=""
ARG CATALOG_VARIANT="legacy"
ENV PROJECT_WORKFLOW_CATALOG_VARIANT=${CATALOG_VARIANT}

COPY README.md LICENSE alembic.ini ./
COPY scripts/ ./scripts/
COPY project_workflow/ ./project_workflow/
COPY runtime-*.json ./

# Runtime inputs are non-executable Git files; normalize NTFS transport modes
# without removing directory search permissions or relaxing digest verification.
RUN find scripts project_workflow -type f -exec chmod 0644 {} + \
    && chmod 0644 pyproject.toml constraints.txt README.md LICENSE alembic.ini \
    && if [ -n "$SOURCE_REVISION" ] || [ -n "$SOURCE_ARCHIVE_SHA256" ] || [ -n "$RUNTIME_BUNDLE_SHA256" ]; then \
        python -m scripts.build_runtime_image verify-manifest \
            --root /app \
            --manifest /app/runtime-build-manifest.json \
            --source-revision "$SOURCE_REVISION" \
            --source-archive-sha256 "$SOURCE_ARCHIVE_SHA256" \
            --runtime-bundle-sha256 "$RUNTIME_BUNDLE_SHA256"; \
    fi

RUN --mount=type=cache,target=/root/.cache/pip,sharing=locked \
    /opt/venv/bin/python -m pip install --no-compile --no-deps \
        --constraint constraints.txt ".[ui]" \
        && /opt/venv/bin/python -m pip check \
        && if [ -n "$SOURCE_REVISION" ] || [ -n "$SOURCE_ARCHIVE_SHA256" ] || [ -n "$RUNTIME_BUNDLE_SHA256" ]; then \
            /opt/venv/bin/python -m scripts.build_runtime_image verify-compatibility --root /app; \
        fi \
        && /opt/venv/bin/python -m pip uninstall -y pip setuptools wheel

FROM python:3.11-slim-bookworm@sha256:0bee7276f83efd4a1ee05bbbf4281d95ed28e079220a9457f25a93e3f1e3c31b AS runtime

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    && rm -rf /var/lib/apt/lists/* \
    && python -m pip uninstall -y pip setuptools wheel

ARG SOURCE_REVISION=""
ARG SOURCE_ARCHIVE_SHA256=""
ARG RUNTIME_BUNDLE_SHA256=""
ARG CATALOG_VARIANT="legacy"
ENV PROJECT_WORKFLOW_CATALOG_VARIANT=${CATALOG_VARIANT}
LABEL org.opencontainers.image.revision=$SOURCE_REVISION \
      io.relevanter.source.archive-sha256=$SOURCE_ARCHIVE_SHA256 \
      io.relevanter.runtime.bundle-sha256=$RUNTIME_BUNDLE_SHA256

COPY --from=builder /opt/venv /opt/venv
COPY --from=builder /app/alembic.ini /app/alembic.ini
COPY --from=builder /app/scripts /app/scripts
COPY --from=builder /app/project_workflow/infrastructure/db/migrations /app/project_workflow/infrastructure/db/migrations
COPY --from=builder /app/runtime-build-manifest.json /app/runtime-build-manifest.json
COPY --from=builder /app/runtime-compatibility.json /app/runtime-compatibility.json

ENV PATH="/opt/venv/bin:$PATH"
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

EXPOSE 8811

CMD ["python", "-m", "project_workflow.interfaces.ui", "--host", "0.0.0.0", "--port", "8811"]
