"""A profession owns execution configuration; phases have no agent assignments."""

import pytest
from sqlalchemy import create_engine, inspect, text

from project_workflow.infrastructure.db import schema
from project_workflow.infrastructure.db.session import run_alembic_command, schema_is_ready
from project_workflow.infrastructure.db.uow import SAUnitOfWork
from tests.test_ui_api import client as client


def create_profession(client, key, **settings):
    response = client.post("/api/namespaces", json={
        "name": f"Profession {key}", "cli_command": f"workflow-{key}", **settings,
    })
    assert response.status_code == 200, response.text
    return response.json()["namespace"]


def test_settings_round_trip_and_agent_registration_removed(client):
    profession = create_profession(client, "designer", role_key="designer", launch_profile="java-designer",
                                   execution_description="Design execution")
    assert profession["role_key"] == "designer"
    assert profession["launch_profile"] == "java-designer"
    assert profession["execution_description"] == "Design execution"
    updated = client.put(f'/api/namespaces/{profession["id"]}', json={
        "launch_profile": "other-runtime-profile", "execution_description": "Updated configuration",
    })
    assert updated.status_code == 200, updated.text
    assert updated.json()["namespace"]["launch_profile"] == "other-runtime-profile"
    cleared = client.put(f'/api/namespaces/{profession["id"]}', json={"launch_profile": None})
    assert cleared.status_code == 200
    assert cleared.json()["namespace"]["launch_profile"] is None
    for method, path in (("get", "/agents"), ("get", "/api/agents"), ("post", "/api/agents"),
                         ("put", "/api/agents/1"), ("delete", "/api/agents/1")):
        assert getattr(client, method)(path).status_code == 404
    html = client.get(f'/namespaces?namespace_id={profession["id"]}').text
    assert 'id="namespaceLaunchProfile"' in html
    assert 'id="namespaceExecutionDescription"' in html
    assert 'href="/agents"' not in html


@pytest.mark.parametrize("invalid", ["", "Bad Profile", "profile/key", "a" * 252, 123])
def test_invalid_profile_does_not_change_profession(client, invalid):
    profession = create_profession(client, "validation", role_key="developer", launch_profile="valid-profile")
    response = client.put(f'/api/namespaces/{profession["id"]}', json={"launch_profile": invalid})
    assert response.status_code == 422
    current = client.get(f'/api/namespaces/{profession["id"]}').json()["namespace"]
    assert current["launch_profile"] == "valid-profile"


def test_execution_comes_from_selected_profession_and_profiles_can_be_shared(client):
    first = create_profession(client, "alpha", role_key="alpha", launch_profile="shared-profile")
    second = create_profession(client, "beta", role_key="beta", launch_profile="shared-profile",
                               workflow_id=first["workflow_id"])
    from project_workflow.interfaces.ui import _app_state

    with _app_state.get_db() as uow:
        a = schema.load_phases_from_db(uow, first["workflow_id"], profession_settings=first)
        b = schema.load_phases_from_db(uow, first["workflow_id"], profession_settings=second)
        assert {phase.delegate.agent for phase in a} == {"alpha"}
        assert {phase.delegate.agent for phase in b} == {"beta"}
        assert {phase.delegate.hermes_profile for phase in a + b} == {"shared-profile"}
        tables = inspect(uow.session.get_bind()).get_table_names()
        assert "agents" not in tables
        assert "execution_role_snapshots" not in tables
        assert "agent_id" not in {column["name"] for column in inspect(uow.session.get_bind()).get_columns("phases")}
        phase_id = a[0].id
    phase_html = client.get(f'/phase/{phase_id}?namespace_id={first["id"]}').text
    assert 'id="agentSelect"' not in phase_html
    assert client.put(f'/api/phases/{phase_id}', json={"agent_id": 1}).status_code == 422


@pytest.mark.parametrize("ownership", ["unique", "ambiguous", "unmapped"])
def test_migration_transfers_settings_and_preserves_phase_identity(tmp_path, ownership):
    engine = create_engine(f'sqlite:///{tmp_path / "transfer.db"}')
    try:
        run_alembic_command("upgrade", engine, "0012_profession_themes")
        with engine.begin() as connection:
            connection.execute(text("INSERT INTO workflows (id,key,name,is_default) VALUES (37,'sample','Sample',0)"))
            connection.execute(text("INSERT INTO workflow_modes (id,workflow_id,key,name,mode_order) "
                                    "VALUES (57,37,'default','Default',1)"))
            connection.execute(text("INSERT INTO agents (id,name,description,hermes_profile) "
                                    "VALUES (93,'builder','Saved note','external-builder')"))
            connection.execute(text("INSERT INTO phases (id,workflow_id,mode_id,code,name,phase_order,agent_id) "
                                    "VALUES (117,37,57,'start','Start',1,93)"))
            connection.execute(text("INSERT INTO projects (id,workflow_id,code,name,cli_command) "
                                    "VALUES (191,37,'SAMPLE','Sample profession','workflow-sample')"))
            connection.execute(text("INSERT INTO profession_workflows (profession_id,workflow_id) VALUES (191,37)"))
            if ownership != "unique":
                connection.execute(text("INSERT INTO agents (id,name,description,hermes_profile) "
                                        "VALUES (94,'other','Another setting','other-builder')"))
            if ownership == "ambiguous":
                connection.execute(text("INSERT INTO phases (id,workflow_id,mode_id,code,name,phase_order,agent_id) "
                                        "VALUES (118,37,57,'next','Next',2,94)"))
        if ownership != "unique":
            with pytest.raises(RuntimeError, match="need a profession owner"):
                run_alembic_command("upgrade", engine)
            with engine.connect() as connection:
                assert connection.execute(text("SELECT COUNT(*) FROM agents")).scalar_one() == 2
                assert connection.execute(text("SELECT agent_id FROM phases WHERE id=117")).scalar_one() == 93
                assert connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == (
                    "0012_profession_themes"
                )
            assert "role_key" not in {column["name"] for column in inspect(engine).get_columns("projects")}
            return
        run_alembic_command("upgrade", engine)
        assert schema_is_ready(engine)
        with SAUnitOfWork(engine) as uow:
            profession = uow.projects.get_by_id(191)
            assert profession.role_key == "builder"
            assert profession.launch_profile == "external-builder"
            assert profession.execution_description == "Saved note"
            phase = uow.phases.get_by_id(117)
            assert phase.code == "start" and phase.workflow_id == 37
        assert "agents" not in inspect(engine).get_table_names()
    finally:
        engine.dispose()


@pytest.mark.parametrize("field,value", [("role_key", "other-role"), ("launch_profile", "other-profile")])
def test_active_tasks_freeze_launch_settings_but_allow_notes(client, field, value):
    profession = create_profession(client, "active", role_key="builder", launch_profile="builder-profile")
    from project_workflow.interfaces.ui import _app_state

    with _app_state.get_db() as uow:
        phase = list(uow.phases.list(profession["workflow_id"]))[0]
        task_id = uow.tasks.create({
            "project_id": profession["id"], "workflow_id": profession["workflow_id"],
            "task_key": "BUILD-42", "title": "Active execution", "status": "active", "current_phase_id": phase.id,
        })
        uow.commit()
    path = f'/api/namespaces/{profession["id"]}'
    assert client.put(path, json={field: value}).status_code == 409
    assert client.get(path).json()["namespace"][field] == profession[field]
    assert client.put(path, json={field: profession[field], "execution_description": "New note"}).status_code == 200
    with _app_state.get_db() as uow:
        uow.tasks.update(task_id, {"status": "done"})
        uow.commit()
    assert client.put(path, json={field: value}).status_code == 200
    assert client.get(path).json()["namespace"][field] == value
