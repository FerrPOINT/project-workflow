# Base Image Catalog Selection

The immutable builder accepts `--catalog-profile legacy-v2` (default) or
`--catalog-profile base-v3`. The profile selects a fixed packaged artifact, not a
user-supplied path, runtime environment setting, API flag or execution permission.
Both images retain the canonical v2 and Base v3 source artifacts.

```text
uv run --isolated --with-requirements constraints.txt --all-extras python -m scripts.build_runtime_image build --revision <committed-workflow-sha> --image <candidate-image> --skills-root <authorized-base-checkout>/agent-skills --catalog-profile base-v3
```

Base input is read from the exact private Git pin, with bounded/no-replacement
reads and the existing package verifier. Dirty source files do not replace the
archived candidate or pinned package. The exporter executed by the builder comes
from the same archived Workflow revision that Docker installs. The Base candidate
must also match its frozen source Git blob and package revision.

The generated `runtime-catalog-selection.json` binds the fixed profile to the
build source revision. Docker verifies source provenance and compatibility before
installation, then copies selection, compatibility and native skills manifest
into the runtime image. Startup re-derives compatibility from installed catalog
bytes and rejects missing, invalid, mismatched or altered metadata. `init_db`
checks image selection before acquiring a database engine or applying migrations.
Source/development startup without image metadata still defaults to v2.

The v3 image uses `base-sdlc/owner-admission-pending/v1` as its build-policy pin.
Its hash includes the installed owner-admission guard source, normalized to LF.
This is intentionally not `hermes-sdlc-runtime/v2`: the authenticated legacy
capability endpoint returns not-ready rather than advertising assign/step dispatch
on the strength of a catalog build. The existing trusted-owner guard remains
unconditional. Source-only Base endpoints do not become installed executor ACKs.

On a fresh database, the selected image initializes its packaged catalog. On a
canonical v2 database, v3 initialization uses the validated append-only
[adoption path](base-catalog-adoption.md). A failed adoption or interrupted append
must roll back the initialization transaction; retries retain historical IDs.
A v2 image must reject an already-v3 database, never downgrade it silently.

This supplies image selection and initialization, not production rollout.
Do not change pinned runtime images during the agreed QA freeze. Production
installation still needs protected backup/locks, a commit-to-image/config receipt,
qualified migration/data checks and the Base deployment procedure. Reverting an
image alone cannot downgrade an adopted database: rollback requires the agreed
protected pre-adoption database restore procedure, preserving the original backup.
Trusted Tracker/Fleet/Forge ACKs and executor-driven acceptance remain separate
requirements; no configuration or readiness override may waive them.
