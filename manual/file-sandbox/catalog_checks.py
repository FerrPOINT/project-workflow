"""Explicit unit checks of catalog preparation, never live CLI/advisor proof."""
import hashlib
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from register_catalog import register
from scenario import catalog
from sqlalchemy import create_engine, func, select

from project_workflow.infrastructure.db import models as m
from project_workflow.infrastructure.db.single_task_catalog import ensure_single_task_catalog, observe_installation
from project_workflow.infrastructure.db.uow import SAUnitOfWork


class CatalogChecks(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite://")
        m.Base.metadata.create_all(self.engine)
        with SAUnitOfWork(self.engine) as uow:
            self.installed = ensure_single_task_catalog(uow)
            uow.commit()
        self.content = json.dumps(catalog()).encode()
        self.digest = hashlib.sha256(self.content).hexdigest()

    def tearDown(self):
        self.engine.dispose()

    def test_only_catalog_is_created_and_managed_professions_are_preserved(self):
        with SAUnitOfWork(self.engine) as uow:
            result = register(uow, self.content, self.digest)
            uow.commit()
            self.assertEqual(observe_installation(uow), self.installed)
            self.assertEqual(len(result["bindings"]), 7)
            self.assertEqual(sum(len(row["modes"]) for row in result["bindings"]), 8)
            for binding in result["bindings"]:
                self.assertEqual(len(uow.workflows.list_by_profession(binding["namespace_id"])), 2)
            for table in (m.Task, m.TaskRuntimeAssignment, m.TaskStepHistoryEntry):
                self.assertEqual(uow.session.scalar(select(func.count()).select_from(table)), 0)
        with SAUnitOfWork(self.engine) as uow:
            self.assertEqual(register(uow, self.content, self.digest), result)
            self.assertEqual(len(uow.workflows.list()), 14)
        changed = catalog()
        changed["workflows"][0]["modes"][0]["phases"][0]["checks"].append("Changed criterion")
        content = json.dumps(changed).encode()
        with SAUnitOfWork(self.engine) as uow, self.assertRaises(ValueError):
            register(uow, content, hashlib.sha256(content).hexdigest())

    def test_wrong_digest_and_late_invalid_mode_leave_no_custom_catalog(self):
        invalid = catalog()
        invalid["workflows"][-1]["modes"][0]["execution_scopes"] = ["invalid"]
        changed = json.dumps(invalid).encode()
        for content, digest in ((self.content, "0" * 64), (changed, hashlib.sha256(changed).hexdigest())):
            with SAUnitOfWork(self.engine) as uow, self.assertRaises(ValueError):
                register(uow, content, digest)
            with SAUnitOfWork(self.engine) as uow:
                self.assertEqual(len(uow.workflows.list()), 7)
                self.assertEqual(observe_installation(uow), self.installed)


if __name__ == "__main__":
    unittest.main()
