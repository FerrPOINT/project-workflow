<!-- project-workflow-cli README — v2.0 2026 -->

<p align="center">
  <img src="https://capsule-render.vercel.app/api?type=waving&height=180&text=project-workflow-cli&fontAlign=50&fontAlignY=35&desc=Declarative%2042-Phase%20Engine%20for%20Multi-Agent%20Development%20Workflows&descAlign=50&descAlignY=60&color=gradient&customColorList=0,2,2,5,30" />
</p>

<p align="center">
  <a href="https://github.com/FerrPOINT/project-workflow-cli/actions"><img src="https://img.shields.io/github/actions/workflow/status/FerrPOINT/project-workflow-cli/ci.yml?style=flat-square&logo=github-actions&logoColor=white&label=CI" /></a>
  <img src="https://img.shields.io/badge/Python-3.11+-3776AB?style=flat-square&logo=python&logoColor=white" />
  <img src="https://img.shields.io/badge/Tests-58%20passing-2EA44F?style=flat-square&logo=pytest&logoColor=white" />
  <img src="https://img.shields.io/badge/Coverage-47%25-yellow?style=flat-square&logo=codecov&logoColor=white" />
  <img src="https://img.shields.io/badge/License-MIT-6B7280?style=flat-square&logo=opensourceinitiative&logoColor=white" />
</p>

<p align="center">
  <a href="#features"><img src="https://img.shields.io/badge/Features-0B1220?style=for-the-badge" /></a>
  <a href="#cli"><img src="https://img.shields.io/badge/CLI%20Commands-111827?style=for-the-badge" /></a>
  <a href="#phases"><img src="https://img.shields.io/badge/42%20Phases-1F2937?style=for-the-badge" /></a>
  <a href="#architecture"><img src="https://img.shields.io/badge/Architecture-374151?style=for-the-badge" /></a>
  <a href="#quality"><img src="https://img.shields.io/badge/Quality%20Bar-4B5563?style=for-the-badge" /></a>
</p>

---

## Позиционирование

CLI-инструмент для **жёсткого пофазового управления задачами разработки**. Каждая задача проходит через 42 декларативно описанные фазы (YAML), с **mandatory evidence** на каждом шаге. Поддерживает rollback-циклы, параллельное делегирование sub-агентам и dual-mode вывод.

**Фокус:** контролируемый AI-agent workflow · декларативные фазы · evidence tracking · gate taxonomy · production-ready CLI.

---

## ✨ Features

| Feature | Description |
|---------|-------------|
| **Declarative Phases** | 42-phase workflow в `references/phases.yaml` — единый источник истины |
| **Dual-Mode CLI** | Rich tables для людей, JSON для агентов (`--json`) |
| **Gate Taxonomy** | 4 типа: Pre-flight (PF), Revision (RV), Escalation (ES), Abort (AB) |
| **Rollback Engine** | Автоматический откат при gate failure с cycle tracking (max 3 retries) |
| **Parallel Delegation** | `delegate` / `delegate-batch` / `jobs` для multi-agent orchestration |
| **Evidence Tracking** | Обязательное подтверждение на каждой фазе: команды, скриншоты, тесты |
| **Context Budget** | 4-tier дисциплина для управления LLM контекстом |
| **SQLite Ready** | Atomic state persistence (планируется) |

---

## 🚀 Quick Start

```bash
git clone https://github.com/FerrPOINT/project-workflow-cli.git
cd project-workflow-cli
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
hrflow --help
```

---

## 🖥️ CLI Commands

### Human Mode (Rich)
```bash
hrflow init TASK-123 "Implementation of auth system"
hrflow phase TASK-123 "3.0"
hrflow next TASK-123
hrflow status TASK-123
hrflow verify TASK-123
hrflow list-phases
hrflow playbook TASK-123 "7.6"
hrflow audit TASK-123
hrflow next-step TASK-123
hrflow rollback TASK-123 4.0 --reason "CriticGate BLOCKER: missing tests"
hrflow delegate TASK-123 reviewer
hrflow delegate-batch TASK-123 reviewer,qa
hrflow jobs
```

### Agent Mode (JSON)
```bash
hrflow --json init TASK-123 "Auth system"
hrflow --json next-step TASK-123
hrflow --json check-env
hrflow --json playbook TASK-123 "7.6"
hrflow --json rollback TASK-123 5.5 --reason "QA FAIL"
```

---

## 📋 42-Phase Workflow

| Group | Phases | Purpose | Gates |
|-------|--------|---------|-------|
| **Preflight** | 0.0–0.9 | Tool check, task intake, setup | PF (0.0), PF (0.5) |
| **Discovery** | 1.0–1.5 | Code discovery, deep research | CG-1 (self), CG-1.5 |
| **Plan** | 2.0–3.5 | Requirements, implementation plan | CG-2, CG-3 (BLOCKER) |
| **Develop** | 4.0–4.5 | TDD implement, pre-commit review | CG-4 (self), CG-4.5 (BLOCKER) |
| **Validate** | 5.0–5.5 | Compile, test, security scan, self-test | CG-5, CG-5.5 |
| **Commit** | 6.0 | Commit + push | CG-6 |
| **Review** | 7.0–7.7 | MR draft, code review, QA, Dataflow, CriticGate | CG-7.5, CG-7.6, CG-7.7 |
| **Done** | 8.0 | Jira transition, completion | — |
| **Improve** | 9.0–10.9 | Cleanup, retro, IP generation | CG-10 (self) |

**Ключевые правила:**
- **Entry/Exit Ritual** — обязательный чеклист перед входом и после выхода из каждой фазы
- **Evidence Required** — каждая фаза требует concrete evidence (вывод команды, скриншот, результат теста)
- **No Skip Allowed** — только последовательное прохождение, нет shortcuts
- **Max 3 Feedback Cycles** — cycle 4 эскалирует к CTO

```mermaid
flowchart LR
    subgraph Preflight["0. Preflight"]
        P0[0.0 Tool Check] --> P06[0.6 Team Setup]
        P06 --> P07[0.7 Repos Sync]
        P07 --> P05[0.5 Jira In Progress]
    end
    subgraph Discovery["1. Discovery"]
        D1[1.0 Preflight] --> D15[1.5 Deep Research]
    end
    subgraph Plan["2-3. Plan"]
        PL2[2.0 Research] --> PL3[3.0 Plan]
        PL3 --> PL35["3.5 CG-3 BLOCKER"]
    end
    subgraph Develop["4. Develop"]
        DEV4[4.0 Implement] --> DEV45["4.5 CG-PreCommit"]
    end
    subgraph Validate["5. Validate"]
        V5[5.0 Tests] --> V55["5.5 Self-Test"]
    end
    subgraph Review["7. Review"]
        R7[7.0 MR Draft] --> R75["7.5 Code Review"]
        R75 --> R76["7.6 QA Test"]
        R76 --> R76R["7.6.R Dataflow"]
        R76R --> R77["7.7 CG-PostQA"]
    end
    subgraph Done["8. Done"]
        D8[8.0 Jira Выполнено]
    end

    Preflight --> Discovery
    Discovery --> Plan
    Plan --> Develop
    Develop --> Validate
    Validate --> Commit[6.0 Commit]
    Commit --> Review
    Review --> Done
```

---

## 🏗️ Architecture

```mermaid
flowchart TD
    subgraph CLI["🖥️ CLI Layer"]
        A[Human Mode / Rich]
        B[Agent Mode / --json]
    end
    subgraph Engine["⚙️ Engine"]
        C[Phase Parser]
        D[State Machine]
        E[Gate Evaluator]
        F[Evidence Validator]
    end
    subgraph Agents["🤖 Agent Layer"]
        G[Profiles Registry]
        H[Job Tracker]
        I[Delegate Payload Generator]
    end
    subgraph Storage["💾 Storage"]
        J[(progress.json)]
        K[(SQLite WAL)]
        L[(checkpoints/)]
    end
    subgraph External["🌐 Integrations"]
        M[Jira REST]
        N[GitLab REST]
        O[Git CLI]
        P[Env Vars]
    end

    A --> C
    B --> C
    C --> D
    D --> E
    D --> F
    E --> G
    G --> H
    H --> I
    D --> J
    D --> K
    E --> L
    D --> M
    D --> N
    D --> O
    D --> P
```

### Module Structure

```
wartz_workflow/
├── cli.py              # Click CLI с dual output (Rich + JSON)
├── config.py           # Constants, paths, API endpoints
├── state.py            # Task state (JSON + atomic SQLite)
├── phases.py           # Phase management, checklists
├── schema.py           # YAML → dataclasses parser
├── engine.py           # Phase execution engine
├── verify.py           # verify-suite, .gitignore, tokens
├── jira_gitlab.py      # Jira REST + GitLab API integration
├── profiles.py         # Agent profile registry
├── jobs.py             # Job tracking для background tasks
├── rollback.py         # Rollback engine с cycle tracking
└── references/
    └── phases.yaml     # Declarative 42-phase schema

tests/
├── test_cli_integration.py
├── test_jobs.py
├── test_phases.py
├── test_profiles.py
├── test_rollback.py
├── test_state.py
└── test_verify.py
```

---

## 🛡️ Quality Bar

| Metric | Target | Current |
|--------|--------|---------|
| Test Coverage | ≥ 80% | 47% |
| Passing Tests | 58/58 | ✅ |
| Lint | ruff + mypy | ✅ |
| CI Pipeline | pytest + ruff + mypy | ✅ |
| Security Scan | Semgrep, Bandit | Planned |

```bash
# Run tests with coverage
pytest tests/ -v --cov=wartz_workflow --cov-report=term

# Run linting
ruff check wartz_workflow/
mypy wartz_workflow/
```

---

## 🎯 Roadmap

```mermaid
mindmap
  root((Roadmap))
    Done
      42 phases
      Gate taxonomy
      Rollback engine
      Parallel delegation
    In Progress
      Test coverage 47% → 80%
      Evidence validator YAML rules
    Planned
      SQLite atomic persistence
      Jira transition integration
      GitLab MR state checks
      Auto-delegate payload generation
      Audit report command
```

---

## 📫 Links

<p align="center">
  <a href="https://github.com/FerrPOINT"><img src="https://img.shields.io/badge/GitHub-FerrPOINT-181717?logo=github&logoColor=white" /></a>
  <a href="mailto:ferruspoint@mail.ru"><img src="https://img.shields.io/badge/Email-ferruspoint@mail.ru-EA4335?logo=gmail&logoColor=white" /></a>
  <a href="https://t.me/ferrpoint"><img src="https://img.shields.io/badge/Telegram-@ferrpoint-26A5E4?logo=telegram&logoColor=white" /></a>
</p>

<p align="center">
  <img src="https://capsule-render.vercel.app/api?type=waving&height=100&section=footer&color=gradient&customColorList=0,2,2,5,30" />
</p>

---

<details>
<summary><b>Почему Python и такая архитектура</b></summary>

- **Python 3.11** — выбран как практичный стандарт для CLI-инструментов и backend automation. Click + Rich дают production-ready интерфейс без overengineering.
- **YAML как single source of truth** — 42 фазы описаны декларативно, что позволяет менять workflow без правки кода. Это отличает подход от hard-coded процессов.
- **SQLite WAL в планах** — atomic state persistence без зависимостей от внешних сервисов. Сейчас JSON с очисткой, но WAL обеспечит надёжность.
- **Dual-mode CLI** — одна команда работает и для человека (Rich таблицы), и для агента (JSON). Это критично для AI-agent workflow, где агенты читают JSON, а люди — Rich.
- **Gate taxonomy** — вместо хаотичных "проверь это" введены 4 типа gate'ов с чёткими правилами: PF (проверка перед входом), RV (блокирующая проверка после), ES (эскалация к человеку), AB (остановка workflow).
- **Evidence tracking** — любая фаза не считается завершённой без concrete evidence. Это предотвращает "кажется ок" и требует либо вывод команды, либо скриншот, либо результат теста.
- **Не CrewAI/OpenAI Swarm** — нативная интеграция с Hermes `delegate_task`. Это даёт контроль над payload'ом и не привязывает к внешним фреймворкам.

</details>
