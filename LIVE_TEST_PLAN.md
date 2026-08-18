# Live smoke: CLI и Wizard

## Цель

На Relevanter Dev подтвердить реальный вызов настроенной Ollama Cloud модели и
fail-closed поведение существующего workflow. Полные feature/bug E2E находятся
в отдельном demo/autotests-контуре, а не в этом generic-репозитории.

## Предусловия

- `DATABASE_URL` указывает на тестовую project-workflow БД;
- существует обычный smoke workflow с разрешённым ключом `SMOKE-*`;
- `OLLAMA_BASE_URL=https://ollama.com/v1`;
- `OLLAMA_MODEL=kimi-k2.7-code:cloud`;
- `OLLAMA_API_KEY` установлен в окружении сервиса.

## Сценарии

1. Полный текстовый отчёт текущей фазы:
   - `step --task` возвращает инструкции, checks и evidence;
   - `step --report` передаёт выполненные пункты и ссылки на evidence;
   - Wizard реально вызывает указанную модель;
   - ожидается `PASS` и ровно один переход из существующей FSM.
2. Неполный текстовый отчёт новой задачи:
   - обязательные пункты явно остаются незавершёнными;
   - Wizard вызывается той же моделью;
   - ожидается `SOFT_FAIL` или `BLOCKED` без перехода вперёд.
3. Отдельно отключить provider и повторить submit:
   - ожидается `BLOCKED`;
   - переход отсутствует;
   - причина и отчёт присутствуют в `history`.

Запуск первых двух сценариев:

```bash
bash scripts/test_cli_live.sh
```

Для каждого результата проверить поле `wizard.model`, текст `report`, feedback и
фактический transition через:

```bash
project-workflow --json history --task <SMOKE-KEY> --n 20
```
