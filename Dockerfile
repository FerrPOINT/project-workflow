# syntax=docker/dockerfile:1.27.1@sha256:4edf897a3ffa55b89f906fc8cc78afdb3f1834cc9c7083565e611a8a7d5fe99e
FROM python:3.11-slim-bookworm@sha256:0bee7276f83efd4a1ee05bbbf4281d95ed28e079220a9457f25a93e3f1e3c31b AS dependency-inputs
ARG PDLC_RUN_SLOT_SHARING=locked
WORKDIR /inputs
COPY pyproject.toml constraints.txt dependency-wheels.json scripts/dependency_inputs.py ./
ARG TARGETARCH
RUN --mount=type=cache,id=pdlc-host-run-slot-v1,target=/.__pdlc_build_slot__,sharing=${PDLC_RUN_SLOT_SHARING} python dependency_inputs.py --project pyproject.toml --extra ui \
    --constraints constraints.txt --contract dependency-wheels.json --target "cpython-311-bookworm-${TARGETARCH}" \
    --output runtime-deps.txt --build-output build-deps.txt --constraint-output install-constraints.txt --allow-legacy-target

FROM python:3.11-slim-bookworm@sha256:0bee7276f83efd4a1ee05bbbf4281d95ed28e079220a9457f25a93e3f1e3c31b AS runtime-dependencies
ARG PDLC_RUN_SLOT_SHARING=locked

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1

COPY --from=dependency-inputs /inputs/runtime-deps.txt /tmp/runtime-deps.txt
COPY --from=dependency-inputs /inputs/install-constraints.txt /tmp/install-constraints.txt
ARG TARGETARCH
ARG PIP_CACHE_ID=pdlc-operator-downloads-v1-pip-cp311
RUN --mount=type=cache,id=pdlc-host-run-slot-v1,target=/.__pdlc_build_slot__,sharing=${PDLC_RUN_SLOT_SHARING} --mount=type=cache,id=${PIP_CACHE_ID}-${TARGETARCH},target=/root/.cache/pip,sharing=locked \
    if grep -q '^# workflow-legacy-target:' /tmp/install-constraints.txt; then \
        export PIP_CONSTRAINT=/tmp/install-constraints.txt; \
        apt-get update && apt-get install -y --no-install-recommends build-essential libpq-dev \
        && rm -rf /var/lib/apt/lists/*; \
    fi \
    && python -m venv /opt/venv \
    && /opt/venv/bin/python -m pip install --no-compile --constraint /tmp/install-constraints.txt -r /tmp/runtime-deps.txt \
    && /opt/venv/bin/python -m pip check

FROM python:3.11-slim-bookworm@sha256:0bee7276f83efd4a1ee05bbbf4281d95ed28e079220a9457f25a93e3f1e3c31b AS build-tools
ARG PDLC_RUN_SLOT_SHARING=locked
ENV PYTHONDONTWRITEBYTECODE=1
ARG TARGETARCH
ARG PIP_CACHE_ID=pdlc-operator-downloads-v1-pip-cp311
COPY --from=dependency-inputs /inputs/build-deps.txt /tmp/build-deps.txt
COPY --from=dependency-inputs /inputs/install-constraints.txt /tmp/install-constraints.txt
RUN --mount=type=cache,id=pdlc-host-run-slot-v1,target=/.__pdlc_build_slot__,sharing=${PDLC_RUN_SLOT_SHARING} --mount=type=cache,id=${PIP_CACHE_ID}-${TARGETARCH},target=/root/.cache/pip,sharing=locked \
    python -m venv /opt/build-venv \
    && /opt/build-venv/bin/python -m pip install --no-compile --constraint /tmp/install-constraints.txt -r /tmp/build-deps.txt \
    && /opt/build-venv/bin/python -m pip check

FROM build-tools AS wheel-inputs
ARG PDLC_RUN_SLOT_SHARING=locked
ARG SOURCE_REVISION=""
ARG SOURCE_ARCHIVE_SHA256=""
ARG RUNTIME_BUNDLE_SHA256=""
WORKDIR /app
COPY pyproject.toml README.md LICENSE ./
COPY project_workflow/ ./project_workflow/

# Preserve executable bits covered by an immutable Git context's digest.
# Only unversioned working-tree input needs NTFS transport normalization.
RUN --mount=type=cache,id=pdlc-host-run-slot-v1,target=/.__pdlc_build_slot__,sharing=${PDLC_RUN_SLOT_SHARING} if [ -z "$SOURCE_REVISION$SOURCE_ARCHIVE_SHA256$RUNTIME_BUNDLE_SHA256" ]; then \
        find project_workflow -type f -exec chmod 0644 {} + \
        && chmod 0644 pyproject.toml README.md LICENSE; \
    fi

FROM wheel-inputs AS application-inputs
ARG PDLC_RUN_SLOT_SHARING=locked
COPY alembic.ini constraints.txt ./
COPY scripts/ ./scripts/
RUN --mount=type=cache,id=pdlc-host-run-slot-v1,target=/.__pdlc_build_slot__,sharing=${PDLC_RUN_SLOT_SHARING} if [ -z "$SOURCE_REVISION$SOURCE_ARCHIVE_SHA256$RUNTIME_BUNDLE_SHA256" ]; then \
        find scripts -type f -exec chmod 0644 {} + \
        && chmod 0644 alembic.ini constraints.txt; \
    fi

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
    /opt/build-venv/bin/python -m pip wheel --no-build-isolation --no-deps --wheel-dir /tmp/app-wheel .

FROM runtime-dependencies AS installed
ARG PDLC_RUN_SLOT_SHARING=locked
COPY --from=builder /tmp/app-wheel/ /tmp/app-wheel/
RUN --mount=type=cache,id=pdlc-host-run-slot-v1,target=/.__pdlc_build_slot__,sharing=${PDLC_RUN_SLOT_SHARING} \
    /opt/venv/bin/python -m pip install --no-compile --no-deps /tmp/app-wheel/*.whl \
        && /opt/venv/bin/python -m pip check \
        && /opt/venv/bin/python -m pip uninstall -y pip setuptools wheel

FROM installed AS runtime-inputs
ARG PDLC_RUN_SLOT_SHARING=locked
# Keep the installed/stripped venv; merging it over the dependency-stage venv
# would restore removed pip files. Verification tooling is only needed here.
COPY --from=verified-inputs /app/ /app/
ARG SOURCE_REVISION=""
ARG SOURCE_ARCHIVE_SHA256=""
ARG RUNTIME_BUNDLE_SHA256=""
ARG CATALOG_VARIANT="single-task-v1"
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
ARG CATALOG_VARIANT="single-task-v1"
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
