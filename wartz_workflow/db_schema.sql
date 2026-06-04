-- WARTZ Workflow DB — финальная схема
-- 9 таблиц, плоская структура, связи через FOREIGN KEY

-- ═══════════════════════════════════════════════════════════════════
-- 1. phase_groups — группировка фаз для UI (Kanban-колонки)
-- ═══════════════════════════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS phase_groups (
    id          TEXT PRIMARY KEY,         -- "prep", "dev", "review"
    name        TEXT NOT NULL,            -- "Подготовка"
    sort_order  INTEGER NOT NULL DEFAULT 0
);

-- ═══════════════════════════════════════════════════════════════════
-- 2. agents — профили агентов для delegate (только name)
-- ═══════════════════════════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS agents (
    id   INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL
);

-- ═══════════════════════════════════════════════════════════════════
-- 3. phases — карточки workflow
-- ═══════════════════════════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS phases (
    id             TEXT PRIMARY KEY,
    name           TEXT NOT NULL,
    description    TEXT,
    phase_order    INTEGER NOT NULL,
    group_id       TEXT REFERENCES phase_groups(id),
    skills         TEXT,           -- JSON list
    agent_id       INTEGER REFERENCES agents(id),
    execution_type TEXT DEFAULT 'sync'   -- sync | parallel
);

-- ═══════════════════════════════════════════════════════════════════
-- 4. instructions — шаги внутри фазы
-- ═══════════════════════════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS instructions (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    phase_id       TEXT NOT NULL REFERENCES phases(id) ON DELETE CASCADE,
    step_num       INTEGER NOT NULL,
    description    TEXT NOT NULL,
    execution_type TEXT DEFAULT 'sync',   -- sync | parallel
    UNIQUE(phase_id, step_num)
);

-- ═══════════════════════════════════════════════════════════════════
-- 5. checks — проверки выполнения фазы
-- ═══════════════════════════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS checks (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    phase_id    TEXT NOT NULL REFERENCES phases(id) ON DELETE CASCADE,
    description TEXT NOT NULL,
    UNIQUE(phase_id, description)
);

-- ═══════════════════════════════════════════════════════════════════
-- 6. evidence — артефакты которые нужно собрать
-- ═══════════════════════════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS evidence (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    phase_id    TEXT NOT NULL REFERENCES phases(id) ON DELETE CASCADE,
    description TEXT NOT NULL,
    UNIQUE(phase_id, description)
);

-- ═══════════════════════════════════════════════════════════════════
-- 7. tasks — активные задачи
-- ═══════════════════════════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS tasks (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    jira_key      TEXT NOT NULL UNIQUE,
    title         TEXT,
    description   TEXT,
    current_phase TEXT DEFAULT '-1',
    status        TEXT DEFAULT 'active',  -- active | done | blocked
    created_at    TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at    TEXT DEFAULT CURRENT_TIMESTAMP
);

-- ═══════════════════════════════════════════════════════════════════
-- 8. task_history — история выполнения фаз по задаче
--    status: pending | done (нет skipped — пропусков в проекте нет)
-- ═══════════════════════════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS task_history (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id      INTEGER NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    phase_id     TEXT NOT NULL,
    status       TEXT DEFAULT 'pending',  -- pending | done
    completed_at TEXT,
    UNIQUE(task_id, phase_id)
);

-- ═══════════════════════════════════════════════════════════════════
-- 9. cli_history — log всех обращений к CLI
-- ═══════════════════════════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS cli_history (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    command   TEXT NOT NULL,              -- "step", "history"
    task_key  TEXT,
    request   TEXT,                       -- JSON аргументы запроса
    response  TEXT,                       -- JSON ответ
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
