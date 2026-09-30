import unittest
from ost_visualizer.application.services.import_service import ImportService
from tests.helpers.import_workflow import (
    FakeEventBus as _import_workflow_FakeEventBus,
    FakeImporter as _import_workflow_FakeImporter,
)


class ImportServiceRefreshTests(unittest.TestCase):
    def test_import_service_can_import_without_refreshing_or_publishing(self):
        importer = _import_workflow_FakeImporter()
        event_bus = _import_workflow_FakeEventBus()
        reloads = []
        service = ImportService(
            ost_importer=importer,
            osp_importer=importer,
            project_write_service=type(
                "ProjectWriteService",
                (),
                {"uses_sql_collaboration_mutations": lambda _self, _path: False},
            )(),
            reload_database=lambda path: reloads.append(path) or True,
            event_bus=event_bus,
        )
        self.assertTrue(
            service.import_ost("source.ost", "target.mdb", "project-1", refresh=False)
        )
        self.assertEqual(
            importer.calls,
            [("ost", "source.ost", "target.mdb", "project-1")],
        )
        self.assertEqual(reloads, [])
        self.assertEqual(event_bus.events, [])
