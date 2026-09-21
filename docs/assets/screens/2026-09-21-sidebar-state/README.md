# Sidebar navigation state smoke

These screenshots render the current `agents.html` Jinja template with one fixture agent. The live UI requires SSO, so this is not an authenticated runtime screenshot.

- `sidebar-375-{dark,gray,light}.png`: open mobile drawer in every supported theme.
- `sidebar-{1280,1920}-light.png`: desktop sidebar and active section.

Chromium checks covered `aria-current`, background inertness, focus containment, Escape and backdrop dismissal, drawer reset after viewport resize, horizontal overflow, page errors, and serious/critical axe violations. No API writes were made.
