import unittest
from types import SimpleNamespace
from ost_visualizer.domain.entities.hierarchy_data import (
    HierarchyBidInfo,
    HierarchyData,
    HierarchyFileEntry,
    HierarchyProjectInfo,
)
from ost_visualizer.domain.entities.identity_refs import BidRef
from ost_visualizer.presentation.config import TAB_INDEX_TAKEOFF
from ost_visualizer.presentation.main_window import MainWindow
from ost_visualizer.presentation.managers.ui_access_manager import (
    _DATABASE_EDIT_FEATURES,
    MAIN_PLAN_SURFACE_ID,
    Feature,
    UIAccessManager,
)
from ost_visualizer.presentation.services.bid_clipboard_service import (
    BidClipboardService,
)
from tests.application.services.write_permission_support import (
    _DatabaseCapability as _permissions__DatabaseCapability,
    _EventBus as _permissions__EventBus,
    _ProjectData as _permissions__ProjectData,
    _TransactionMonitor as _permissions__TransactionMonitor,
    _hierarchy_with_bids as _permissions__hierarchy_with_bids,
)
from tests.presentation.managers.permission_support import (
    _FakeAccess as _permissions__FakeAccess,
    _FakePlanView as _permissions__FakePlanView,
    _FakeTabWidget as _permissions__FakeTabWidget,
    _License as _permissions__License,
    _ToolbarUiState as _permissions__ToolbarUiState,
    _UiState as _permissions__UiState,
)


class BidLockPermissionTests(unittest.TestCase):
    def _access_manager(self, project_data, ui_state=None, capability=None):
        return UIAccessManager(
            _permissions__EventBus(),
            _permissions__License(),
            _permissions__TransactionMonitor(),
            project_data,
            ui_state or _permissions__UiState(project_data.bid_ref),
            capability or _permissions__DatabaseCapability(),
        )

    def test_context_job_status_does_not_use_active_bid_permission_for_other_target(
        self,
    ):
        project_data = _permissions__ProjectData()

        class _ActiveOnlyCapability:
            @staticmethod
            def is_editable(locator, _resource=None):
                return locator == project_data.bid_ref.file_path

        manager = self._access_manager(
            project_data,
            capability=_ActiveOnlyCapability(),
        )
        updates = []
        window = MainWindow.__new__(MainWindow)
        window.ui_access_manager = manager
        window.handlers = SimpleNamespace(
            delete=SimpleNamespace(
                update_bid_job_status=lambda *args: updates.append(args)
            )
        )
        MainWindow._update_project_tree_bid_job_status(
            window,
            BidRef("C:/jobs/other.mdb", "9"),
            "status-2",
        )
        self.assertEqual(updates, [])
        # Positive control: the same command for the editable (active) database
        # goes through, so the empty result above is a real denial.
        MainWindow._update_project_tree_bid_job_status(
            window, project_data.bid_ref, "status-2"
        )
        self.assertEqual(updates, [(project_data.bid_ref, "status-2")])

    def test_project_tree_delete_rejects_selection_with_inaccessible_bid(self):
        project_data = _permissions__ProjectData()
        active_ref = project_data.bid_ref
        other_ref = BidRef("C:/jobs/other.mdb", "9")

        class _SelectedBidsState(_permissions__UiState):
            def get_selected_bid_refs(self):
                return [active_ref, other_ref]

        class _ActiveOnlyCapability:
            @staticmethod
            def is_editable(locator, _resource=None):
                return locator == active_ref.file_path

        ui_state = _SelectedBidsState(active_ref)
        manager = self._access_manager(
            project_data,
            ui_state=ui_state,
            capability=_ActiveOnlyCapability(),
        )
        calls = []
        window = MainWindow.__new__(MainWindow)
        window._handle_inline_text_shortcut = lambda _command: False
        window.tab_widget = _permissions__FakeTabWidget(0)
        window.ui_state_manager = ui_state
        window.ui_access_manager = manager
        window.project_view = SimpleNamespace(
            get_delete_replacement_selection_state=lambda: {"kind": "file_root"}
        )
        window.handlers = SimpleNamespace(
            delete=SimpleNamespace(
                delete_selected=lambda selection: calls.append(selection)
            )
        )
        MainWindow._delete_selected(window)
        self.assertEqual(calls, [])
        # Positive control: with only the accessible bid selected, delete runs.
        accessible_state = _permissions__UiState(active_ref)
        accessible_state.get_selected_bid_refs = lambda: [active_ref]
        window.ui_state_manager = accessible_state
        window.ui_access_manager = self._access_manager(
            project_data,
            ui_state=accessible_state,
            capability=_ActiveOnlyCapability(),
        )
        MainWindow._delete_selected(window)
        self.assertEqual(calls, [{"kind": "file_root"}])

    def test_project_tree_cut_checks_every_selected_bid_resource(self):
        project_data = _permissions__ProjectData()
        active_ref = project_data.bid_ref
        blocked_ref = BidRef(active_ref.file_path, "9")

        class _SelectedBidsState(_permissions__UiState):
            def get_selected_bid_refs(self):
                return [active_ref, blocked_ref]

        class _SecondBidLockedCapability:
            @staticmethod
            def is_editable(_locator, resource=None):
                return resource is None or resource.resource_id != "9"

        ui_state = _SelectedBidsState(active_ref)
        manager = self._access_manager(
            project_data,
            ui_state=ui_state,
            capability=_SecondBidLockedCapability(),
        )
        cut_calls = []
        window = MainWindow.__new__(MainWindow)
        window._handle_inline_text_shortcut = lambda _command: False
        window.tab_widget = _permissions__FakeTabWidget(0)
        window.ui_state_manager = ui_state
        window.ui_access_manager = manager
        window._bid_clipboard = SimpleNamespace(cut=cut_calls.append)
        MainWindow._cut_selected(window)
        self.assertEqual(cut_calls, [])
        # Positive control: with only the unlocked bid selected, cut proceeds.
        accessible_state = _permissions__UiState(active_ref)
        accessible_state.get_selected_bid_refs = lambda: [active_ref]
        window.ui_state_manager = accessible_state
        window.ui_access_manager = self._access_manager(
            project_data,
            ui_state=accessible_state,
            capability=_SecondBidLockedCapability(),
        )
        window.handlers = SimpleNamespace(
            ui_event=SimpleNamespace(refresh_toolbar=lambda: None)
        )
        MainWindow._cut_selected(window)
        self.assertEqual(cut_calls, [[active_ref]])

    def test_context_paste_checks_captured_destination_database(self):
        project_data = _permissions__ProjectData()

        class _ActiveOnlyCapability:
            @staticmethod
            def is_editable(locator, _resource=None):
                return locator == project_data.bid_ref.file_path

        manager = self._access_manager(
            project_data,
            capability=_ActiveOnlyCapability(),
        )
        window = MainWindow.__new__(MainWindow)
        window.ui_access_manager = manager
        window._project_data_service = SimpleNamespace(get_hierarchy=lambda: object())
        window._bid_clipboard = SimpleNamespace(
            is_cut=False,
            bid_refs=[BidRef("C:/jobs/other.mdb", "9")],
            reconcile=lambda _hierarchy: None,
            has_content=lambda: True,
            source_matches_file=lambda path: path == "C:/jobs/other.mdb",
        )
        allowed = MainWindow._can_paste_project_bids(
            window, "C:/jobs/other.mdb", "project-9"
        )
        self.assertFalse(allowed)
        # Positive control: the same clipboard shape is allowed for the
        # editable database, so only the captured destination decides.
        active_file = project_data.bid_ref.file_path
        window._bid_clipboard = SimpleNamespace(
            is_cut=False,
            bid_refs=[BidRef(active_file, "9")],
            reconcile=lambda _hierarchy: None,
            has_content=lambda: True,
            source_matches_file=lambda path: path == active_file,
        )
        self.assertTrue(
            MainWindow._can_paste_project_bids(window, active_file, "project-9")
        )

    def test_takeoff_shortcuts_do_not_run_when_selection_access_denied(self):
        project_data = _permissions__ProjectData()
        project_data.locked = True
        ui_state = _permissions__ToolbarUiState(project_data.bid_ref)
        manager = self._access_manager(project_data, ui_state)
        window = MainWindow.__new__(MainWindow)
        window.tab_widget = _permissions__FakeTabWidget(TAB_INDEX_TAKEOFF)
        window.ui_access_manager = manager
        window.plan_view = _permissions__FakePlanView()
        window.handlers = SimpleNamespace(
            ui_event=SimpleNamespace(refresh_toolbar=lambda: None)
        )
        MainWindow._delete_selected(window)
        MainWindow._select_all(window)
        self.assertEqual(window.plan_view.deleted, 0)
        self.assertEqual(window.plan_view.selected_all, 0)
        # Positive control: unlocking the bid lets the same shortcuts act.
        project_data.locked = False
        MainWindow._delete_selected(window)
        MainWindow._select_all(window)
        self.assertEqual(window.plan_view.deleted, 1)
        self.assertEqual(window.plan_view.selected_all, 1)

    def test_project_paste_allows_same_database_with_normalized_paths(self):
        window = MainWindow.__new__(MainWindow)
        window._bid_clipboard = BidClipboardService()
        window._bid_clipboard.copy([BidRef("C:/jobs/test.mdb", "bid-1")])
        window._project_data_service = SimpleNamespace(
            get_hierarchy=lambda: HierarchyData(
                loaded_files=[
                    HierarchyFileEntry(
                        file_path="C:\\jobs\\test.mdb",
                        bid_projects={
                            "project-1": HierarchyProjectInfo(
                                name="Project 1",
                                bids=[HierarchyBidInfo(uid="bid-1")],
                            )
                        },
                    )
                ]
            )
        )
        window.ui_access_manager = _permissions__FakeAccess({Feature.DUPLICATE_BID})
        self.assertTrue(
            MainWindow._can_paste_project_bids(
                window, "C:\\jobs\\test.mdb", "project-2"
            )
        )
        # Negative control: the same normalized-path paste is refused once the
        # duplicate permission is gone.
        window.ui_access_manager.allowed.clear()
        self.assertFalse(
            MainWindow._can_paste_project_bids(
                window, "C:\\jobs\\test.mdb", "project-2"
            )
        )
        self.assertTrue(window._bid_clipboard.has_content())

    def test_context_copy_stores_bid_clipboard_with_normalized_same_database_refs(self):
        window = MainWindow.__new__(MainWindow)
        window.ui_access_manager = _permissions__FakeAccess({Feature.COPY_BID})
        window._bid_clipboard = BidClipboardService()
        refresh_calls = []
        window.handlers = SimpleNamespace(
            ui_event=SimpleNamespace(refresh_toolbar=lambda: refresh_calls.append(True))
        )
        MainWindow._copy_project_bids(
            window,
            [
                BidRef("C:/jobs/test.mdb", "bid-1"),
                BidRef("C:\\jobs\\test.mdb", "bid-2"),
            ],
        )
        self.assertEqual(
            [ref.bid_uid for ref in window._bid_clipboard.bid_refs],
            ["bid-1", "bid-2"],
        )
        self.assertEqual(refresh_calls, [True])
        # Negative control: without COPY_BID the command leaves the clipboard alone.
        window.ui_access_manager.allowed.clear()
        window._bid_clipboard = BidClipboardService()
        MainWindow._copy_project_bids(window, [BidRef("C:/jobs/test.mdb", "bid-1")])
        self.assertFalse(window._bid_clipboard.has_content())
        self.assertEqual(refresh_calls, [True])

    def test_project_paste_invokes_bid_paste_handler_for_same_database_target(self):
        window = MainWindow.__new__(MainWindow)
        window._bid_clipboard = BidClipboardService()
        window._bid_clipboard.copy([BidRef("C:/jobs/test.mdb", "bid-1")])
        window._project_data_service = SimpleNamespace(
            get_hierarchy=lambda: _permissions__hierarchy_with_bids("bid-1")
        )
        window.ui_access_manager = _permissions__FakeAccess({Feature.DUPLICATE_BID})
        paste_calls = []
        refresh_calls = []
        window.handlers = SimpleNamespace(
            delete=SimpleNamespace(
                paste_bids=lambda refs, project_uid, is_cut=False: paste_calls.append(
                    ([ref.bid_uid for ref in refs], project_uid, is_cut)
                )
                or True
            ),
            ui_event=SimpleNamespace(
                refresh_toolbar=lambda: refresh_calls.append(True)
            ),
        )
        MainWindow._paste_project_bids(window, "C:\\jobs\\test.mdb", "project-2")
        self.assertEqual(paste_calls, [(["bid-1"], "project-2", False)])
        self.assertEqual(refresh_calls, [True])

    def test_project_cut_clipboard_waits_for_authoritative_move_completion(self):
        window = MainWindow.__new__(MainWindow)
        window._bid_clipboard = BidClipboardService()
        window._bid_clipboard.cut([BidRef("C:/jobs/test.mdb", "bid-1")])
        window._project_data_service = SimpleNamespace(
            get_hierarchy=lambda: _permissions__hierarchy_with_bids("bid-1")
        )
        window.ui_access_manager = _permissions__FakeAccess({Feature.DELETE_BID})
        completions = []
        refresh_calls = []

        def paste_bids(
            _refs,
            _project_uid,
            *,
            is_cut=False,
            on_cut_committed=None,
        ):
            self.assertTrue(is_cut)
            completions.append(on_cut_committed)
            return True

        window.handlers = SimpleNamespace(
            delete=SimpleNamespace(paste_bids=paste_bids),
            ui_event=SimpleNamespace(
                refresh_toolbar=lambda: refresh_calls.append(True)
            ),
        )
        MainWindow._paste_project_bids(window, "C:/jobs/test.mdb", "project-2")
        self.assertTrue(window._bid_clipboard.has_content())
        completions[0]()
        self.assertFalse(window._bid_clipboard.has_content())
        self.assertEqual(refresh_calls, [True, True])

    def test_older_bid_cut_completion_preserves_newer_clipboard(self):
        window = MainWindow.__new__(MainWindow)
        window._bid_clipboard = BidClipboardService()
        window._bid_clipboard.cut([BidRef("C:/jobs/test.mdb", "bid-1")])
        window._project_data_service = SimpleNamespace(
            get_hierarchy=lambda: _permissions__hierarchy_with_bids("bid-1", "bid-2")
        )
        window.ui_access_manager = _permissions__FakeAccess({Feature.DELETE_BID})
        completions = []

        def paste_bids(
            _refs,
            _project_uid,
            *,
            is_cut=False,
            on_cut_committed=None,
        ):
            self.assertTrue(is_cut)
            completions.append(on_cut_committed)
            return True

        window.handlers = SimpleNamespace(
            delete=SimpleNamespace(paste_bids=paste_bids),
            ui_event=SimpleNamespace(refresh_toolbar=lambda: None),
        )
        MainWindow._paste_project_bids(window, "C:/jobs/test.mdb", "project-2")
        window._bid_clipboard.cut([BidRef("C:/jobs/test.mdb", "bid-2")])
        completions[0]()
        self.assertTrue(window._bid_clipboard.is_cut)
        self.assertEqual(
            window._bid_clipboard.bid_refs,
            [BidRef("C:/jobs/test.mdb", "bid-2")],
        )

    def test_project_paste_reconciles_partial_remote_bid_deletion(self):
        window = MainWindow.__new__(MainWindow)
        window._bid_clipboard = BidClipboardService()
        window._bid_clipboard.cut(
            [
                BidRef("C:/jobs/test.mdb", "deleted-bid"),
                BidRef("C:/jobs/test.mdb", "surviving-bid"),
            ]
        )
        window._project_data_service = SimpleNamespace(
            get_hierarchy=lambda: HierarchyData(
                loaded_files=[
                    HierarchyFileEntry(
                        file_path="C:\\jobs\\test.mdb",
                        bid_projects={
                            "project-1": HierarchyProjectInfo(
                                name="Project 1",
                                bids=[HierarchyBidInfo(uid="surviving-bid")],
                            )
                        },
                    )
                ]
            )
        )
        window.ui_access_manager = _permissions__FakeAccess({Feature.DELETE_BID})
        self.assertTrue(
            MainWindow._can_paste_project_bids(window, "C:/jobs/test.mdb", "project-2")
        )
        self.assertEqual(
            [ref.bid_uid for ref in window._bid_clipboard.bid_refs],
            ["surviving-bid"],
        )

    def test_project_paste_allowed_when_project_target_replaces_bid_selection(self):
        project_data = _permissions__ProjectData()
        ui_state = SimpleNamespace(
            selected_file_path="C:/jobs/test.mdb",
            selected_project_uid="project-2",
            place_condition_uid=None,
            get_selected_bid_ref=lambda: None,
            is_database_selected=lambda: False,
        )
        manager = self._access_manager(project_data, ui_state)
        self.assertFalse(manager.is_allowed(Feature.DUPLICATE_BID))
        window = MainWindow.__new__(MainWindow)
        window._bid_clipboard = BidClipboardService()
        window._bid_clipboard.copy([BidRef("C:/jobs/test.mdb", "bid-1")])
        window._project_data_service = SimpleNamespace(
            get_hierarchy=lambda: _permissions__hierarchy_with_bids("bid-1")
        )
        window.ui_access_manager = manager
        self.assertTrue(
            MainWindow._can_paste_project_bids(window, "C:/jobs/test.mdb", "project-2")
        )
