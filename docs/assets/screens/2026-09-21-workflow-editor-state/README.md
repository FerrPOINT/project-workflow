# Workflow editor state smoke

These screenshots render the current `workflows.html` Jinja template with a protected default workflow and one editable fixture. The live UI requires SSO, so this is not an authenticated runtime screenshot.

- `workflow-default-1280-light.png`: protected default workflow with an explicit explanation.
- `workflow-delete-1280-light.png`: named destructive confirmation with safely rendered markup-like text.
- `workflow-create-375-dark.png`: mobile creation mode with focus in the required name field.

Chromium checks covered selection semantics, default deletion protection, required-field validation, save/delete pending states, draft preservation after API errors, create/cancel focus, mobile picker behavior, horizontal overflow, page errors, and serious/critical axe violations. Mock API requests returned errors; no live data was changed.
