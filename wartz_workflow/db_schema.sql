-- WARTZ Workflow DB — минимальная схема (4 таблицы)
-- Убрано: questions, answers, checkups, agents, phase_groups — всё в плоских таблицах.

-- ═══════════════════════════════════════════════════════════════════
--  phases — карточки workflow
-- ═══════════════════════════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS phases (
    id           TEXT PRIMARY KEY,
    name         TEXT NOT NULL,
    description  TEXT,
    phase_order  INTEGER NOT NULL,
    skills       TEXT,  -- JSON list
    -- delegate config (flattened)
    delegate_agent        TEXT,
    delegate_timeout      INTEGER DEFAULT 30,
    delegate_max_cycles   INTEGER DEFAULT 3,
    delegate_toolsets     TEXT,  -- JSON list
    -- meta
    parallel_with      TEXT,
    rollback_target    TEXT,
    next_recommendation TEXT,
    execution_mode   TEXT DEFAULT 'sync'  -- sync | parallel
);

-- ═══════════════════════════════════════════════════════════════════
--  instructions — шаги внутри фазы
-- ═══════════════════════════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS instructions (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    phase_id    TEXT NOT NULL REFERENCES phases(id) ON DELETE CASCADE,
    step_num    INTEGER NOT NULL,
    description TEXT NOT NULL,
    execution_type TEXT DEFAULT 'sync',  -- sync | parallel
    tool        TEXT,
    UNIQUE(phase_id, step_num)
);

-- ═══════════════════════════════════════════════════════════════════
--  checks — проверки выполнения фазы
-- ═══════════════════════════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS checks (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    phase_id    TEXT NOT NULL REFERENCES phases(id) ON DELETE CASCADE,
    description TEXT NOT NULL,
    command     TEXT,
    UNIQUE(phase_id, description)
);

-- ═══════════════════════════════════════════════════════════════════
--  evidence — артефакты которые нужно собрать
-- ═══════════════════════════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS evidence (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    phase_id    TEXT NOT NULL REFERENCES phases(id) ON DELETE CASCADE,
    description TEXT NOT NULL,
    validator   TEXT,
    collected   INTEGER DEFAULT 0,
    UNIQUE(phase_id, description)
);

-- ═══════════════════════════════════════════════════════════════════
--  tasks — активные задачи
-- ═══════════════════════════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS tasks (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    jira_key    TEXT NOT NULL UNIQUE,
    title       TEXT,
    description TEXT,
    current_phase TEXT DEFAULT '-1',
    status      TEXT DEFAULT 'active',  -- active | done | blocked
    created_at  TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at  TEXT DEFAULT CURRENT_TIMESTAMP
);

-- ═══════════════════════════════════════════════════════════════════
--  task_phases — история выполнения фаз по задаче
-- ═══════════════════════════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS task_phases (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id     INTEGER NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    phase_id    TEXT NOT NULL,
    status      TEXT DEFAULT 'pending',  -- pending | done | skipped
    completed_at TEXT,
    UNIQUE(task_id, phase_id)
);
