"""Reuse exact schema validation only while live catalog versions remain unchanged."""

from __future__ import annotations

from threading import Lock
from weakref import WeakKeyDictionary

from sqlalchemy import text
from sqlalchemy.engine import Connection, Engine

from project_workflow.config import get_settings

from . import session

# Catalog row versions change on DDL, including defaults, constraints, indexes,
# legacy archive guards and function bodies. Application data is not part of the
# token. The migration revision is read separately on every request.
_POSTGRES_SCHEMA_TOKEN = text("""
WITH namespace AS (
    SELECT oid FROM pg_catalog.pg_namespace WHERE nspname = :schema
), relations AS (
    SELECT oid FROM pg_catalog.pg_class WHERE relnamespace = (SELECT oid FROM namespace)
), types AS (
    SELECT oid FROM pg_catalog.pg_type WHERE typnamespace = (SELECT oid FROM namespace)
), versions AS (
    SELECT 'namespace' AS kind, oid::text AS object_id, xmin::text AS version
    FROM pg_catalog.pg_namespace WHERE oid = (SELECT oid FROM namespace)
    UNION ALL SELECT 'relation', oid::text, xmin::text FROM pg_catalog.pg_class
    WHERE oid IN (SELECT oid FROM relations)
    UNION ALL SELECT 'attribute', attrelid::text || ':' || attnum::text, xmin::text
    FROM pg_catalog.pg_attribute WHERE attrelid IN (SELECT oid FROM relations)
    UNION ALL SELECT 'default', oid::text, xmin::text FROM pg_catalog.pg_attrdef
    WHERE adrelid IN (SELECT oid FROM relations)
    UNION ALL SELECT 'constraint', oid::text, xmin::text FROM pg_catalog.pg_constraint
    WHERE connamespace = (SELECT oid FROM namespace)
    UNION ALL SELECT 'index', indexrelid::text, xmin::text FROM pg_catalog.pg_index
    WHERE indrelid IN (SELECT oid FROM relations)
    UNION ALL SELECT 'trigger', oid::text, xmin::text FROM pg_catalog.pg_trigger
    WHERE tgrelid IN (SELECT oid FROM relations)
    UNION ALL SELECT 'function', oid::text, xmin::text FROM pg_catalog.pg_proc
    WHERE pronamespace = (SELECT oid FROM namespace)
    UNION ALL SELECT 'rewrite', oid::text, xmin::text FROM pg_catalog.pg_rewrite
    WHERE ev_class IN (SELECT oid FROM relations)
    UNION ALL SELECT 'type', oid::text, xmin::text FROM pg_catalog.pg_type
    WHERE oid IN (SELECT oid FROM types)
    UNION ALL SELECT 'enum', oid::text, xmin::text FROM pg_catalog.pg_enum
    WHERE enumtypid IN (SELECT oid FROM types)
    UNION ALL SELECT 'inheritance', inhrelid::text || ':' || inhparent::text, xmin::text
    FROM pg_catalog.pg_inherits
    WHERE inhrelid IN (SELECT oid FROM relations) OR inhparent IN (SELECT oid FROM relations)
    UNION ALL SELECT 'sequence', seqrelid::text, xmin::text FROM pg_catalog.pg_sequence
    WHERE seqrelid IN (SELECT oid FROM relations)
    UNION ALL SELECT 'comment', classoid::text || ':' || objoid::text || ':' || objsubid::text, xmin::text
    FROM pg_catalog.pg_description WHERE objoid IN (SELECT oid FROM relations)
)
SELECT md5(COALESCE(string_agg(kind || ':' || object_id || ':' || version, ','
                              ORDER BY kind, object_id, version), '')) FROM versions
""")

_validated: WeakKeyDictionary[Engine, tuple[str, frozenset[str], bool]] = WeakKeyDictionary()
_validation_lock = Lock()


def _schema_token(connection: Connection) -> str:
    if connection.dialect.name == "sqlite":
        return str(connection.exec_driver_sql("PRAGMA schema_version").scalar_one())
    return str(connection.execute(_POSTGRES_SCHEMA_TOKEN, {"schema": get_settings().DB_SCHEMA}).scalar_one())


def schema_is_ready_for_health(engine: Engine) -> bool:
    """Check live DB/catalog/revision each time; reuse unchanged deep validation.

    There is no TTL or background refresh. DDL and migration revision changes
    invalidate both successful and failed results immediately. Engine lifetime
    owns the cache, so replacing a connection engine cannot reuse another DB's
    validation. A database error is never converted into cached success.
    """
    if engine.dialect.name not in {"sqlite", "postgresql"}:
        return session.schema_is_ready(engine)
    with _validation_lock:
        with engine.connect() as connection:
            token = _schema_token(connection)
            revisions = frozenset(session.database_revisions(connection))
        cached = _validated.get(engine)
        if cached is not None and cached[:2] == (token, revisions):
            return cached[2]
        ready = session.schema_is_ready(engine)
        # Do not publish a result if DDL/revision changed during full inspection.
        with engine.connect() as connection:
            if (_schema_token(connection), frozenset(session.database_revisions(connection))) != (token, revisions):
                return False
        _validated[engine] = (token, revisions, ready)
        return ready
