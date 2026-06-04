-- WARTZ Workflow DB — финальная схема
-- 9 таблиц, плоская структура, связи через FOREIGN KEY
--
-- Оптимизация типов (по запросу):
--   execution_type → CHECK IN ('sync','parallel')
--   status         → CHECK IN ('active','done','blocked') / ('pending','done')

CREATE TABLE IF NOT EXISTS phase_groups (
    id          TEXT PRIMARY KEY,         -- "prep", "dev", "review"
    name        TEXT NOT NULL,            -- "Подготовка"
    sort_order  INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS agents (
    id   INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS phases (
    id             TEXT PRIMARY KEY,
    name           TEXT NOT NULL,
    description    TEXT,
    phase_order    INTEGER NOT NULL,
    group_id       TEXT REFERENCES phase_groups(id),
    agent_id       INTEGER REFERENCES agents(id),
    execution_type TEXT DEFAULT 'sync'
        CHECK(execution_type IN ('sync', 'parallel'))
);

CREATE TABLE IF NOT EXISTS instructions (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    phase_id       TEXT NOT NULL REFERENCES phases(id) ON DELETE CASCADE,
    step_num       INTEGER NOT NULL,
    description    TEXT NOT NULL,
    execution_type TEXT DEFAULT 'sync'
        CHECK(execution_type IN ('sync', 'parallel')),
    skills         TEXT,                  -- JSON list
    UNIQUE(phase_id, step_num)
);

CREATE TABLE IF NOT EXISTS checks (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    phase_id    TEXT NOT NULL REFERENCES phases(id) ON DELETE CASCADE,
    description TEXT NOT NULL,
    UNIQUE(phase_id, description)
);

CREATE TABLE IF NOT EXISTS evidence (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    phase_id    TEXT NOT NULL REFERENCES phases(id) ON DELETE CASCADE,
    description TEXT NOT NULL,
    UNIQUE(phase_id, description)
);

CREATE TABLE IF NOT EXISTS tasks (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    task_key      TEXT NOT NULL UNIQUE,
    title         TEXT,
    description   TEXT,
    current_phase TEXT DEFAULT '-1',
    status        TEXT DEFAULT 'active'
        CHECK(status IN ('active', 'done', 'blocked')),
    created_at    TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at    TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS task_history (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id      INTEGER NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    phase_id     TEXT NOT NULL,
    status       TEXT DEFAULT 'pending'
        CHECK(status IN ('pending', 'done')),
    completed_at TEXT,
    UNIQUE(task_id, phase_id)
);

CREATE TABLE IF NOT EXISTS cli_history (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    command   TEXT NOT NULL,
    task_key  TEXT,
    request   TEXT,                       -- JSON аргументы запроса
    response  TEXT,                       -- JSON ответ
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
