-- WARTZ Workflow DB — минимальная схема

-- ═══════════════════════════════════════════════════════════════════
--  phases — карточки workflow
-- ═══════════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS phases (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    description TEXT,
    phase_order INTEGER NOT NULL UNIQUE,
    skills      TEXT                        -- JSON ["skill1","skill2"]
);

-- ═══════════════════════════════════════════════════════════════════
--  instructions — шаги внутри фазы (sync / parallel)
-- ═══════════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS instructions (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    phase_id        TEXT NOT NULL REFERENCES phases(id) ON DELETE CASCADE,
    step_num        INTEGER NOT NULL,
    description     TEXT NOT NULL,
    execution_type  TEXT NOT NULL DEFAULT 'sync'
                            CHECK (execution_type IN ('sync','parallel')),
    tool            TEXT,
    UNIQUE (phase_id, step_num)
);

-- ═══════════════════════════════════════════════════════════════════
--  checks — ручные проверки / гейты перед переходом на сл. фазу
-- ═══════════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS checks (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    phase_id    TEXT NOT NULL REFERENCES phases(id) ON DELETE CASCADE,
    description TEXT NOT NULL,
    command     TEXT                         -- shell-команда для проверки
);

-- ═══════════════════════════════════════════════════════════════════
--  evidence — что собрать агенту
-- ═══════════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS evidence (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    phase_id    TEXT NOT NULL REFERENCES phases(id) ON DELETE CASCADE,
    description TEXT NOT NULL
);

-- ═══════════════════════════════════════════════════════════════════
--  checkups — авто/периодические проверки статуса (Jira, MR, тесты...)
-- ═══════════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS checkups (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    phase_id        TEXT NOT NULL REFERENCES phases(id) ON DELETE CASCADE,
    name            TEXT NOT NULL,            -- название чекапа
    check_type      TEXT NOT NULL,            -- 'jira_status', 'gitlab_mr', 'test_passed', 'lint_clean'
    target          TEXT,                     -- что проверяем: URL, task-key, endpoint
    interval_min    INTEGER DEFAULT 0,        -- 0 = разово, >0 = периодически
    last_status     TEXT DEFAULT 'unknown'    -- 'ok', 'fail', 'running'
                            CHECK (last_status IN ('ok','fail','unknown','running')),
    last_run        TEXT,                     -- ISO8601
    fail_action     TEXT DEFAULT 'warn'       -- 'block' | 'warn' | 'skip'
);
