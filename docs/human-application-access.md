# Человеческие роли и приложения Workflow

Статус: feature-исходники, не установленная политика. Канон — Base
`docs/platform/HUMAN_APPLICATION_ACCESS.md`; экспорт SDK закрепляется Base pin.
Профессии и роли исполнителей не являются человеческими ролями.

## Вход и административные операции

SSO middleware получает текущую identity один раз от настроенного Auth,
проверяет proof через canonical Python SDK и помещает authority в request state.
JWT и PAT требуют приложение `project-workflow`; PAT сохраняет точный read/write
scope. Роль из proof актуальнее profile hint. Зарегистрированные технические
credentials не становятся людьми и не получают административные permissions.

`AUTH_APPLICATION_ACCESS_REQUIRED=true` включает обязательность действующего
`enforced` proof. Значение по умолчаниюfalse оставлено для этапа совместимого
rollout; оно не означает завершённую активацию. Настроенный Central Auth при
недоступности не переключается на standalone. Пустой app set возвращает403.
Страница отказа использует прежние theme tokens, показывает «Нет доступа» и
не предлагает повторный SSO для исправления отсутствующего разрешения.

Обычный пользователь читает процессы и выполняет разрешённые задания.
14 mutating routes профессий, workflow, фаз и инструкций объявляют общую FastAPI
admin dependency при регистрации. Страница создания профессии и редактор
инструкций также административные. CLI history/step, рабочие чтения и личная
CLI-справка не превращаются в общую конфигурацию.

Шаблоны используют ту же текущую authority через `can_administer`: обычный
пользователь видит процессы, фазы, инструкции и профессии без форм и действий
изменения. Просмотр, смена профессии/процесса/режима и Список/Схема сохраняются.
Редакторские scripts и autosave не публикуются в обычной странице. Это не
заменяет серверную dependency и не является проверкой открытой вкладки.

## Машинная совместимость

Namespace/Base reader introspection принимает новое поле `role=service_account`,
сохраняя exact registered subject и выдаваемые scopes. Human role, дажеadmin,
не открывает machine paths. Неизвестные claims не игнорируются. Существующий
строгий execution-context V2 не расширяется этой задачей.

## Открытые gates

Scoped SSO/machine/route checks подтверждают серверную часть, но не заменяют
commit fencing, UI freshness/cache, текущую authority владельца новых worker
стадий, совместное namespace admission и compatible cohort. Source flag не
является операторским guard активации. Filled migration/rollback, полный gate,
Docker/Kubernetes кандидаты, dev/IAB под user/admin и реальное задание остаются
отдельными обязательными этапами до заявления о завершении.
