# syntax=docker/dockerfile:1.27.1@sha256:4edf897a3ffa55b89f906fc8cc78afdb3f1834cc9c7083565e611a8a7d5fe99e
FROM python:3.11-slim-bookworm@sha256:0bee7276f83efd4a1ee05bbbf4281d95ed28e079220a9457f25a93e3f1e3c31b AS dependency-inputs
ARG PDLC_RUN_SLOT_SHARING=locked
WORKDIR /inputs
COPY pyproject.toml scripts/dependency_inputs.py ./
RUN --mount=type=cache,id=pdlc-host-run-slot-v1,target=/.__pdlc_build_slot__,sharing=${PDLC_RUN_SLOT_SHARING} python dependency_inputs.py --project pyproject.toml --extra ui --output runtime-deps.txt

FROM python:3.11-slim-bookworm@sha256:0bee7276f83efd4a1ee05bbbf4281d95ed28e079220a9457f25a93e3f1e3c31b AS runtime-dependencies
ARG PDLC_RUN_SLOT_SHARING=locked

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1

RUN --mount=type=cache,id=pdlc-host-run-slot-v1,target=/.__pdlc_build_slot__,sharing=${PDLC_RUN_SLOT_SHARING} apt-get update && apt-get install -y --no-install-recommends \
    build-essential libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY constraints.txt ./
COPY --from=dependency-inputs /inputs/runtime-deps.txt /tmp/runtime-deps.txt
ENV PIP_CONSTRAINT=/app/constraints.txt
ARG TARGETARCH
ARG PIP_CACHE_ID=pdlc-operator-downloads-v1-pip-cp311
RUN --mount=type=cache,id=pdlc-host-run-slot-v1,target=/.__pdlc_build_slot__,sharing=${PDLC_RUN_SLOT_SHARING} --mount=type=cache,id=${PIP_CACHE_ID}-${TARGETARCH},target=/root/.cache/pip,sharing=locked \
    python -m venv /opt/venv \
    && /opt/venv/bin/python -m pip install --no-compile --constraint constraints.txt -r /tmp/runtime-deps.txt

FROM runtime-dependencies AS wheel-inputs
ARG PDLC_RUN_SLOT_SHARING=locked
COPY pyproject.toml README.md LICENSE ./
COPY project_workflow/ ./project_workflow/

# Runtime inputs are non-executable Git files; normalize NTFS transport modes
# without removing directory search permissions or relaxing digest verification.
RUN --mount=type=cache,id=pdlc-host-run-slot-v1,target=/.__pdlc_build_slot__,sharing=${PDLC_RUN_SLOT_SHARING} find project_workflow -type f -exec chmod 0644 {} + \
    && chmod 0644 pyproject.toml constraints.txt README.md LICENSE

FROM wheel-inputs AS application-inputs
ARG PDLC_RUN_SLOT_SHARING=locked
COPY alembic.ini ./
COPY scripts/ ./scripts/
RUN --mount=type=cache,id=pdlc-host-run-slot-v1,target=/.__pdlc_build_slot__,sharing=${PDLC_RUN_SLOT_SHARING} find scripts -type f -exec chmod 0644 {} + \
    && chmod 0644 alembic.ini

FROM application-inputs AS verified-inputs
ARG PDLC_RUN_SLOT_SHARING=locked
ARG SOURCE_REVISION=""
ARG SOURCE_ARCHIVE_SHA256=""
ARG RUNTIME_BUNDLE_SHA256=""
COPY runtime-*.json ./
RUN --mount=type=cache,id=pdlc-host-run-slot-v1,target=/.__pdlc_build_slot__,sharing=${PDLC_RUN_SLOT_SHARING} if [ -n "$SOURCE_REVISION" ] || [ -n "$SOURCE_ARCHIVE_SHA256" ] || [ -n "$RUNTIME_BUNDLE_SHA256" ]; then \
        python -m scripts.build_runtime_image verify-manifest \
            --root /app \
            --manifest /app/runtime-build-manifest.json \
            --source-revision "$SOURCE_REVISION" \
            --source-archive-sha256 "$SOURCE_ARCHIVE_SHA256" \
            --runtime-bundle-sha256 "$RUNTIME_BUNDLE_SHA256"; \
    fi \
    && printf 'verified\n' > /tmp/runtime-inputs-verified

FROM wheel-inputs AS builder
ARG PDLC_RUN_SLOT_SHARING=locked
RUN --mount=type=cache,id=pdlc-host-run-slot-v1,target=/.__pdlc_build_slot__,sharing=${PDLC_RUN_SLOT_SHARING} --mount=type=bind,from=verified-inputs,source=/tmp/runtime-inputs-verified,target=/tmp/runtime-inputs-verified,ro \
    --mount=type=cache,id=${PIP_CACHE_ID}-${TARGETARCH},target=/root/.cache/pip,sharing=locked \
    /opt/venv/bin/python -m pip install --no-compile --no-deps \
        --constraint constraints.txt ".[ui]" \
        && /opt/venv/bin/python -m pip check \
        && /opt/venv/bin/python -m pip uninstall -y pip setuptools wheel

FROM builder AS runtime-inputs
ARG PDLC_RUN_SLOT_SHARING=locked
# Keep the installed/stripped venv; merging it over the dependency-stage venv
# would restore removed pip files. Verification tooling is only needed here.
COPY --from=verified-inputs /app/ /app/
ARG SOURCE_REVISION=""
ARG SOURCE_ARCHIVE_SHA256=""
ARG RUNTIME_BUNDLE_SHA256=""
ARG CATALOG_VARIANT="legacy"
ENV PROJECT_WORKFLOW_CATALOG_VARIANT=${CATALOG_VARIANT}
RUN --mount=type=cache,id=pdlc-host-run-slot-v1,target=/.__pdlc_build_slot__,sharing=${PDLC_RUN_SLOT_SHARING} if [ -n "$SOURCE_REVISION" ] || [ -n "$SOURCE_ARCHIVE_SHA256" ] || [ -n "$RUNTIME_BUNDLE_SHA256" ]; then \
        /opt/venv/bin/python -m scripts.build_runtime_image verify-compatibility --root /app; \
    fi

FROM python:3.11-slim-bookworm@sha256:0bee7276f83efd4a1ee05bbbf4281d95ed28e079220a9457f25a93e3f1e3c31b AS runtime
ARG PDLC_RUN_SLOT_SHARING=locked

WORKDIR /app

RUN --mount=type=cache,id=pdlc-host-run-slot-v1,target=/.__pdlc_build_slot__,sharing=${PDLC_RUN_SLOT_SHARING} apt-get update && apt-get install -y --no-install-recommends \
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

COPY --from=runtime-inputs /opt/venv /opt/venv
COPY --from=runtime-inputs /app/alembic.ini /app/alembic.ini
COPY --from=runtime-inputs /app/scripts /app/scripts
COPY --from=runtime-inputs /app/project_workflow/infrastructure/db/migrations /app/project_workflow/infrastructure/db/migrations
COPY --from=runtime-inputs /app/runtime-build-manifest.json /app/runtime-build-manifest.json
COPY --from=runtime-inputs /app/runtime-compatibility.json /app/runtime-compatibility.json

ENV PATH="/opt/venv/bin:$PATH"
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

EXPOSE 8811

CMD ["python", "-m", "project_workflow.interfaces.ui", "--host", "0.0.0.0", "--port", "8811"]
