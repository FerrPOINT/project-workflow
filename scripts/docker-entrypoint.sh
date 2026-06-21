#!/usr/bin/env bash
set -euo pipefail

# Wait for Postgres to become ready if DATABASE_URL points to postgres.
if [[ "${DATABASE_URL:-}" == postgres* ]]; then
    until pg_isready -h "${DB_HOST:-db}" -p "${DB_PORT:-5432}" -U "${DB_USER:-project_workflow}" 2>/dev/null; do
        echo "Waiting for Postgres..."
        sleep 1
    done
fi

# Apply migrations.
alembic upgrade head
