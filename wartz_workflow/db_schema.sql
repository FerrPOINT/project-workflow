-- WARTZ Workflow DB — минимальная схема

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
    next_recommendation TEXT
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
    optional    INTEGER DEFAULT 0,
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
--  questions — вопросы для wizard (проверка понимания)
-- ═══════════════════════════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS questions (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    phase_id     TEXT NOT NULL REFERENCES phases(id) ON DELETE CASCADE,
    qtext        TEXT NOT NULL,
    required     INTEGER DEFAULT 1,
    expected_keywords TEXT,  -- JSON list
    hint         TEXT,
    auto_command TEXT,
    validate_fn  TEXT,
    step_num     INTEGER DEFAULT 0
);

-- ═══════════════════════════════════════════════════════════════════
--  answers — ответы агента на вопросы
-- ═══════════════════════════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS answers (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    question_id  INTEGER NOT NULL REFERENCES questions(id) ON DELETE CASCADE,
    jira_key     TEXT NOT NULL,
    answer_text  TEXT,
    ok           INTEGER DEFAULT 0,
    created_at   TEXT DEFAULT CURRENT_TIMESTAMP
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

-- ═══════════════════════════════════════════════════════════════════
--  checkups — результаты выполнения checks
-- ═══════════════════════════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS checkups (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    phase_id    TEXT NOT NULL REFERENCES phases(id) ON DELETE CASCADE,
    name        TEXT,
    check_type  TEXT,
    target      TEXT,
    interval_min INTEGER DEFAULT 0,
    last_status TEXT DEFAULT 'unknown',
    last_run    TEXT,
    fail_action TEXT DEFAULT 'warn',
    check_id    INTEGER REFERENCES checks(id),
    passed      INTEGER DEFAULT 0,
    output      TEXT,
    ran_at      TEXT DEFAULT CURRENT_TIMESTAMP
);
