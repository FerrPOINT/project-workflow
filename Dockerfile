# syntax=docker/dockerfile:1.19@sha256:b6afd42430b15f2d2a4c5a02b919e98a525b785b1aaff16747d2f623364e39b6
FROM python:3.11-slim-bookworm@sha256:0bee7276f83efd4a1ee05bbbf4281d95ed28e079220a9457f25a93e3f1e3c31b AS dependency-inputs
WORKDIR /inputs
COPY pyproject.toml scripts/dependency_inputs.py ./
RUN python dependency_inputs.py --project pyproject.toml --extra ui --output runtime-deps.txt

FROM python:3.11-slim-bookworm@sha256:0bee7276f83efd4a1ee05bbbf4281d95ed28e079220a9457f25a93e3f1e3c31b AS runtime-dependencies

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY constraints.txt ./
COPY --from=dependency-inputs /inputs/runtime-deps.txt /tmp/runtime-deps.txt
ENV PIP_CONSTRAINT=/app/constraints.txt
ARG TARGETARCH
ARG PIP_CACHE_ID=pdlc-operator-downloads-v1-pip-cp311
RUN --mount=type=cache,id=${PIP_CACHE_ID}-${TARGETARCH},target=/root/.cache/pip,sharing=locked \
    python -m venv /opt/venv \
    && /opt/venv/bin/python -m pip install --no-compile --constraint constraints.txt -r /tmp/runtime-deps.txt

FROM runtime-dependencies AS application-inputs
COPY pyproject.toml README.md LICENSE alembic.ini ./
COPY scripts/ ./scripts/
COPY project_workflow/ ./project_workflow/

# Runtime inputs are non-executable Git files; normalize NTFS transport modes
# without removing directory search permissions or relaxing digest verification.
RUN find scripts project_workflow -type f -exec chmod 0644 {} + \
    && chmod 0644 pyproject.toml constraints.txt README.md LICENSE alembic.ini

FROM application-inputs AS verified-inputs
ARG SOURCE_REVISION=""
ARG SOURCE_ARCHIVE_SHA256=""
ARG RUNTIME_BUNDLE_SHA256=""
COPY runtime-*.json ./
RUN if [ -n "$SOURCE_REVISION" ] || [ -n "$SOURCE_ARCHIVE_SHA256" ] || [ -n "$RUNTIME_BUNDLE_SHA256" ]; then \
        python -m scripts.build_runtime_image verify-manifest \
            --root /app \
            --manifest /app/runtime-build-manifest.json \
            --source-revision "$SOURCE_REVISION" \
            --source-archive-sha256 "$SOURCE_ARCHIVE_SHA256" \
            --runtime-bundle-sha256 "$RUNTIME_BUNDLE_SHA256"; \
    fi \
    && printf 'verified\n' > /tmp/runtime-inputs-verified

FROM application-inputs AS builder
RUN --mount=type=bind,from=verified-inputs,source=/tmp/runtime-inputs-verified,target=/tmp/runtime-inputs-verified,ro \
    --mount=type=cache,id=${PIP_CACHE_ID}-${TARGETARCH},target=/root/.cache/pip,sharing=locked \
    /opt/venv/bin/python -m pip install --no-compile --no-deps \
        --constraint constraints.txt ".[ui]" \
        && /opt/venv/bin/python -m pip check \
        && /opt/venv/bin/python -m pip uninstall -y pip setuptools wheel

ARG SOURCE_REVISION=""
ARG SOURCE_ARCHIVE_SHA256=""
ARG RUNTIME_BUNDLE_SHA256=""
ARG CATALOG_VARIANT="legacy"
ENV PROJECT_WORKFLOW_CATALOG_VARIANT=${CATALOG_VARIANT}
COPY --from=verified-inputs /app/runtime-*.json ./
RUN if [ -n "$SOURCE_REVISION" ] || [ -n "$SOURCE_ARCHIVE_SHA256" ] || [ -n "$RUNTIME_BUNDLE_SHA256" ]; then \
        /opt/venv/bin/python -m scripts.build_runtime_image verify-compatibility --root /app; \
    fi

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
