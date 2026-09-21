# CLI reference copy smoke

These screenshots render the current `settings.html` Jinja template with two neutral CLI fixtures. The live UI requires SSO, so this is not an authenticated runtime screenshot.

- `cli-copy-1280-light.png`: desktop reference after copying the complete `step` command.
- `cli-reference-375-dark.png`: compact mobile layout with copy actions stacked below command usage.
- `cli-empty-1280-light.png`: explicit empty state when the runtime command catalog is empty.

Chromium checks covered the exact clipboard payload, copy pending/success/error labels, focus restoration, 40 px action targets, heading hierarchy, empty state, mobile stacking, horizontal overflow, page errors, and serious/critical axe violations in light and dark themes. Clipboard behavior was isolated in the browser fixture; no live data was changed.
