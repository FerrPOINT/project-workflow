# Namespace editor state smoke

These screenshots render the current `namespaces.html` Jinja template with one taskful namespace and two empty fixtures. The live UI requires SSO, so this is not an authenticated runtime screenshot.

- `namespace-protected-1280-light.png`: desktop editor with explicit deletion protection for a namespace that contains tasks.
- `namespace-delete-1280-light.png`: named destructive confirmation with safely rendered markup-like text and a bright accent preview.
- `namespace-create-375-dark.png`: compact mobile creation mode with focus in the required name field.

Chromium checks covered selection semantics, mobile picker synchronization, deletion protection, required-field validation, save/delete pending states, draft preservation after API errors, create focus, bright-accent foreground contrast, horizontal overflow, page errors, and serious/critical axe violations in light and dark themes. Delayed mock PUT and DELETE requests returned errors so pending and recovery states could be observed; no live data was changed.
