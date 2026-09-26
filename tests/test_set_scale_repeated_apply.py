import logging
import os
import unittest
import uuid
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from ost_visualizer.application.dtos.collaboration_dtos import (
    EditLeaseHandle,
    EditLeaseResult,
    MutationOutcomeStatus,
    QueuedMutationResult,
)
from ost_visualizer.application.events.app_events import AppEvents
from ost_visualizer.application.services.project_write_service import (
    ProjectWriteService,
)
from ost_visualizer.application.use_cases.project.save_page_scale_use_case import (
    SavePageScaleUseCase,
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
from PySide6 import QtWidgets


class SetScaleRepeatedApplyTests(unittest.TestCase):
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
        self.writer.save_page_scale.side_effect = self._write
        self.service._save_page_scale = SavePageScaleUseCase(self.writer)
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

    def _write(self, database, page_uid, sf1, sf2):
        self.write_calls.append((database, page_uid, sf1, sf2))
        self.persisted[page_uid] = replace(
            self.persisted[page_uid], scale_factor1=sf1, scale_factor2=sf2
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
            self.coordinator.open_set_scale_dialog()

    @staticmethod
    def _change(dialog, scale):
        dialog._custom_radio.setChecked(True)
        dialog._custom_factor1_edit.setText("1")
        dialog._custom_factor2_edit.setText(str(scale))

    def test_two_applies_use_same_authoritative_page_without_reload(self):
        pages_submitted = []
        save = self.coordinator._save_scale_settings

        def observe(bid_ref, page_uid, page, settings):
            pages_submitted.append(page)
            return save(bid_ref, page_uid, page, settings)

        self.coordinator._save_scale_settings = observe

        def interact(dialog):
            self._change(dialog, 96)
            dialog._on_apply()
            replacement = self.model.get_page("42")
            self.assertEqual(len(self.write_calls), 1)
            self.assertIs(replacement, self.original)
            self.assertEqual(replacement.scale_factor2, 96)
            self.assertFalse(dialog._dirty)
            self.assertTrue(dialog.isVisible())
            self.assertTrue(
                self.coordinator._page_dialog_context_is_current(
                    self.bid_ref, "42", self.original
                )
            )
            self._change(dialog, 192)
            dialog._on_apply()
            self.assertEqual(len(self.write_calls), 2)
            self.assertIs(pages_submitted[0], self.original)
            self.assertIs(pages_submitted[1], replacement)
            self.assertIs(self.model.get_page("42"), replacement)
            self.assertEqual(self.model.get_page("42").scale_factor2, 192)
            self.assertEqual(dialog._custom_factor2_edit.text(), "192")
            self.assertFalse(dialog._dirty)
            self.assertTrue(dialog.isVisible())

        with patch(
            "ost_visualizer.presentation.dialogs.set_scale_dialog.show_warning"
        ) as warning:
            self._open(interact)
        warning.assert_not_called()

    def test_scale_save_projects_only_affected_page_without_database_reload(self):
        changes = []
        self.events.subscribe(
            AppEvents.PAGE_METADATA_CHANGED,
            lambda **event: changes.append(event),
        )
        self.assertTrue(self.service.save_page_scale("test.mdb", "42", 1.0, 96.0))
        self.assertEqual(self.reloads, [])
        self.assertEqual(len(changes), 1)
        self.assertEqual(changes[0]["page_uids"], ("42",))

    def test_scale_save_does_not_project_into_bid_selected_during_write(self):
        replacement = Page(uid="42", name="Other bid page", scale_factor2=24.0)
        resources = []

        def execute(_database, requested, operation, **_options):
            resources.extend(requested)
            value = operation(Mock())
            self.model.current_bid_ref = BidRef("test.mdb", "8")
            self.model.current_bid = Bid("8", "Other bid")
            self.model.set_pages({"42": replacement})
            return SimpleNamespace(
                outcome_status=MutationOutcomeStatus.COMMITTED,
                value=value,
            )

        reloads = []
        self.service._execute_database_mutation = execute
        self.service._reload_database = lambda path: reloads.append(path) or True
        self.assertTrue(self.service.save_page_scale("test.mdb", "42", 1.0, 96.0))
        self.assertEqual(str(resources[0].bid_uid), "7")
        self.assertEqual(replacement.scale_factor2, 24.0)
        self.assertEqual(reloads, ["test.mdb"])

    def test_unrelated_replacement_deletion_navigation_and_permission_loss_reject(self):
        for saved_first in (False, True):
            for change in ("replace", "delete", "page", "bid", "permission"):
                with self.subTest(change=change, saved_first=saved_first):
                    self.setUp()

                    def interact(dialog):
                        if saved_first:
                            self._change(dialog, 96)
                            dialog._on_apply()
                        saved = self.model.get_page("42")
                        if change == "replace":
                            self.model.set_pages({"42": replace(saved)})
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
                        self._change(dialog, 192)
                        with self.assertLogs(
                            "ost_visualizer.presentation.coordinators.ui_event_coordinator",
                            level="WARNING",
                        ) as logs, patch(
                            "ost_visualizer.presentation.dialogs.set_scale_dialog.show_warning"
                        ):
                            dialog._on_apply()
                        self.assertIn("context_current=False", logs.output[0])
                        expected = {
                            "replace": "page_current=False",
                            "delete": "page_present=False",
                            "page": "selection_current=False",
                            "bid": "selection_current=False",
                            "permission": "edit_allowed=False",
                        }
                        self.assertIn(expected[change], logs.output[0])
                        self.assertEqual(len(self.write_calls), int(saved_first))
                        self.assertEqual(
                            self.persisted["42"].scale_factor2,
                            96 if saved_first else 48,
                        )

                    self._open(interact)

    def test_failed_write_and_exception_keep_original_owner_for_retry(self):
        for failure in (False, RuntimeError("write failed")):
            with self.subTest(failure=type(failure).__name__):
                self.setUp()

                def interact(dialog):
                    self.writer.save_page_scale.side_effect = (
                        failure if isinstance(failure, Exception) else None
                    )
                    self.writer.save_page_scale.return_value = False
                    self._change(dialog, 96)
                    with self.assertLogs(
                        "ost_visualizer.presentation.coordinators.ui_event_coordinator",
                        level="WARNING",
                    ) as logs, patch(
                        "ost_visualizer.presentation.dialogs.set_scale_dialog.show_warning"
                    ) as warning:
                        dialog._on_apply()
                    self.assertIn("database=test.mdb, bid=7, page=42", logs.output[0])
                    if isinstance(failure, Exception):
                        self.assertIsNotNone(logs.records[0].exc_info)
                    else:
                        self.assertIn("context_current=True", logs.output[0])
                    warning.assert_called_once_with(
                        dialog, "Save Failed", "Failed to save page scale."
                    )
                    self.assertIs(self.model.get_page("42"), self.original)
                    self.assertTrue(dialog._dirty)
                    self.assertTrue(dialog._apply_btn.isEnabled())
                    self.writer.save_page_scale.side_effect = self._write
                    dialog._on_apply()
                    self._change(dialog, 192)
                    dialog._on_apply()
                    self.assertEqual(len(self.write_calls), 2)
                    self.assertEqual(self.model.get_page("42").scale_factor2, 192)

                self._open(interact)

    def test_scale_save_does_not_depend_on_database_reload(self):
        def failed_reload(database):
            self._reload(database)
            return False

        self.service._reload_database = failed_reload

        def interact(dialog):
            self._change(dialog, 96)
            dialog._on_apply()
            self.assertIs(self.model.get_page("42"), self.original)
            self.assertEqual(self.model.get_page("42").scale_factor2, 96)
            self.assertEqual(self.reloads, [])

        self._open(interact)

    def test_apply_all_then_single_page_save_uses_replacement(self):
        self.persisted["43"] = Page(uid="43", name="Page 43", scale_factor2=24)
        self.model.set_pages(dict(self.persisted))

        def interact(dialog):
            dialog._apply_all_check.setChecked(True)
            self._change(dialog, 96)
            dialog._on_apply()
            self.assertEqual([call[1] for call in self.write_calls], ["42", "43"])
            replacement = self.model.get_page("42")
            dialog._apply_all_check.setChecked(False)
            self._change(dialog, 192)
            dialog._on_apply()
            self.assertEqual([call[1] for call in self.write_calls], ["42", "43", "42"])
            self.assertIs(self.model.get_page("42"), replacement)
            self.assertEqual(self.model.get_page("42").scale_factor2, 192)
            self.assertEqual(self.model.get_page("43").scale_factor2, 96)

        self._open(interact)

    def test_unchanged_and_cancelled_drafts_do_not_write(self):
        def interact(dialog):
            dialog._on_apply()
            self.assertEqual(self.write_calls, [])
            self._change(dialog, 96)
            dialog._on_apply()
            dialog._on_apply()
            self.assertEqual(len(self.write_calls), 1)
            self._change(dialog, 192)
            dialog.reject()
            self.assertEqual(self.model.get_page("42").scale_factor2, 96)
            self.assertEqual(len(self.write_calls), 1)

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
                        self.model.get_page("42"), scale_factor2=96 * (index + 1)
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
            self._change(dialog, 96)
            dialog._on_apply()
            self.assertIs(queued[0][0], handles[0])
            self.assertTrue(dialog._save_pending)
            complete(0)
            self.assertFalse(dialog._save_pending)
            self._change(dialog, 192)
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
