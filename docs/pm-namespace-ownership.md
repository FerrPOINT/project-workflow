# PM Namespace Ownership v1

This bounded foundation provisions immutable Workflow authority. It does not
prepare/admit an assignment, issue a workspace receipt, validate a requested
Fleet agent, or permit dispatch. Tracker reservation remains dispatch-disallowed.
Tracker owns allocation UUIDs/version/SDLC ordinal and immutable creation input;
later admission must validate the real concrete Fleet agent, not its selector.

## Provisioning And Readback

`PUT /api/pm/namespace-ownership/{namespace_id}` requires exactly the strict body:

```json
{"contract_version":1,"tracker_instance_ref":"tracker-instance","tracker_project_ref":"cccccccc-cccc-4ccc-8ccc-cccccccccccc"}
```

The example is a wire example, not a receipt or deployed mapping. Instance refs
are exact strings of 1..128 UTF-8 bytes without whitespace, C0/C1 controls; no
trimming, case folding or Unicode normalization. UUIDs are canonical lowercase
and non-nil. Caller issuer/subject/receipt/timestamp fields are forbidden.
The byte bound matches Fleet `PmExecutionIdentity` / `valid_ref`, not Python
character count. Unicode scalar strings within that byte budget remain unchanged;
invalid UTF-8/surrogates are rejected. Generated schema records `x-max-utf8-bytes`
because standard JSON Schema maxLength counts characters, not UTF-8 bytes.

First PUT returns 201; identical ownership returns 200 with the original result.
Changed owner pair or authority issuer returns 409 without mutation. Mapping is
write-once, including issuer, actor, UUID and timestamp: no update/delete route
or repository method, PostgreSQL/SQLite migration UPDATE/DELETE rejection, and
namespace FK RESTRICT. A display prefix never establishes ownership.

`GET /api/pm/namespace-ownership/{namespace_id}` returns 200 with:

```text
{ok:true,result:{contract_version:1,ownership_ref,namespace_id,
 tracker_instance_ref,tracker_project_ref,authority_issuer,
 provisioner_subject,created_at}}
```

Readback is the stored mapping, not a new authorization/dispatch receipt. Every
request freshly authenticates. Responses use Cache-Control: no-store. Errors
are typed 401/403, missing mapping/namespace 404, immutable conflict 409,
strict wire 422, unavailable/malformed dependency/configuration 503. Remote
errors, URLs and PATs are not returned. There is no default-success dependency
fallback. Generated wire lives in `pm-continuation-openapi.json`.

## Exact Machine Authorization

Set `PROJECT_WORKFLOW_NAMESPACE_PROVISIONER_SUBJECT` to a distinct trusted
provisioner central subject, canonical non-nil UUID. Empty/invalid configuration
disables this API even when optional browser SSO is disabled. This is an explicit
machine allowlist, not a browser admin role or Tracker's human task owner.

Both `AUTH_ISSUER` and `AUTH_INTERNAL_BASE_URL` must be fixed operator-configured
HTTP(S) roots without credentials, path prefixes, query or fragment. Opaque PAT
authority is verified by fresh Base `/auth/tokens/introspect` at that trusted
root, not by a caller `iss` claim. The recorded issuer comes from configuration.
Introspection uses 5-second network timeouts/body deadline, at most 16 KiB,
identity encoding, no redirects, retries, proxy-env routing or auth cache.

PUT requires the pinned subject and `project-workflow:write`; GET requires the
same registered subject and `project-workflow:read`. Only standard service
read/write scopes are accepted, without duplicates, wildcard or compound grants.
GET additionally checks the persisted issuer/provisioner identity; PUT cannot
reown an existing mapping after subject/issuer configuration changes. The existing
canonical PM namespace, Tracker binding, immutability and enrollment guards remain.
Cookie/session JWT, local/runtime/assignment/catalog tokens, human admin status
and a PAT scope alone cannot provision or read this authority.

Issuer audit on 2026-10-03 corrected the earlier impossible extra-scope
requirement: Base's actual PAT creation accepts ONLY registered `service:read`
and `service:write`. No delegated compound namespace scopes are assumed. Issue
the standard PAT for the explicitly registered machine subject outside this
change. No Base configuration or live credential is modified here, and no root
PAT is handed to an agent. This namespace ownership readback is not Base runtime
execution or terminal receipt admission.

## Locks And Enrollment

Provisioning and first PM bind take the existing catalog shared transaction lock,
then Project FOR NO KEY UPDATE row lock. First bind next takes the existing owner Task lock.
This serializes ownership while permitting FK KEY SHARE from a generic
continuation INSERT that already owns Task; FOR UPDATE would deadlock that path.
Catalog bootstrap takes its exclusive catalog lock first. Ownership adds no
Task-to-Project lock edge to continuation/step paths. A blocked contender rereads
the ownership after Project lock acquisition. SQL uniqueness fences namespace
and reverse instance/project conflicts. Provisioning also rejects incompatible
existing immutable PM enrollment; it does not backfill an execution ledger.

New PM enrollment requires matching persisted ownership before callback/run
mutation. Missing mapping fails closed. Exact historic bind replay runs before
this new check; legacy PM readback/checkpoint/resume/rebind retain their existing
identity and fences without retroactive mapping synthesis. Generic non-PM
assignment/delivery DTOs and PM identity ten/callback eighteen fields stay intact.

## Migration And Product Limits

Only pending `0007_pm_execution`, after accepted `0006`, adds the optional table;
existing namespaces receive NO inferred ownership. Published migrations and
assignment/PM history are not rewritten. Fresh/0006 upgrade is supported. An
already-applied old pending 0007 without the new table is schema-not-ready;
`upgrade head` does not silently repair it. Preserve such snapshots; recreate
only explicitly owned disposable QA databases, never shared runtime data.

Current managed catalog admits one PM namespace per Workflow database. Therefore
this rollout supports ONE explicitly provisioned Tracker instance/project pair.
A second project/instance cannot reuse it, regardless of equal display keys.
Multi-project namespace/routing support is a remaining product gap, not completed
by this mapping. Required PMDraftAdmission, real workspace producer, exact owner
CAS/reservation coordination, replacement history/quiescence, trusted concrete
agent validation and real pinned native-skills release remain separate blockers.

This foundation is implementable without a skills manifest, but does not bypass
runtime compatibility/readiness. A genuine source-pinned manifest and build are
still required for runnable PM admission; no synthetic workspace/skill receipts
or happy-path admission endpoint are included.
