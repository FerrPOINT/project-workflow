# Phase deletion context smoke

These screenshots render the current `phases.html` Jinja template with two fixture phases. The live UI requires SSO, so this is not an authenticated runtime screenshot.

- `phase-delete-375-dark.png`: named destructive confirmation on mobile.
- `phase-delete-1280-light.png`: named destructive confirmation on desktop.

Chromium checks covered a phase name containing markup-like characters, safe text rendering, target naming, focus restoration after Cancel, Escape and backdrop dismissal, menu state, horizontal overflow, page errors, and serious/critical axe violations. The confirmation was cancelled in every scenario; no API write was made.
