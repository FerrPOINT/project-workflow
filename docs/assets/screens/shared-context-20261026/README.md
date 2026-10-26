# Общий контекст Workflow: source UI evidence

Шаблон workflows.html использует действующий Base UI producer
`c2ca61094a904706fceeda8eb8f3b3cfd2e7cdfc`. Production template SHA-256:
`d50a16db513dd55fb952be966c9cd0c62f7a9b5b151e916847afc6071598bcde`.

- [Desktop](workflow-context-dark-desktop.png): реальные action groups формы,
  навигация режимов и controls фаз. Форма принудительно раскрыта только
  в частном presentation fixture; её сохранение и lifecycle не выполняются.
- [375 px iframe](workflow-context-dark-375.png): общий Select режима,
  RadioGroup, фазовые карточки и separated Notice. Внешняя белая страница
  и заголовок проверки принадлежат QA host, а не продуктовой оболочке.

В IAB проверены 24 сочетания catalog/form, light/dark/gray и native iframe
320/375/1920/2560: стабильная геометрия, отсутствие горизонтального overflow,
доступная навигация без дублирующей nav role. Ссылки и клавиатурный Select
различают одинаковые подписи по ID; сохраняются workflow/profession/scope.
RadioGroup меняет вид, phase jump переводит focus на выбранную фазу.

Содержимое отрендерено штатным Jinja и каноническими Base SSR assets;
view functions взяты из отрендеренного шаблона. Нет приложения, БД, Auth,
API записей, login bypass или внешнего runtime. Собственный read-only сервер
и вкладка закрыты; source hashes не изменились во время проверки.
Полный runtime/authenticated gate и настоящий browser zoom 200% остаются
отдельными проверками. Прежняя проекция с неотрендеренным JS выражением
отклонена и не засчитана; окончательный сценарий повторён после исправления.
