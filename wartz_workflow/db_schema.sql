-- WARTZ Workflow DB — финальная схема
-- PK: INTEGER AUTOINCREMENT для runtime-сущностей
-- code TEXT UNIQUE для семантических идентификаторов фаз/workflow/project

CREATE TABLE IF NOT EXISTS agents (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS workflows (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    code        TEXT NOT NULL UNIQUE,
    name        TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS phases (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    workflow_id    INTEGER NOT NULL REFERENCES workflows(id),
    code           TEXT NOT NULL UNIQUE,
    name           TEXT NOT NULL,
    description    TEXT,
    min_time_min   INTEGER DEFAULT 0,
    phase_order    INTEGER NOT NULL,
    agent_id       INTEGER REFERENCES agents(id),
    next_recommendation TEXT,
    parallel_with  TEXT,
    rollback_target TEXT,
    execution_type TEXT DEFAULT 'sync'
        CHECK(execution_type IN ('sync', 'parallel')),
    is_seed_managed INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS instructions (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    phase_id       INTEGER NOT NULL REFERENCES phases(id) ON DELETE CASCADE,
    step_num       INTEGER NOT NULL,
    description    TEXT NOT NULL,
    execution_type TEXT DEFAULT 'sync'
        CHECK(execution_type IN ('sync', 'parallel')),
    skills         TEXT,
    UNIQUE(phase_id, step_num)
);

CREATE TABLE IF NOT EXISTS checks (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    phase_id    INTEGER NOT NULL REFERENCES phases(id) ON DELETE CASCADE,
    description TEXT NOT NULL,
    UNIQUE(phase_id, description)
);

CREATE TABLE IF NOT EXISTS evidence (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    phase_id    INTEGER NOT NULL REFERENCES phases(id) ON DELETE CASCADE,
    description TEXT NOT NULL,
    UNIQUE(phase_id, description)
);

CREATE TABLE IF NOT EXISTS projects (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    workflow_id  INTEGER NOT NULL REFERENCES workflows(id),
    code         TEXT NOT NULL UNIQUE,
    name         TEXT NOT NULL,
    key_patterns TEXT NOT NULL DEFAULT '[]'
);

CREATE TABLE IF NOT EXISTS tasks (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id    INTEGER NOT NULL REFERENCES projects(id),
    task_key      TEXT NOT NULL UNIQUE,
    title         TEXT,
    description   TEXT,
    current_phase INTEGER NOT NULL DEFAULT -1,
    status        TEXT DEFAULT 'active'
        CHECK(status IN ('active', 'done', 'blocked')),
    created_at    TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at    TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS task_history (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id      INTEGER NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    phase_id     INTEGER NOT NULL REFERENCES phases(id),
    status       TEXT DEFAULT 'pending'
        CHECK(status IN ('pending', 'done')),
    completed_at TEXT,
    UNIQUE(task_id, phase_id)
);

CREATE TABLE IF NOT EXISTS cli_history (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    command    TEXT NOT NULL,
    task_key   TEXT,
    request    TEXT,
    response   TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
