"""Real editor HTML/publication APIs with controlled current human Auth."""

import json
from copy import deepcopy

from project_workflow.infrastructure.db.background_professions import ensure_background_professions
from project_workflow.infrastructure.db.uow import SAUnitOfWork
from tests.test_catalog_publication import verified_catalog_administrator as verified_catalog_administrator
from tests.test_configured_cli import configured as configured
from tests.test_ui_shell_template import Elements


def test_background_editor_saves_and_publishes_without_mutating_saved_phases(configured):
    client, _ = configured
    with SAUnitOfWork() as uow:
        namespace = ensure_background_professions(uow)["BUG_SEARCHER"]
        workflow = uow.workflows.get_by_id(uow.projects.get_by_id(namespace).workflow_id)
        workflow_id = workflow.id
        original_mode = uow.workflows.list_modes(workflow_id)[0]
        original_phase_ids = [phase.id for phase in uow.phases.list(workflow_id, mode_id=original_mode.id)]
    url = f"/workflows?profession_id={namespace}&workflow_id={workflow_id}"
    page = client.get(url)
    assert page.status_code == 200, page.text
    elements = Elements(page.text).elements
    fields = [attrs for tag, attrs in elements if tag == "textarea" and "data-catalog-path" in attrs]
    assert fields and all(isinstance(json.loads(attrs["data-catalog-path"]), list) for attrs in fields)
    assert 'data-catalog-action="save"' in page.text and 'data-catalog-action="publish"' in page.text
    assert 'class="workflow-card-actions phase-card-actions"' not in page.text
    root = f"/api/workflows/{workflow_id}/catalog"
    active = client.get(root).json()["revision"]
    modes = deepcopy(active["modes"])
    text = 'Human instruction </textarea><script>window.untrusted=true</script>'
    modes[0]["phases"][0]["instructions"][0]["description"] = text
    command = {"expected_version": active["catalog_version"], "expected_sha256": active["content_sha256"],
               "modes": modes}
    saved = client.post(root + "/drafts", json=command)
    assert saved.status_code == 200, saved.text
    draft = saved.json()["revision"]
    assert client.get(root).json()["revision"] == active
    assert client.post(root + "/drafts", json=command).json()["revision"] == draft
    reloaded = client.get(url)
    assert reloaded.status_code == 200
    assert text not in reloaded.text and '&lt;script&gt;window.untrusted=true&lt;/script&gt;' in reloaded.text
    publication = {"expected_version": active["catalog_version"], "expected_sha256": active["content_sha256"],
                   "draft_sha256": draft["content_sha256"], "operation_key": "background-ui-publication"}
    published = client.post(root + f"/drafts/{draft['catalog_version']}/publication", json=publication)
    assert published.status_code == 200, published.text
    assert client.get(root + "/publications/operations/background-ui-publication").json() == published.json()
    after = client.get(url)
    assert after.status_code == 200 and 'data-testid="workflow-mode-navigation"' not in after.text
    phase = client.get(f"/phase/{original_phase_ids[0]}?profession_id={namespace}")
    assert phase.status_code == 200
    assert '"canEditPhase": false' in phase.text
    assert 'Редактировать инструкции следующего запуска' in phase.text
    links = [attrs['href'] for tag, attrs in Elements(phase.text).elements
             if tag == 'a' and attrs.get('href', '').startswith('/phases?')]
    assert links and all('mode_id=' not in link for link in links)
    assert client.put(f"/api/phases/{original_phase_ids[0]}", json={"name": "raw mutation"}).status_code == 409
    with SAUnitOfWork() as uow:
        assert [phase.id for phase in uow.phases.list(workflow_id, mode_id=original_mode.id)] == original_phase_ids
        assert uow.phase_instructions.list(original_phase_ids[0])[0]["description"] != text
