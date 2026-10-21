# Bootstrap HTTP assignment projection

Parent634ed8a98e0347b67009b15623f8e8b8e80075e9 (normal remote/UI merge).
One production line in pm_bootstrap_api.retry now uses the existing
runtime_api._assignment_response(result)["result"]. Existing {ok,result}
envelope, no-store, authorization, trusted callback and predecessor JSON/hash
are unchanged. No DTO, protocol, migration, pin or Hermes change.

Confirmed red case on the old producer: the real registered unbound HTTP
response contained id/project_id/description/bind_request_sha256/updated_at
and other private fields; exact canonical key assertion failed (37.55s).
The existing positive bound/unbound tests now independently assert all36
canonical Assignment keys, required scalar/nullable types, exact input refs,
unbound refs, no execution token and identical replay body without new HTTP.
They exercise configured synthetic Fleet callbacks and actual Workflow routes,
not a mocked PMBootstrapService return.

After correction: all12 tests/test_pm_bootstrap_http.py host cases PASS25.82s;
full Ruff, mypy142 source files and diff checks PASS. This is the HTTP contract
matching Fleet's closed Assignment shape; no Rust decoder execution is claimed.
The earlier scoped49 proof belongs to the prior byte-equal scope;
these12 tests qualify the additional projection change separately.

Draft followup PR141 includes actual master657bcaf1 through normal merge7e7b78ce;
its entire tree equals checked488. Main's one-case PG pilot passed, followed by
the affected full18 bootstrap6/retained2/health10 gate in138.243s,0skip. Actual
OpenAPI/PM consumer export parity and both cleanup checks passed. See the
catalog-scope handoff for exact source/evidence hashes. This is not live proof.
Critical-history timeout60 stays OPEN; no all3105 claim. Old prepared tuples
and failures remain immutable; PR140's closed branch was not pushed.
