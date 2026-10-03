import os
import unittest
from contextlib import nullcontext
from types import SimpleNamespace
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from ost_visualizer.application.dtos.collaboration_dtos import (
    AuthoritativeMutationResult,
    DatabaseMutationResult,
    EditLeaseHandle,
    EditLeaseResult,
    MutationOutcomeStatus,
    QueuedMutationResult,
    ResourceRef,
)
from ost_visualizer.application.events.app_events import AppEvents
from ost_visualizer.application.services.project_write_service import (
    ProjectWriteService,
)
from ost_visualizer.domain.entities.cover_sheet import (
    CoverSheetData,
    CoverSheetFolder,
    CoverSheetPage,
    JobStatus,
)
from ost_visualizer.domain.entities.identity_refs import BidRef
from ost_visualizer.infrastructure.events.event_bus import EventBus
from ost_visualizer.presentation.dialogs.cover_sheet.dialog import CoverSheetDialog
from ost_visualizer.presentation.handlers.cover_sheet_handler import CoverSheetHandler
from PySide6 import QtCore, QtGui, QtWidgets
from tests.helpers.workspace_state import (
    make_workspace_state_model,
    with_workspace_state,
)
from tests.presentation.dialogs.cover_sheet.path_support import (
    CoverSheetDialog as _path_support_CoverSheetDialog,
    _FakeCoverSheetDialog as _path_support__FakeCoverSheetDialog,
    _FakeIconProvider as _path_support__FakeIconProvider,
    _app as _path_support__app,
    _cover_sheet_data as _path_support__cover_sheet_data,
    _first_page_update as _path_support__first_page_update,
    _path_editor as _path_support__path_editor,
)


class SaveProjectionCoverSheetPathTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _path_support__app()

    def tearDown(self):
        self.app.processEvents()

    def test_original_source_rejection_keeps_cover_sheet_draft_retryable_and_snapshot_unchanged(
        self,
    ):
        queued = []
        errors = []
        handler = CoverSheetHandler.__new__(CoverSheetHandler)
        handler.window = None
        handler._write_service = SimpleNamespace(
            queue_cover_sheet_save=lambda database_id, bid_uid, updates, callback: queued.append(
                (updates, callback)
            )
            or 1
        )
        handler._ui_event_coordinator = SimpleNamespace(
            present_queued_mutation_error=lambda database_id, title, result: errors.append(
                (title, result.message)
            )
        )
        original = _path_support__cover_sheet_data(
            image_path="original.tif", overlay_image_path="overlay.tif"
        )
        dialog = _path_support_CoverSheetDialog(
            _path_support__FakeIconProvider(),
            None,
            original,
            save_cover_sheet_async_fn=lambda updates, completed: handler._save_cover_sheet_async(
                BidRef("database", "7"), updates, completed
            ),
        )
        try:
            item = dialog.plan_tree.topLevelItem(0)
            for path in ("replacement.tif", ""):
                editor = _path_support__path_editor(dialog, item, 4)
                editor.begin_path_edit()
                editor.setText(path)
                editor.editingFinished.emit()
                dialog.accept()
                self.assertTrue(dialog._operation_pending)
                before = len(errors)
                queued[-1][1](
                    QueuedMutationResult(
                        database_id="database",
                        runtime_generation=1,
                        operation_id="00000000-0000-0000-0000-000000000001",
                        outcome_status=MutationOutcomeStatus.REJECTED,
                        message="Original source save rejected",
                    )
                )
                self.assertFalse(dialog._operation_pending)
                self.assertFalse(dialog._save_done)
                self.assertEqual(
                    _path_support__first_page_update(dialog)["image_path"], path
                )
                self.assertEqual(
                    original.pages_without_folder[0].image_path, "original.tif"
                )
                self.assertEqual(len(errors), before + 1)
                self.assertEqual(
                    errors[-1], ("Cover Sheet", "Original source save rejected")
                )
            dialog.accept()
            queued[-1][1](
                QueuedMutationResult(
                    database_id="database",
                    runtime_generation=1,
                    operation_id="00000000-0000-0000-0000-000000000001",
                    outcome_status=MutationOutcomeStatus.COMMITTED,
                )
            )
            self.assertEqual(dialog.result(), QtWidgets.QDialog.DialogCode.Accepted)
            self.assertEqual(len(errors), 2)
        finally:
            dialog.reject()
            dialog.deleteLater()

    def test_cover_sheet_close_publishes_one_refresh_for_bulk_delete(self):
        calls = []

        class WriteGuard:
            def blocks_active_locked_bid_write(self, *_args):
                return False

        class SaveCoverSheet:
            def execute(self, db_path, bid_uid, updates):
                calls.append(("save", db_path, bid_uid, updates))
                return True

        class EventBus:
            def publish(self, event_type, **payload):
                calls.append(("publish", event_type, payload))

        class ReadService:
            def get_cover_sheet_data(self, _file_path, _bid_uid):
                return _path_support__cover_sheet_data()

            def get_employee_uids_in_use(self, _file_path):
                return set()

            def get_pages_with_takeoffs(self, _file_path, _bid_uid):
                return set()

            def get_pages_with_delete_content(self, _file_path, _bid_uid):
                return set()

        class ProjectData:
            def is_current_bid_locked(self):
                return False

            def get_assigned_area_uids_with_stored_takeoff(self):
                return set()

        class UiState:
            def get_selected_bid_ref(self):
                return BidRef("bid.mdb", "7")

        class Access:
            def is_allowed(self, _feature):
                return True

            def has_license(self):
                return True

        class DeferredPersistence:
            def flush_for_file(self, file_path):
                calls.append(("flush", file_path))
                return True

        class Infrastructure:
            def get_pdf_page_sizes(self, _path):
                return []

        class FakeDialog(_path_support__FakeCoverSheetDialog):
            def get_updates(self):
                return {"deleted_page_uids": [str(index) for index in range(1, 226)]}

        event_bus = EventBus()
        write_service = ProjectWriteService.__new__(ProjectWriteService)
        write_service.uses_sql_collaboration_mutations = lambda _database_id: False
        write_service._bid_write_guard = WriteGuard()
        write_service._save_cover_sheet = SaveCoverSheet()
        write_service._reload_database = (
            lambda file_path: calls.append(("reload", file_path)) or True
        )
        write_service._event_bus = event_bus
        write_service.logger = mock.Mock()
        write_service._mutation_executor = SimpleNamespace(
            execute=lambda request, operation: DatabaseMutationResult(
                operation_id=request.operation_id,
                outcome_status=MutationOutcomeStatus.COMMITTED,
                value=operation(
                    SimpleNamespace(
                        record=lambda resource, change_operation, *, changed_fields=(), payload="": None
                    )
                ),
            )
        )
        write_service._session_registry = SimpleNamespace(
            get=lambda _database_id: "",
            lock_tokens=lambda _database_id, _resources: (),
        )
        write_service._concurrency_tokens = SimpleNamespace(
            mutation_scope=lambda _database_id: nullcontext(),
            ensure_resources_loaded=lambda _database_id, _resources: None,
            expected_versions=lambda _database_id, _resources: (),
            apply_result=lambda _database_id, _versions: None,
        )
        write_service._database_capability_service = SimpleNamespace(
            is_editable=lambda _locator, resource=None: True
        )
        handler = CoverSheetHandler(
            window=object(),
            icon_provider=_path_support__FakeIconProvider(),
            project_data_service=ProjectData(),
            project_read_service=ReadService(),
            project_write_service=write_service,
            infrastructure_provider=Infrastructure(),
            event_bus=event_bus,
            ui_state_manager=UiState(),
            ui_access_manager=Access(),
            deferred_persistence_manager=DeferredPersistence(),
            workspace_state_model=make_workspace_state_model(),
        )
        from ost_visualizer.presentation.handlers import cover_sheet_handler as module

        with mock.patch.object(
            module, "CoverSheetDialog", FakeDialog
        ), mock.patch.object(
            module,
            "exec_with_ost_blocking",
            return_value=QtWidgets.QDialog.DialogCode.Accepted,
        ):
            handler.open_cover_sheet()
        self.assertEqual([call[0] for call in calls].count("save"), 1)
        self.assertEqual([call[0] for call in calls].count("flush"), 1)
        self.assertEqual([call[0] for call in calls].count("reload"), 1)
        # Pending visual state is flushed before the write, the write receives the
        # full 225-page delete set for the selected bid, and the reload follows it.
        self.assertEqual(
            [call[0] for call in calls], ["flush", "save", "reload", "publish"]
        )
        self.assertEqual(calls[0], ("flush", "bid.mdb"))
        self.assertEqual(
            calls[1],
            (
                "save",
                "bid.mdb",
                "7",
                {"deleted_page_uids": [str(index) for index in range(1, 226)]},
            ),
        )
        self.assertEqual(calls[2], ("reload", "bid.mdb"))
        publish_calls = [call for call in calls if call[0] == "publish"]
        self.assertEqual(len(publish_calls), 1)
        self.assertIs(publish_calls[0][1], AppEvents.DATABASE_REFRESHED)
        self.assertEqual(
            publish_calls[0][2],
            {
                "file_path": "bid.mdb",
                "image_sources_unchanged": False,
                "mesh_scene_unchanged": False,
                "page_scale_uids": (),
            },
        )
        self.assertTrue(
            all(
                value is None
                for value in FakeDialog.instance.async_save_functions.values()
            )
        )
        self.assertTrue(FakeDialog.instance.deleted)
