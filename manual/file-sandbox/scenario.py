"""File fixtures and phase contracts for the explicitly invoked agent/advisor proof."""

from __future__ import annotations

import csv
import hashlib
import io
import json
from pathlib import Path

CASES = (
    ("project_manager", "draft"),
    ("analyst", "analysis"),
    ("architect", "decomposition"),
    ("developer", "initial"),
    ("developer", "rework"),
    ("reviewer", "delivery"),
    ("tester", "delivery"),
    ("devops", "delivery"),
)


def case_id(role: str, mode: str) -> str:
    return f"{role}-{mode}"


def fixture(index: int) -> dict[str, str]:
    role, mode = CASES[index]
    label = case_id(role, mode)
    return {
        "notes.md": f"# {label}\nState: draft\nKeep this sentence unchanged.\n",
        "settings.json": json.dumps({"case": label, "enabled": False, "limit": index + 2}, indent=2) + "\n",
        "items.csv": f"id,qty,price_cents\na,2,{100 + index}\nb,3,{50 + index}\n",
        "calculator.py": 'def total(rows):\n    return sum(row["price_cents"] for row in rows)\n',
        "obsolete.txt": "This obsolete sample must be removed during phase 2.\n",
    }


def total_for(index: int) -> int:
    return 2 * (100 + index) + 3 * (50 + index) + 4 * (25 + index)


def phases(index: int, *, include_business_flow: bool = True) -> list[dict]:
    role, mode = CASES[index]
    label = case_id(role, mode)
    rules = (
        f"Файловую работу выполняй только в каталоге {label}. "
        "Штатные CLI Workflow и Tracker разрешены для этого тестового задания. "
        "Не обращайся к соседним каталогам, секретам, посторонней сети, git или реальным проектам. "
        "Отчёт — только о фактически выполненном. Решение PASS/PARTIAL принимает advisor. "
        "Не редактируй файлы проверяющего модуля и не подменяй его результаты. "
    )
    before_final = ""
    if role == "project_manager" and include_business_flow:
        before_final = (
            " Перед финальным отчётом прочитай текущий контекст задачи и все страницы обсуждения через "
            "task-tracker CLI. Опубликуй редакцию требований к этому файловому заданию штатной командой "
            "Tracker и запроси подтверждение конкретной редакции у владельца. Не подтверждай за него: "
            "при ожидании задай вопрос и остановись до настоящего ответа. После сохранённого "
            "подтверждения передай его фактические revision и content_hash в финальном Workflow CLI "
            "отчёте через --requirements-revision и --requirements-sha256. Это выполняется до отчёта. "
            "Действия после complete=true: оставь итоговый комментарий через Tracker CLI и выполни "
            "разрешённое завершение с полученным Workflow receipt. Они не являются условиями оценки "
            "текущего отчёта: будущего receipt, комментария или перехода до PASS ещё нет. "
            "PM заканчивает в Backlog / Ready и не запускает Analyst."
        )
    definitions = [
        (
            "Инвентаризация",
            "Прочитать исходные файлы и описать исходное состояние.",
            "Прочитай все пять исходных файлов. Создай inventory.md: перечисли их имена, "
            "исходные значения settings.json и две строки items.csv. Укажи ошибку calculator.py "
            "на конкретном расчёте. Остальные исходные файлы пока не изменяй.",
            [
                "inventory.md содержит все пять исходных имён и фактические значения.",
                "Приведён расчёт, показывающий потерю множителя qty.",
                "Пять исходных файлов остались неизменными.",
            ],
        ),
        (
            "Изменения",
            "Выполнить создание, изменение и удаление разных файлов.",
            f"В notes.md замени только State: draft на State: reviewed. В settings.json включи enabled "
            f"и установи limit={2 * (index + 2)}, сохрани case. В CSV добавь строку c,4,{25 + index}; "
            "сохрани существующие строки. Исправь pure-функцию total(rows) в calculator.py: сумма "
            "qty * price_cents для словарей с целыми неотрицательными значениями, пустой список даёт 0. "
            "Не используй I/O, imports или побочные эффекты внутри calculator.py. Удали obsolete.txt. "
            f"Создай result.json с точными полями case={label}, total_cents={total_for(index)}, item_count=3. "
            "Создай test_calculator.py с unittest для пустого списка, qty>1 и нулевого количества. "
            "В SUMMARY.md запиши роль, режим, изменения и реально выполненные команды.",
            [
                "Markdown и JSON изменены согласно заданию, исходная контрольная строка сохранена.",
                "CSV содержит исходные строки и новую строку c без дубликатов.",
                "total умножает цену на количество и обрабатывает пустой список и qty=0.",
                "obsolete.txt удалён, result.json и test_calculator.py действительно созданы.",
            ],
        ),
        (
            "Проверка и исправление",
            "Проверить результат и устранить замечания advisor.",
            "Выполни python -B -m unittest -v test_calculator.py. Проверь все файлы из задания, "
            "включая удаление obsolete.txt и точные поля result.json. Исправь обнаруженные ошибки "
            "и повтори тесты. Обнови SUMMARY.md фактическими командами и выводом; укажи роль и режим. "
            "Не объявляй успех при упавшем тесте или непроверенном файле." + before_final,
            [
                "unittest реально выполнен успешно; отчёт содержит команду и результат.",
                "Итоговые файлы согласованы с CSV и результатом total.",
                "Замечания предыдущего ответа advisor устранены либо честно отмечены.",
            ],
        ),
    ]
    return [
        {
            "code": f"SBX-{index + 1:02d}-{number:02d}",
            "name": name,
            "description": description,
            "phase_order": number,
            "instructions": [{"description": rules + instruction, "skills": [], "execution_type": "sync"}],
            "checks": checks,
            "evidence": [
                "Фактическое содержимое файлов, команды и результаты в отчёте агента.",
                "Отчёт агента с командами, результатами и оставшимися замечаниями.",
            ],
        }
        for number, (name, description, instruction, checks) in enumerate(definitions, 1)
    ]


def catalog(*, direct: bool = False) -> dict:
    workflows = []
    for role in dict(CASES):
        modes = []
        for index, (case_role, mode) in enumerate(CASES):
            if case_role == role:
                modes.append(
                    {
                        "key": mode,
                        "name": mode,
                        "mode_order": len(modes) + 1,
                        "execution_scopes": [
                            "business" if role in {"project_manager", "analyst", "architect"} else "delivery"
                        ],
                        "phases": phases(index, include_business_flow=not direct),
                    }
                )
        workflows.append(
            {"key": f"{'file-sandbox-direct-v1' if direct else 'file-sandbox-v1'}:{role}",
             "role_key": role, "name": f"{'Прямой CLI' if direct else 'Песочница'}: {role}", "modes": modes}
        )
    return {"schema": "workflow-file-sandbox/v1", "test_only": True, "workflows": workflows}


def snapshot(folder: Path) -> dict[str, dict[str, str]]:
    if folder.is_symlink() or not folder.is_dir():
        raise ValueError("Case must be its own directory, not a link")
    result = {}
    for path in sorted(folder.iterdir()):
        if path.is_symlink() or not path.is_file() or path.stat().st_size > 32_000:
            raise ValueError(f"Unexpected directory, link or oversized file: {path.name}")
        content = path.read_bytes()
        result[path.name] = {
            "sha256": hashlib.sha256(content).hexdigest(),
            "text": content.decode("utf-8").replace("\r\n", "\n"),
        }
    return result


def verify(folder: Path, index: int, *, initial: bool = False) -> list[str]:
    files = snapshot(folder)
    expected = fixture(index)
    failures = []
    if initial:
        for name, text in expected.items():
            if files.get(name, {}).get("text") != text:
                failures.append(f"Initial file changed: {name}")
        inventory = files.get("inventory.md", {}).get("text", "")
        if not all(name in inventory for name in expected):
            failures.append("Missing inventory or source names")
        return failures
    label = case_id(*CASES[index])
    if files.get("notes.md", {}).get("text") != expected["notes.md"].replace("State: draft", "State: reviewed"):
        failures.append("notes.md differs from the requested edit")
    try:
        settings = json.loads(files["settings.json"]["text"])
        if (
            settings != {"case": label, "enabled": True, "limit": 2 * (index + 2)}
            or type(settings["enabled"]) is not bool
        ):
            failures.append("settings.json values differ")
        rows = list(csv.DictReader(io.StringIO(files["items.csv"]["text"])))
        wanted = [
            {"id": key, "qty": str(qty), "price_cents": str(price)}
            for key, qty, price in (("a", 2, 100 + index), ("b", 3, 50 + index), ("c", 4, 25 + index))
        ]
        if rows != wanted:
            failures.append("CSV source rows/new row differ")
        if json.loads(files["result.json"]["text"]) != {
            "case": label,
            "total_cents": total_for(index),
            "item_count": 3,
        }:
            failures.append("result.json differs from independent arithmetic")
    except (KeyError, ValueError):
        failures.append("Missing or malformed JSON/CSV output")
    if "obsolete.txt" in files:
        failures.append("obsolete.txt was not removed")
    for name in ("inventory.md", "test_calculator.py", "SUMMARY.md", "calculator.py"):
        if not files.get(name, {}).get("text", "").strip():
            failures.append(f"Missing {name}")
    summary = files.get("SUMMARY.md", {}).get("text", "")
    if not all(value in summary for value in CASES[index]):
        failures.append("SUMMARY.md omits profession/mode")
    return failures
