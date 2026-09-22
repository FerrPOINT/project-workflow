# Structured phase editor browser QA

The screenshots were captured from the production Docker image at
`http://127.0.0.1:8812` after a real Central Auth login. The shared PostgreSQL
database supplied 19 phases; the test selected the most populated phase with
2 instructions, 4 checks and 3 evidence requirements. No application mutation
was sent.

Coverage:

- `light`, `gray` and `dark` themes;
- widths `320`, `375`, `768`, `960`, `961`, `1280`, `1920` and `2560`;
- desktop outline and mobile section selector at the `960/961` boundary;
- all four section targets, query preservation and active state;
- direct links to checks and evidence plus keyboard activation of the outline;
- natural scroll recovery after a programmatic section jump;
- horizontal overflow, visible targets below 40 px, page/HTTP errors and
  serious/critical axe violations.

The final result is 24/24 responsive/theme states with zero unexpected errors,
mutations, overflow, small visible targets or serious/critical axe violations.
`results.json` contains the machine-readable summary. The 15 PNG files retain
the three themes at mobile, breakpoint and wide-desktop widths.
