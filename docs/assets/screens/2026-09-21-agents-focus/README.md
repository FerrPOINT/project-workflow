# Agents editor focus smoke

The screenshots show the current Jinja template rendered with three fixture agents. The live UI requires SSO, so these images do not represent an authenticated production session.

- `agents-{375,1280,1920}-{light,dark}.png`: collapsed list at mobile and desktop widths.
- `editor-375-dark.png`: expanded editor and action targets.
- `delete-confirm-375-dark.png`: confirmation naming the selected agent.

Chromium checks covered horizontal overflow, serious/critical axe violations, page errors, mobile action targets of at least 44 px, and focus after cancel, save, deletion of a middle agent, and deletion of the last agent. PUT and DELETE requests were mocked; no live data was changed.
