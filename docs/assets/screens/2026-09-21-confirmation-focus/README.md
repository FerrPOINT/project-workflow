# Confirmation dialog focus smoke

These screenshots render the current `agents.html` Jinja template with one fixture agent. The live UI requires SSO, so this is not an authenticated runtime screenshot.

- `confirmation-375-{dark,light,gray}.png`: mobile dialog in all supported themes.
- `confirmation-1280-{dark,light}.png` and `confirmation-1920-light.png`: desktop dialog.

Chromium checks covered Tab/Shift+Tab focus containment, background inertness, focus restoration after Escape, Cancel, Confirm and backdrop dismissal, viewport changes while the dialog was open, page errors, and serious/critical axe violations. No API writes were made.
