# PM review revision bridge

This additive producer path separates Tracker review authority from Workflow's
internal assignment CAS. It uses existing single-task PM instructions, routes,
execution/checkpoint ledger and terminal receipts. It adds no workflow mode,
scheduler, controller, Hermes change or pre-model hook.

## Admission

The trusted adapter submits `SingleTaskPMReviewAssignmentRequest` to existing
`POST /internal/runtime/assign`, using its existing PM assignment credential.
The base single-task request retains actual task, task revision, root, execution,
assignment, agent, lease and input references. The required `pm_review_context` is:

```text
purpose = critical_business_review
tracker_assignment_revision = reservation.assignment.version (2 or greater)
owner_version = reservation.owner_cas.version (2 or greater, independent)
blocker_id, blocker_sha256, blocker_version = saved Tracker review context
requirements = {revision, content_hash} from that saved context
```

The context and nested requirements are closed typed objects. Versions are strict
integers bounded by Tracker's safe-version limit. Owner version is not assignment
revision: for example, assignment8/owner2 is valid, as is assignment2/owner3.
The existing single-task `task_revision` is a fourth independent value, supplied
from Tracker's resulting task revision, never from `owner_cas.version` or either
assignment counter. Focused fixtures distinguish task89/assignment8/owner2/sink1.

Only `single-task-v1:project_manager`, mode `draft`, stage `Draft`, business scope,
cycle0/attempt1 and a new sink cursor (`expected_revision=0`, status `missing`)
are admitted. Existing namespace ownership must match Tracker instance/project.
Task/root identity remains unchanged; the new execution's actual task key is not
an invented replacement of the business task. The original reservation key stays
`pm-draft:<assignment UUID>`, including for critical review.

Workflow retains the context in immutable assignment payload/hash and returns it
as `result.pm_review_context`. `result.assignment_revision` remains the real sink
revision, normally 1 for the new cursor; it does not pretend Tracker's revision
was 1. Existing predecessor-terminal, sealed history and native readback checks
remain mandatory before admitting/enrolling another PM execution.

## Binding and Continuation

- Existing `/internal/runtime/bind`, step and history use the returned Workflow
  sink revision, not Tracker authority. The original binding hashes the whole
  immutable assignment, including review context.
- Existing `/internal/runtime/v1/pm/bind` accepts typed `SingleTaskPMReviewBind`.
  Its `assignment_revision` is actual Tracker2+, and its required
  `workflow_assignment_revision` is the independently returned sink revision.
  Both must match saved assignment state. Ordinary PM bind cannot enroll a review.
- PM snapshot identity, checkpoint, resume, rebind, observations and scoped tokens
  retain the authoritative Tracker revision. The saved mapping, not a caller's
  owner version or an implicit fallback, resolves the internal sink revision.
- Generic terminal receipt/history retain their true Workflow cursor identity;
  the existing assignment/context hashes also retain review authority. No native
  EOF, human text or Stop ACK becomes business or terminal proof.

Same-key changed context is rejected, including changes to owner version,
requirements or blocker hash. Malformed saved review context is rejected rather
than treated as a legacy assignment. Existing checkpoint/unknown-acceptance,
typed input, terminal and scope guards are unchanged.

## Compatibility and Qualification Boundary

`POST /internal/runtime/v1/pm/assign` remains strictly initial `PMDraftAssignment`
with assignment1/owner1 and its original canonical key/body. Legacy and ordinary
single-task requests/responses omit review context and the new bind sink field.
No table, migration, catalog/pin change or schema snapshot regeneration belongs
to this packet. Integrators must adapt review callers to the two explicit revisions
and separately regenerate/qualify generated clients where required.

Focused synthetic SQLite/HTTP tests live in
[test_pm_review_revision_bridge.py](../tests/test_pm_review_revision_bridge.py).
These are not live Tracker authorization, installed rollout, real native dispatch
or end-to-end review completion qualification. The earlier PostgreSQL preservation
result remains scoped to its original source and cases; it does not qualify this
new revision-bridge implementation.
