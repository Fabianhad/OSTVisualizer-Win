import unittest
from PySide6 import QtWidgets
from ost_visualizer.application.services.import_service import ImportService
from ost_visualizer.domain.entities.hierarchy_data import HierarchyFileEntry
from ost_visualizer.infrastructure.persistence.repositories.file_project_repository import (
    FileProjectRepository,
    _LoadedFileCache,
)
from ost_visualizer.presentation.handlers import import_handler as import_handler_module
from ost_visualizer.presentation.handlers.import_handler import ImportHandler


class FakeImporter:
    def __init__(self):
        self.calls = []

    def import_ost(self, source_path, target_path, project_uid=None):
        self.calls.append(("ost", source_path, target_path, project_uid))
        return True

    def import_osp(self, source_path, target_path, project_uid=None):
        self.calls.append(("osp", source_path, target_path, project_uid))
        return True


class FakeEventBus:
    def __init__(self):
        self.events = []

    def publish(self, event_type, **kwargs):
        self.events.append((event_type, kwargs))


class FakeImportService:
    def __init__(self):
        self.import_calls = []
        self.reloads = []
        self.next_result = True

    def import_ost(self, filename, target_db, target_project_uid, refresh=True):
        self.import_calls.append((filename, target_db, target_project_uid, refresh))
        return self.next_result

    def reload_and_notify(self, target_db):
        self.reloads.append(target_db)


class FakeProjectData:
    def get_current_file_path(self):
        return "target.mdb"


class FakeUiState:
    selected_project_uid = None
    selected_file_path = None

    def get_selected_bid_ref(self):
        return None


class FakeProgressDialog:
    error = None
    result_code = QtWidgets.QDialog.DialogCode.Accepted

    def __init__(self, _filename, task_fn, parent=None):
        self.result = task_fn()
        self.cleanup_calls = 0
        self.delete_later_calls = 0

    def exec(self):
        return self.result_code

    def cleanup(self):
        self.cleanup_calls += 1

    def deleteLater(self):
        self.delete_later_calls += 1


class ImportRefreshFlowTests(unittest.TestCase):
    def test_import_service_can_import_without_refreshing_or_publishing(self):
        importer = FakeImporter()
        event_bus = FakeEventBus()
        reloads = []
        service = ImportService(
            ost_importer=importer,
            osp_importer=importer,
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

    def test_loaded_databases_have_path_tiebreaker_when_file_times_match(self):
        repository = FileProjectRepository.__new__(FileProjectRepository)

        class FakeHierarchy:
            def set(self, data):
                self.data = data

        repository._current_hierarchy = FakeHierarchy()
        repository._loaded_files = {
            "z.mdb": _LoadedFileCache(
                file_path="z.mdb",
                created_at=1.0,
                parsed_hierarchy=HierarchyFileEntry(file_path="z.mdb"),
            ),
            "a.mdb": _LoadedFileCache(
                file_path="a.mdb",
                created_at=1.0,
                parsed_hierarchy=HierarchyFileEntry(file_path="a.mdb"),
            ),
        }
        FileProjectRepository._rebuild_merged_hierarchy(repository)
        self.assertEqual(
            [
                entry.file_path
                for entry in repository._current_hierarchy.data.loaded_files
            ],
            ["a.mdb", "z.mdb"],
        )

    def test_import_handler_runs_import_without_refresh_then_refreshes_on_ui_completion(
        self,
    ):
        service = FakeImportService()
        handler = ImportHandler(
            window=None,
            project_data_service=FakeProjectData(),
            import_service=service,
            ui_state_manager=FakeUiState(),
        )
        original_dialog = import_handler_module.ProgressDialog
        original_get_open = import_handler_module.QtWidgets.QFileDialog.getOpenFileName
        original_show_info = import_handler_module.show_info
        try:
            import_handler_module.ProgressDialog = FakeProgressDialog
            import_handler_module.QtWidgets.QFileDialog.getOpenFileName = (
                lambda *_args, **_kwargs: ("source.ost", "")
            )
            import_handler_module.show_info = lambda *_args, **_kwargs: None
            handler.import_ost()
        finally:
            import_handler_module.ProgressDialog = original_dialog
            import_handler_module.QtWidgets.QFileDialog.getOpenFileName = (
                original_get_open
            )
            import_handler_module.show_info = original_show_info
        self.assertEqual(
            service.import_calls,
            [("source.ost", "target.mdb", None, False)],
        )
        self.assertEqual(service.reloads, ["target.mdb"])

    def test_import_handler_does_not_refresh_after_rejected_import(self):
        service = FakeImportService()
        handler = ImportHandler(
            window=None,
            project_data_service=FakeProjectData(),
            import_service=service,
            ui_state_manager=FakeUiState(),
        )
        original_dialog = import_handler_module.ProgressDialog
        original_get_open = import_handler_module.QtWidgets.QFileDialog.getOpenFileName
        original_show_critical = import_handler_module.show_critical
        try:
            FakeProgressDialog.result_code = QtWidgets.QDialog.DialogCode.Rejected
            import_handler_module.ProgressDialog = FakeProgressDialog
            import_handler_module.QtWidgets.QFileDialog.getOpenFileName = (
                lambda *_args, **_kwargs: ("source.ost", "")
            )
            import_handler_module.show_critical = lambda *_args, **_kwargs: None
            handler.import_ost()
        finally:
            FakeProgressDialog.result_code = QtWidgets.QDialog.DialogCode.Accepted
            import_handler_module.ProgressDialog = original_dialog
            import_handler_module.QtWidgets.QFileDialog.getOpenFileName = (
                original_get_open
            )
            import_handler_module.show_critical = original_show_critical
        self.assertEqual(
            service.import_calls,
            [("source.ost", "target.mdb", None, False)],
        )
        self.assertEqual(service.reloads, [])


if __name__ == "__main__":
    unittest.main()
