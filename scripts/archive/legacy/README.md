# Legacy scripts archive

## `legacy/migrate_sqlite_to_postgres.py`

One-shot migration script used to move data from the old SQLite `workflow.db`
into the current PostgreSQL schema. It is no longer part of the production
runtime and is kept here for reference / disaster-recovery only.

To use it (rarely needed):

```bash
export DATABASE_URL="postgresql+psycopg://..."
export WORKFLOW_DB_PATH="path/to/workflow.db"
python scripts/archive/legacy/migrate_sqlite_to_postgres.py
```

Do not import this script from production code.
