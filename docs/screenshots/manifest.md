# Screenshot Manifest

README embeds a single desktop representative for each implemented semantic
layout mode. The full operational route table remains in the README; responsive
viewport QA stays in the capture tests and is not embedded in the README.

Capture source: `scripts/capture_ui_screenshots.mjs`; browser fixture is isolated
and read-only, with generic names and UI-testing copy. Captures use the default
product theme and full-page screenshots after route/content assertions.

| File | Route | Layout | Viewport | PNG dimensions | README |
|---|---|---|---|---|---|
| [dashboard.png](dashboard.png) | `/` | `wide` | 1920x1080 | 1920x1080 | yes |
| [settings.png](settings.png) | `/settings` | `reading` | 1920x1080 | 1920x1080 | yes |
| [task-detail-dev.png](task-detail-dev.png) | `/task/RUN-42` | `detail-with-aside` | 1920x1080 | 1920x2652 | yes |
| [wide.png](375x812/wide.png) | `/` | `wide` | 375x812 | 375x1152 | no |
| [reading.png](375x812/reading.png) | `/settings` | `reading` | 375x812 | 375x841 | no |
| [detail-with-aside.png](375x812/detail-with-aside.png) | `/task/RUN-42` | `detail-with-aside` | 375x812 | 375x4181 | no |

Responsive PNG dimensions are read by `tests/test_docs_quality.py`; route and
state coverage is asserted by the screenshot capture and live UI tests.
