"""Actual PostgreSQL writer/freeze races; no SQLite or Auth mocks substitute these."""

import time
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from uuid import uuid4

import pytest
from sqlalchemy import event, text
from sqlalchemy.exc import DBAPIError

from project_workflow import config
from project_workflow.domain.identity_deletion import DeletionRequest
from project_workflow.infrastructure.db.identity_deletion import OwnerError, execute
from project_workflow.infrastructure.db.session import (
    ensure_migrated,
    get_engine,
    run_alembic_command,
    schema_is_ready,
)
from project_workflow.infrastructure.identity_deletion_auth import Authority
from tests import test_postgres_integration as pg_fixtures

pg_url = pg_fixtures.pg_url
pytestmark = pytest.mark.integration
ISSUER = "https://auth.example.test"


def authority(seconds=60):
    return Authority(ISSUER, time.monotonic() + seconds, time.time() - 1, time.time() + seconds)


def command(subject=None):
    return DeletionRequest.model_validate({"schema_version": 1, "operation_id": str(uuid4()),
        "inventory_revision": str(uuid4()), "identity": {"issuer": ISSUER, "subject": subject or str(uuid4())}})


@pytest.fixture
def owner(pg_url, monkeypatch):
    monkeypatch.setenv("AUTH_ISSUER", ISSUER)
    monkeypatch.setenv("PROJECT_WORKFLOW_IDENTITY_LEGACY_ISSUER", ISSUER)
    config.get_settings.cache_clear()
    engine = get_engine(pg_url)
    ensure_migrated(engine)
    assert schema_is_ready(engine)
    with engine.begin() as connection:
        workflow = connection.execute(text("INSERT INTO workflows(key,name,is_default) "
            "VALUES('identity-fixture','Identity fixture',0) RETURNING id")).scalar_one()
        mode = connection.execute(text("INSERT INTO workflow_modes(workflow_id,key,name,mode_order) "
            "VALUES(:workflow,'mode','Mode',1) RETURNING id"), {"workflow": workflow}).scalar_one()
        project = connection.execute(text("INSERT INTO projects(workflow_id,code,name,cli_command) "
            "VALUES(:workflow,'identity-fixture','Identity fixture','identity-fixture') RETURNING id"),
            {"workflow": workflow}).scalar_one()
    return engine, workflow, mode, project


def context(connection, owner, subject):
    _, workflow, mode, _ = owner
    connection.execute(text("INSERT INTO resource_execution_contexts(id,operation_id,request,verified_projection,"
        "workflow_id,mode_id,created_by_subject) VALUES(:id,:op,'{}','{}',:workflow,:mode,:subject)"),
        {"id": str(uuid4()), "op": str(uuid4()), "workflow": workflow, "mode": mode, "subject": subject})


def test_real_sources_receipt_replay_release_and_permanent_fence(owner):
    engine, _, _, project = owner
    target = command()
    assert execute("check", target, authority()).reference_count == 0
    with engine.begin() as connection:
        context(connection, owner, target.identity.subject)
        connection.execute(text("INSERT INTO pm_namespace_ownership(ownership_ref,namespace_id,tracker_instance_ref,"
            "tracker_project_ref,authority_issuer,provisioner_subject) "
            "VALUES(:id,:project,'fixture',:tracker,:issuer,:sub)"),
            {"id": str(uuid4()), "project": project, "tracker": str(uuid4()), "issuer": ISSUER,
             "sub": target.identity.subject})
    frozen = execute("freeze", target, authority())
    assert frozen.reference_count == 2
    assert execute("freeze", target, authority()) == frozen
    with engine.begin() as connection:
        with pytest.raises(DBAPIError) as rejected:
            context(connection, owner, target.identity.subject)
        assert rejected.value.orig.sqlstate == "23514"
    execute("release", target, authority())
    with engine.begin() as connection:
        context(connection, owner, target.identity.subject)
    with pytest.raises(OwnerError) as rejected:
        execute("freeze", target, authority())
    assert rejected.value.status == 409
    cancelled = command()
    execute("release", cancelled, authority())
    with pytest.raises(OwnerError):
        execute("freeze", cancelled, authority())
    unused = command()
    assert execute("freeze", unused, authority()).reference_count == 0
    with engine.begin() as connection:
        context(connection, owner, str(uuid4()))  # ordinary unrelated API/CLI writes remain supported
    for changed in [unused.model_copy(update={"inventory_revision": uuid4()}),
                    unused.model_copy(update={"identity": target.identity})]:
        with pytest.raises(OwnerError):
            execute("freeze", changed, authority())
    with pytest.raises(OwnerError) as expired:
        execute("release", unused, authority(-1))
    assert expired.value.status == 401


def test_freeze_drains_writer_and_rejects_old_repeatable_read_snapshot(owner):
    engine = owner[0]
    target = command()
    execute("check", target, authority())  # bind deployment issuer before writer
    entered = Event()

    def freeze():
        entered.set()
        return execute("freeze", target, authority())

    with ThreadPoolExecutor(max_workers=1) as workers:
        with engine.connect() as writer:
            tx = writer.begin()
            context(writer, owner, target.identity.subject)
            future = workers.submit(freeze)
            assert entered.wait(2)
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                with engine.connect() as observer:
                    waiting = observer.execute(text("SELECT count(*) FROM pg_stat_activity "
                        "WHERE datname=current_database() "
                        "AND wait_event='advisory' AND query LIKE '%714402216003%'" )).scalar_one()
                if waiting:
                    break
                time.sleep(0.02)
            assert waiting and not future.done()
            tx.commit()
        assert future.result(5).reference_count == 1
    target = command()
    with engine.connect().execution_options(isolation_level="REPEATABLE READ") as old:
        tx = old.begin()
        old.execute(text("SELECT * FROM identity_fence_epoch")).all()
        execute("freeze", target, authority())
        with pytest.raises(DBAPIError) as rejected:
            context(old, owner, target.identity.subject)
        assert rejected.value.orig.sqlstate == "40001"
        tx.rollback()


def test_all_sources_direct_dml_missing_epoch_and_actual_lock_timeout(owner, monkeypatch):
    engine = owner[0]
    target = command()
    execute("freeze", target, authority())
    monkeypatch.setenv("AUTH_ISSUER", "https://other-auth.example.test")
    monkeypatch.setenv("PROJECT_WORKFLOW_IDENTITY_LEGACY_ISSUER", "https://other-auth.example.test")
    config.get_settings.cache_clear()
    # Old-issuer authority is denied before touching the new deployment binding.
    with pytest.raises(OwnerError) as old_authority:
        execute("check", command(), authority())
    assert old_authority.value.status == 403
    assert old_authority.value.code == "identity_deletion_access_denied"
    # A coherent new-issuer command still cannot rebind the persisted old issuer.
    request = command().model_dump(mode="json")
    request["identity"]["issuer"] = "https://other-auth.example.test"
    changed_authority = Authority(
        request["identity"]["issuer"], time.monotonic() + 60, time.time() - 1, time.time() + 60
    )
    with pytest.raises(OwnerError) as rejected:
        execute("check", DeletionRequest.model_validate(request), changed_authority)
    assert rejected.value.code == "identity_legacy_issuer_conflict"
    assert rejected.value.status == 409
    monkeypatch.setenv("AUTH_ISSUER", ISSUER)
    monkeypatch.setenv("PROJECT_WORKFLOW_IDENTITY_LEGACY_ISSUER", ISSUER)
    config.get_settings.cache_clear()
    for table, document in [
        ("resource_execution_contexts", {"created_by_subject": target.identity.subject}),
        ("pm_namespace_ownership", {"authority_issuer": ISSUER, "provisioner_subject": target.identity.subject}),
    ]:
        columns = ",".join(document)
        params = ",".join(":" + item for item in document)
        with engine.begin() as connection:
            with pytest.raises(DBAPIError) as rejected:
                connection.execute(text(f"INSERT INTO {table}({columns}) VALUES({params})"), document)
            assert rejected.value.orig.sqlstate == "23514"  # fence before ordinary not-null/FK validation
    with engine.connect() as blocker:
        tx = blocker.begin()
        blocker.execute(text("SELECT pg_advisory_xact_lock_shared(714402216003::bigint)"))
        with pytest.raises(OwnerError) as rejected:
            execute("check", command(), authority())
        assert rejected.value.code == "identity_deletion_storage_unavailable"
        tx.rollback()
    with engine.begin() as connection:
        connection.execute(text("DELETE FROM identity_fence_epoch"))
    with pytest.raises(OwnerError):
        execute("check", command(), authority())
    with engine.begin() as connection:
        with pytest.raises(DBAPIError) as rejected:
            context(connection, owner, str(uuid4()))
        assert rejected.value.orig.sqlstate == "23514"


@pytest.mark.parametrize("predecessor", ["0016_human_project_commit_guard", "0017_human_application_clock"])
def test_populated_upgrade_preserves_context_history_and_bounded_inventory(pg_url, monkeypatch, predecessor):
    monkeypatch.setenv("AUTH_ISSUER", ISSUER)
    monkeypatch.setenv("PROJECT_WORKFLOW_IDENTITY_LEGACY_ISSUER", ISSUER)
    config.get_settings.cache_clear()
    engine = get_engine(pg_url)
    run_alembic_command("upgrade", engine, predecessor)
    def application_clock_snapshot():
        with engine.connect() as connection:
            definition = connection.execute(text(
                "SELECT pg_get_functiondef('workflow_application_clock_guard()'::regprocedure)"
            )).scalar_one()
            triggers = connection.execute(text(
                "SELECT c.relname,t.tgname,pg_get_triggerdef(t.oid) "
                "FROM pg_trigger t JOIN pg_class c ON c.oid=t.tgrelid "
                "JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname=current_schema() "
                "AND t.tgname IN ('workflow_application_write','workflow_application_commit') "
                "ORDER BY c.relname,t.tgname"
            )).all()
            assert len(triggers) == 34
            return definition, triggers

    before_clock = application_clock_snapshot() if predecessor == "0017_human_application_clock" else None
    target = command()
    with engine.begin() as connection:
        workflow = connection.execute(text("INSERT INTO workflows(key,name,is_default) "
            "VALUES('populated-identity','Populated fixture',0) RETURNING id")).scalar_one()
        mode = connection.execute(text("INSERT INTO workflow_modes(workflow_id,key,name,mode_order) "
            "VALUES(:workflow,'mode','Mode',1) RETURNING id"), {"workflow": workflow}).scalar_one()
        connection.execute(text("INSERT INTO resource_execution_contexts(id,operation_id,request,verified_projection,"
            "workflow_id,mode_id,created_by_subject) SELECT md5('id-' || n)::uuid::text,"
            "md5('operation-' || n)::uuid::text,"
            "'{}','{}',:workflow,:mode,:subject FROM generate_series(1,5000) n"),
            {"workflow": workflow, "mode": mode, "subject": target.identity.subject})
    ensure_migrated(engine)
    assert schema_is_ready(engine)
    after_clock = application_clock_snapshot()
    if before_clock is not None:
        assert after_clock == before_clock, "Owner migration must preserve the released application clock"
    result = execute("check", target, authority())
    assert result.reference_count == 5000
    with engine.begin() as connection:
        connection.execute(text("SET LOCAL statement_timeout='8s'"))
        for source in ("resource_execution_contexts", "pm_namespace_ownership"):
            plan = connection.execute(text(f"EXPLAIN (ANALYZE, FORMAT JSON) SELECT count(*) FROM {source} source "
                "WHERE EXISTS(SELECT 1 FROM workflow_identity_refs(:source,to_jsonb(source)) r "
                "WHERE r.issuer=:issuer AND r.subject=:subject)"),
                {"source": source, **target.identity.model_dump()}).scalar_one()
            assert plan[0]["Execution Time"] < 8000
            print(source, "rows=5000 inventory execution_ms=", plan[0]["Execution Time"])


def required_reference(connection, owner, source, subject):
    if source == "resource_execution_contexts":
        context(connection, owner, subject)
    else:
        connection.execute(text("INSERT INTO pm_namespace_ownership("
            "ownership_ref,namespace_id,tracker_instance_ref,"
            "tracker_project_ref,authority_issuer,provisioner_subject) "
            "VALUES(:id,:project,'blank-fixture',:tracker,:issuer,:subject)"),
            {"id": str(uuid4()), "project": owner[3], "tracker": str(uuid4()), "issuer": ISSUER, "subject": subject})


@pytest.mark.parametrize("blank", ["", "  "])
@pytest.mark.parametrize("source", ["resource_execution_contexts", "pm_namespace_ownership"])
def test_required_legacy_blank_subject_is_unknown_never_zero(owner, blank, source):
    engine = owner[0]
    target = command()
    with engine.begin() as connection:
        required_reference(connection, owner, source, blank)
    for action in ("check", "freeze"):
        with pytest.raises(OwnerError) as rejected:
            execute(action, target, authority())
        assert rejected.value.code == "identity_legacy_reference_unresolved"
    # Preserve the legacy row: the released PM namespace history is immutable.
    # Only this fixture's database is dropped by pg_url teardown.
    with engine.connect() as connection:
        assert connection.execute(text(f"SELECT count(*) FROM {source}")).scalar_one() == 1


@pytest.mark.parametrize("blank", ["", "  "])
@pytest.mark.parametrize("source", ["resource_execution_contexts", "pm_namespace_ownership"])
def test_required_blank_subject_is_denied_after_fence_on_a_fresh_database(owner, blank, source):
    engine = owner[0]
    execute("freeze", command(), authority())
    with engine.begin() as connection:
        with pytest.raises(DBAPIError) as rejected:
            required_reference(connection, owner, source, blank)
        assert rejected.value.orig.sqlstate == "23514"
    with engine.connect() as connection:
        assert connection.execute(text(f"SELECT count(*) FROM {source}")).scalar_one() == 0


@pytest.mark.parametrize("action", ["check", "freeze", "release"])
def test_original_owner_authority_expiring_inside_commit_rolls_back_every_effect(owner, action):
    engine = owner[0]
    target = command()
    execute("check", target, authority())
    if action == "release":
        execute("freeze", target, authority())

    def snapshot():
        with engine.connect() as connection:
            return (
                connection.execute(text("SELECT * FROM identity_deletion_operations ORDER BY operation_id")).all(),
                connection.execute(text("SELECT * FROM identity_legacy_issuer")).all(),
                connection.execute(text("SELECT * FROM identity_fence_epoch")).all(),
            )

    before = snapshot()
    barrier_key = uuid4().int % (2**62) + 1
    with engine.begin() as connection:
        connection.execute(text(f"""
            CREATE SEQUENCE qa_owner_commit_entered;
            CREATE SEQUENCE qa_owner_commit_until;
            CREATE SEQUENCE qa_owner_commit_pid;
            CREATE SEQUENCE qa_owner_commit_valid;
            CREATE FUNCTION qa_owner_commit_wait() RETURNS trigger LANGUAGE plpgsql AS $$
            BEGIN
              PERFORM nextval('qa_owner_commit_entered');
              PERFORM setval('qa_owner_commit_until',
                  floor(extract(epoch FROM NEW.valid_until)*1000000)::bigint,true);
              PERFORM setval('qa_owner_commit_pid',pg_backend_pid()::bigint,true);
              PERFORM setval('qa_owner_commit_valid',
                  CASE WHEN clock_timestamp()<NEW.valid_until THEN 1 ELSE 2 END,true);
              PERFORM pg_advisory_xact_lock({barrier_key}::bigint);
              RETURN NEW;
            END;$$;
            CREATE CONSTRAINT TRIGGER aaa_owner_commit_wait
              AFTER INSERT ON identity_owner_command_authorizations
              DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION qa_owner_commit_wait();
        """))
    states = []

    def record_error(context):
        original = context.original_exception
        states.append((getattr(original, "sqlstate", None),
                       getattr(getattr(original, "diag", None), "message_primary", None)))

    event.listen(engine, "handle_error", record_error)
    try:
        with engine.connect() as blocker:
            tx = blocker.begin()
            blocker_pid = blocker.execute(text("SELECT pg_backend_pid()")).scalar_one()
            blocker.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": barrier_key})
            with ThreadPoolExecutor(max_workers=1) as workers:
                # Distinct original caps expose accidental renewal to the later
                # wall expiry; the DB receipt must retain the monotonic 3s cap.
                permit = Authority(ISSUER, time.monotonic() + 3, time.time() - 1, time.time() + 30)
                future = workers.submit(execute, action, target, permit)
                try:
                    observed = False
                    wait_until = time.monotonic() + 4
                    while time.monotonic() < wait_until and not future.done():
                        with engine.connect() as observer:
                            observed = observer.execute(text(
                                "SELECT is_called AND :blocker=ANY(pg_blocking_pids(last_value::integer)) "
                                "FROM qa_owner_commit_pid"
                            ), {"blocker": blocker_pid}).scalar_one()
                        if observed:
                            break
                        time.sleep(0.01)
                    assert observed and not future.done(), "The exact owner PID must wait inside deferred COMMIT"
                    with engine.connect() as observer:
                        assert observer.execute(text(
                            "SELECT is_called FROM qa_owner_commit_entered"
                        )).scalar_one(), "The test must observe the real deferred trigger"
                        assert observer.execute(text(
                            "SELECT last_value FROM qa_owner_commit_valid"
                        )).scalar_one() == 1, "The actual NEW.valid_until must be valid at trigger entry"
                        assert observer.execute(text(
                            "SELECT is_called AND clock_timestamp()<"
                            "to_timestamp(last_value::double precision/1000000) FROM qa_owner_commit_until"
                        )).scalar_one(), "The actual fixed DB cap must remain future at the blocked barrier"
                    assert permit.current() and not future.done()
                    expired = False
                    expire_until = time.monotonic() + 5
                    while time.monotonic() < expire_until:
                        with engine.connect() as observer:
                            expired = observer.execute(text(
                                "SELECT clock_timestamp()>=to_timestamp(last_value::double precision/1000000) "
                                "FROM qa_owner_commit_until"
                            )).scalar_one()
                        if expired:
                            break
                        time.sleep(0.01)
                    assert expired, "The original fixed DB cap must expire without renewal"
                    assert not future.done(), "The transaction remains blocked after its original DB cap expires"
                finally:
                    tx.commit()
                with pytest.raises(OwnerError) as rejected:
                    future.result(5)
                assert rejected.value.status == 503
                assert rejected.value.code == "identity_deletion_storage_unavailable"
        assert ("42501", "identity_owner_command_authority_expired") in states, (
            "The exact database COMMIT clock diagnostic must reject the expired receipt"
        )
        assert snapshot() == before, "Journal, issuer binding and epoch must roll back together"
        with engine.connect() as connection:
            assert connection.execute(
                text("SELECT count(*) FROM identity_owner_command_authorizations")
            ).scalar_one() == 0
        # A fresh command remains possible: neither an expired transient receipt
        # nor the original freeze stores a deadline on the durable fence.
        execute(action, target, authority())
        with engine.connect() as connection:
            assert connection.execute(
                text("SELECT count(*) FROM identity_owner_command_authorizations")
            ).scalar_one() == 0
    finally:
        event.remove(engine, "handle_error", record_error)


@pytest.mark.parametrize("variant", ["uppercase", "compact", "braces"])
def test_subject_alias_request_counts_canonical_rows_and_installs_the_same_fence(owner, variant):
    engine, _, _, project = owner
    subject = "abcdefab-cdef-4abc-8def-" + uuid4().hex[:12]
    canonical = command(subject)
    payload = canonical.model_dump(mode="json")
    forms = {"uppercase": subject.upper(), "compact": subject.replace("-", ""), "braces": "{" + subject + "}"}
    alias = DeletionRequest.model_validate(payload | {
        "identity": payload["identity"] | {"subject": forms[variant]},
    })
    with engine.begin() as connection:
        context(connection, owner, subject)
        connection.execute(text(
            "INSERT INTO pm_namespace_ownership(ownership_ref,namespace_id,tracker_instance_ref,"
            "tracker_project_ref,authority_issuer,provisioner_subject) "
            "VALUES(:id,:project,'fixture',:tracker,:issuer,:subject)"
        ), {"id": str(uuid4()), "project": project, "tracker": str(uuid4()), "issuer": ISSUER, "subject": subject})

    # This count is the regression: old valid-but-noncanonical DTOs returned zero
    # against both real canonical reference rows, then installed a nonmatching fence.
    checked = execute("check", alias, authority())
    assert checked.reference_count == 2
    assert checked.request == canonical
    frozen = execute("freeze", alias, authority())
    assert frozen.reference_count == 2 and frozen.request == canonical
    assert execute("freeze", canonical, authority()) == frozen

    def saved_operation():
        with engine.connect() as connection:
            return dict(connection.execute(text(
                "SELECT request,issuer,subject,inventory_revision,state,fence,revision,reference_count "
                "FROM identity_deletion_operations WHERE operation_id=:operation"
            ), {"operation": str(canonical.operation_id)}).mappings().one())

    saved = saved_operation()
    assert saved["request"] == payload
    assert saved["issuer"] == ISSUER and saved["subject"] == subject
    assert saved["inventory_revision"] == str(canonical.inventory_revision)
    assert saved["state"] == "frozen" and saved["fence"] == str(frozen.fence)
    assert saved["revision"] == frozen.revision and saved["reference_count"] == 2
    with pytest.raises(OwnerError) as changed:
        execute("freeze", alias.model_copy(update={"inventory_revision": uuid4()}), authority())
    assert changed.value.status == 409 and changed.value.code == "identity_deletion_operation_conflict"
    assert saved_operation() == saved

    with engine.begin() as connection:
        with pytest.raises(DBAPIError) as rejected:
            context(connection, owner, subject)
        assert rejected.value.orig.sqlstate == "23514"
        assert rejected.value.orig.diag.message_primary == "identity_reference_frozen"
    assert saved_operation() == saved
    with engine.connect() as connection:
        assert connection.execute(text(
            "SELECT created_by_subject FROM resource_execution_contexts WHERE created_by_subject=:subject"
        ), {"subject": subject}).scalars().all() == [subject]
        assert connection.execute(text(
            "SELECT authority_issuer,provisioner_subject FROM pm_namespace_ownership "
            "WHERE authority_issuer=:issuer AND provisioner_subject=:subject"
        ), {"issuer": ISSUER, "subject": subject}).all() == [(ISSUER, subject)]

    assert execute("release", alias, authority()) == execute("release", canonical, authority())
    with engine.begin() as connection:
        context(connection, owner, subject)
    with pytest.raises(OwnerError) as late:
        execute("freeze", alias, authority())
    assert late.value.status == 409 and late.value.code == "identity_deletion_operation_conflict"
    released = saved_operation()
    assert released["request"] == payload and released["subject"] == subject
    assert released["state"] == "released" and released["fence"] is None
    assert released["revision"] == saved["revision"] and released["reference_count"] == 2
