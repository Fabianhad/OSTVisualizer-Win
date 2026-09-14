import logging
import os
import unittest
import uuid
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6 import QtWidgets

from ost_visualizer.application.dtos.collaboration_dtos import (
    MutationOutcomeStatus,
    EditLeaseHandle,
    EditLeaseResult,
    QueuedMutationResult,
)
from ost_visualizer.application.services.project_write_service import (
    ProjectWriteService,
)
from ost_visualizer.application.use_cases.project.save_page_image_adjustments_use_case import (
    SavePageImageAdjustmentsUseCase,
)
from ost_visualizer.domain.aggregates.ost_aggregate import OstAggregate
from ost_visualizer.domain.entities.bid import Bid
from ost_visualizer.domain.entities.identity_refs import BidRef
from ost_visualizer.domain.entities.page import Page
from ost_visualizer.domain.services.project_data_service import ProjectDataService
from ost_visualizer.infrastructure.events.event_bus import EventBus
from ost_visualizer.presentation.coordinators.ui_event_coordinator import (
    UIEventCoordinator,
)


class AdjustImagesRepeatedApplyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def setUp(self):
        self.bid_ref = BidRef("test.mdb", "7")
        self.original = Page(uid="42", name="Page 42", scale_factor2=48.0)
        self.model = OstAggregate(Mock())
        self.model.current_bid_ref = self.bid_ref
        self.model.current_bid = Bid("7", "Test bid")
        self.model.set_pages({"42": self.original})
        self.data = ProjectDataService(self.model)
        self.persisted = {"42": self.original}
        self.write_calls = []
        self.reloads = []
        self.events = EventBus()
        self.service = object.__new__(ProjectWriteService)
        self.service._project_data = self.data
        self.service._bid_write_guard = Mock()
        self.service._bid_write_guard.blocks_active_locked_bid_write.return_value = (
            False
        )
        self.service.uses_sql_collaboration_mutations = Mock(return_value=False)
        self.service.logger = logging.getLogger(__name__)
        self.service._event_bus = self.events
        self.service._reload_database = self._reload
        self.service._execute_database_mutation = (
            lambda _db, _resources, operation, **_kw: SimpleNamespace(
                outcome_status=MutationOutcomeStatus.COMMITTED, value=operation(Mock())
            )
        )
        self.writer = Mock()
        self.writer.save_page_image_adjustments.side_effect = self._write
        self.service._save_page_image_adjustments = SavePageImageAdjustmentsUseCase(
            self.writer
        )
        self.coordinator = object.__new__(UIEventCoordinator)
        self.coordinator.main_window = None
        self.coordinator.event_bus = self.events
        self.coordinator._icon_provider = None
        self.coordinator.project_data = self.data
        self.coordinator.ui_state_manager = SimpleNamespace(
            active_page_uid="42",
            get_selected_bid_ref=lambda: self.model.current_bid_ref,
        )
        self.coordinator.ui_access_manager = Mock()
        self.coordinator.ui_access_manager.is_allowed.return_value = True
        self.coordinator.takeoff_sidebar = SimpleNamespace(
            get_page_order=lambda: list(self.persisted)
        )
        self.coordinator._deferred_persistence = Mock()
        self.coordinator._deferred_persistence.flush_for_file.return_value = True
        self.coordinator._project_write_service = self.service

    def _write(self, database, page_uids, rotation, flip_x, flip_y, invert, bitonal):
        self.write_calls.append(
            (database, tuple(page_uids), rotation, flip_x, flip_y, invert, bitonal)
        )
        for uid in page_uids:
            self.persisted[uid] = replace(
                self.persisted[uid],
                rotation=rotation,
                flip_x=flip_x,
                flip_y=flip_y,
                invert=invert,
                bitonal=bitonal,
            )
        return True

    def _reload(self, database):
        self.assertEqual(database, self.bid_ref.file_path)
        self.model.current_bid = Bid("7", "Test bid")
        self.model.set_pages(
            {uid: replace(page) for uid, page in self.persisted.items()}
        )
        self.reloads.append(self.model.get_page("42"))
        return True

    def _open(self, interact):
        def run(dialog, _events):
            dialog.show()
            try:
                interact(dialog)
            finally:
                dialog.reject()
            return dialog.result()

        with patch(
            "ost_visualizer.presentation.coordinators.ui_event_coordinator.exec_with_ost_blocking",
            side_effect=run,
        ):
            self.coordinator.open_adjust_images_dialog()

    def test_two_applies_use_reloaded_authoritative_page_in_same_dialog(self):
        pages_submitted = []
        save = self.coordinator._save_image_adjustments

        def observe(bid_ref, page_uid, page, settings):
            pages_submitted.append(page)
            return save(bid_ref, page_uid, page, settings)

        self.coordinator._save_image_adjustments = observe

        def interact(dialog):
            dialog._flip_x_check.setChecked(True)
            dialog._on_apply()
            replacement = self.model.get_page("42")
            self.assertIsNot(replacement, self.original)
            self.assertTrue(replacement.flip_x)
            self.assertTrue(dialog.isVisible())
            self.assertFalse(dialog._dirty)
            self.assertTrue(dialog._flip_x_check.isChecked())
            self.assertFalse(
                self.coordinator._page_dialog_context_is_current(
                    self.bid_ref, "42", self.original
                )
            )
            dialog._rotation_buttons[90].setChecked(True)
            dialog._on_apply()
            self.assertEqual(len(self.write_calls), 2)
            self.assertEqual(pages_submitted, [self.original, replacement])
            self.assertIs(pages_submitted[1], replacement)
            self.assertIsNot(self.model.get_page("42"), replacement)
            self.assertEqual(self.model.get_page("42").rotation, 90)
            self.assertEqual(self.model.get_page("42").scale_factor2, 48.0)
            self.assertTrue(dialog.isVisible())
            self.assertFalse(dialog._dirty)

        with patch(
            "ost_visualizer.presentation.dialogs.adjust_images_dialog.show_warning"
        ) as warning:
            self._open(interact)
        warning.assert_not_called()

    def test_unchanged_apply_and_cancel_do_not_consume_a_save(self):
        def interact(dialog):
            dialog._on_apply()
            dialog._flip_x_check.setChecked(True)
            dialog._flip_x_check.setChecked(False)
            dialog._on_apply()
            self.assertEqual(self.write_calls, [])
            dialog._invert_check.setChecked(True)
            dialog._on_apply()
            dialog._on_apply()
            self.assertEqual(len(self.write_calls), 1)
            dialog._bitonal_check.setChecked(True)
            dialog.reject()
            self.assertEqual(len(self.write_calls), 1)
            self.assertTrue(self.model.get_page("42").invert)
            self.assertFalse(self.model.get_page("42").bitonal)

        self._open(interact)
        self._open(lambda dialog: self.assertTrue(dialog._invert_check.isChecked()))

    def test_failed_write_logs_context_and_keeps_same_dialog_retryable(self):
        def interact(dialog):
            self.writer.save_page_image_adjustments.side_effect = None
            self.writer.save_page_image_adjustments.return_value = False
            dialog._flip_x_check.setChecked(True)
            with self.assertLogs(
                "ost_visualizer.presentation.coordinators.ui_event_coordinator",
                level="WARNING",
            ) as logs, patch(
                "ost_visualizer.presentation.dialogs.adjust_images_dialog.show_warning"
            ) as warning:
                dialog._on_apply()
            self.assertIn("database=test.mdb, bid=7, page=42", logs.output[0])
            self.assertIn("context_current=True", logs.output[0])
            warning.assert_called_once_with(
                dialog, "Save Failed", "Failed to save image adjustments."
            )
            self.assertIs(self.model.get_page("42"), self.original)
            self.assertTrue(dialog._dirty)
            self.assertTrue(dialog._apply_btn.isEnabled())
            self.writer.save_page_image_adjustments.side_effect = self._write
            dialog._on_apply()
            dialog._bitonal_check.setChecked(True)
            dialog._on_apply()
            self.assertEqual(len(self.write_calls), 2)
            self.assertTrue(self.model.get_page("42").bitonal)
            self.assertFalse(dialog._dirty)

        self._open(interact)

    def test_exception_is_logged_with_traceback_and_retry_succeeds(self):
        def interact(dialog):
            self.writer.save_page_image_adjustments.side_effect = RuntimeError(
                "write failed"
            )
            dialog._invert_check.setChecked(True)
            with self.assertLogs(
                "ost_visualizer.presentation.coordinators.ui_event_coordinator",
                level="ERROR",
            ) as logs, patch(
                "ost_visualizer.presentation.dialogs.adjust_images_dialog.show_warning"
            ) as warning:
                dialog._on_apply()
            self.assertIsNotNone(logs.records[0].exc_info)
            self.assertIn("database=test.mdb, bid=7, page=42", logs.output[0])
            self.assertIn("RuntimeError: write failed", logs.output[0])
            warning.assert_called_once()
            self.assertTrue(dialog._dirty)
            self.writer.save_page_image_adjustments.side_effect = self._write
            dialog._on_apply()
            self.assertTrue(self.model.get_page("42").invert)

        self._open(interact)

    def test_unrelated_replacement_deletion_navigation_and_permission_loss_are_rejected(
        self,
    ):
        for change in ("replace", "delete", "page", "bid", "permission"):
            with self.subTest(change=change):
                self.setUp()

                def interact(dialog):
                    dialog._flip_x_check.setChecked(True)
                    dialog._on_apply()
                    saved = self.model.get_page("42")
                    if change == "replace":
                        self.model.set_pages({"42": replace(saved, scale_factor2=96.0)})
                    elif change == "delete":
                        self.model.set_pages({})
                    elif change == "page":
                        self.coordinator.ui_state_manager.active_page_uid = "43"
                    elif change == "bid":
                        self.model.current_bid_ref = BidRef("other.mdb", "7")
                    else:
                        self.coordinator.ui_access_manager.is_allowed.return_value = (
                            False
                        )
                    dialog._invert_check.setChecked(True)
                    with self.assertLogs(
                        "ost_visualizer.presentation.coordinators.ui_event_coordinator",
                        level="WARNING",
                    ) as logs, patch(
                        "ost_visualizer.presentation.dialogs.adjust_images_dialog.show_warning"
                    ):
                        dialog._on_apply()
                    self.assertIn("context_current=False", logs.output[0])
                    self.assertEqual(len(self.write_calls), 1)
                    self.assertFalse(self.persisted["42"].invert)

                self._open(interact)

    def test_apply_to_all_pages_refreshes_owner_for_next_single_page_apply(self):
        second = Page(uid="43", name="Page 43", scale_factor2=96.0)
        self.persisted["43"] = second
        self.model.set_pages(dict(self.persisted))

        def interact(dialog):
            dialog._apply_all_check.setChecked(True)
            dialog._rotation_buttons[90].setChecked(True)
            dialog._on_apply()
            self.assertEqual(self.write_calls[0][1], ("42", "43"))
            dialog._apply_all_check.setChecked(False)
            dialog._invert_check.setChecked(True)
            dialog._on_apply()
            self.assertEqual(self.write_calls[1][1], ("42",))
            self.assertTrue(self.model.get_page("42").invert)
            self.assertFalse(self.model.get_page("43").invert)
            self.assertEqual(self.model.get_page("43").rotation, 90)
            self.assertEqual(self.model.get_page("43").scale_factor2, 96.0)

        self._open(interact)

    def test_sql_repeated_apply_uses_reacquired_lease_after_each_completion(self):
        self.model.current_bid_ref = BidRef("sql-database-id", "7")
        self.service.uses_sql_collaboration_mutations.return_value = True
        handles = []
        queued = []
        released = []

        def grant(database_id, resources, callback, **options):
            handle = EditLeaseHandle(
                database_id,
                f"draft-{len(handles) + 1}",
                3,
                options["operation_id"],
                options["owning_surface"],
                resources,
            )
            handles.append(handle)
            callback(EditLeaseResult(True, handle=handle))

        def queue(database_id, bid_uid, kind, updates, completed, *, edit_lease_handle):
            queued.append((edit_lease_handle, updates, completed))
            return len(queued)

        self.coordinator.request_collaboration_edit = grant
        self.coordinator.end_collaboration_edit = released.append
        self.service.queue_page_settings = queue

        def complete(index):
            self.model.set_pages(
                {
                    "42": replace(
                        self.model.get_page("42"), flip_x=True, invert=bool(index)
                    )
                }
            )
            queued[index][2](
                QueuedMutationResult(
                    database_id="sql-database-id",
                    runtime_generation=3,
                    operation_id=str(uuid.UUID(int=index + 1)),
                    outcome_status=MutationOutcomeStatus.COMMITTED,
                )
            )

        def interact(dialog):
            dialog._flip_x_check.setChecked(True)
            dialog._on_apply()
            self.assertIs(queued[0][0], handles[0])
            self.assertTrue(dialog._save_pending)
            complete(0)
            self.assertFalse(dialog._save_pending)
            dialog._invert_check.setChecked(True)
            dialog._on_apply()
            self.assertIs(queued[1][0], handles[1])
            self.assertIsNot(queued[1][0], queued[0][0])
            complete(1)
            self.assertFalse(dialog._dirty)
            self.assertTrue(dialog._ok_btn.isEnabled())

        self._open(interact)
        self.assertEqual(len(handles), 3)
        self.assertEqual(released, [handles[2]])
        self.assertEqual(self.write_calls, [])
