import os
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch, MagicMock
from contextlib import nullcontext

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from ost_visualizer.domain.entities.hierarchy_data import (
    HierarchyBidInfo,
    HierarchyData,
    HierarchyFileEntry,
    HierarchyPageInfo,
    HierarchyFolderInfo,
)
from ost_visualizer.domain.entities.cover_sheet import (
    CoverSheetData,
    CoverSheetFolder,
    CoverSheetPage,
)
from ost_visualizer.domain.entities.bid import Bid
from ost_visualizer.domain.entities.identity_refs import BidRef
from ost_visualizer.domain.entities.condition import Condition
from ost_visualizer.domain.services.uom_service import CALC_LINEAR_LENGTH, UOM_INCHES
from ost_visualizer.application.events.app_events import AppEvents
from ost_visualizer.presentation.coordinators.sidebar_coordinator import (
    SidebarCoordinator,
)
from ost_visualizer.application.dtos.collaboration_dtos import ChangeOperation
from ost_visualizer.presentation.coordinators.ui_event_coordinator import (
    UIEventCoordinator,
)
from tests import test_set_scale_repeated_apply as scale_fixture
from ost_visualizer.domain.entities.page import Page
from ost_visualizer.domain.entities.takeoff import Takeoff
from ost_visualizer.presentation.components.page_combo import (
    PageComboBox,
    SinglePageComboBox,
)
from ost_visualizer.presentation.managers.detached_page_view_manager import (
    DetachedPageViewManager,
)
from ost_visualizer.infrastructure.mdb.mdb_reader import MdbReader
from ost_visualizer.infrastructure.sql.reader import SqlProjectReader


class RefreshScopeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        scale_fixture.SetScaleRepeatedApplyTests.setUpClass()

    def setUp(self):
        self.fixture = scale_fixture.SetScaleRepeatedApplyTests()
        self.fixture.setUp()
        self.service = self.fixture.service
        self.service._save_page_name = SimpleNamespace(execute=lambda *_args: True)
        self.info = HierarchyPageInfo("42", "Page 42")
        self.fixture.model.set_hierarchy(
            HierarchyData(
                loaded_files=[
                    HierarchyFileEntry(
                        "test.mdb",
                        orphan_bids=[
                            HierarchyBidInfo("7", pages_without_folder=[self.info])
                        ],
                    )
                ]
            )
        )

    def test_page_rename_preserves_page_and_bid_without_database_reload(self):
        bid = self.fixture.model.current_bid
        self.assertTrue(self.service.save_page_name("test.mdb", "42", "Renamed"))
        self.assertEqual(self.fixture.reloads, [])
        self.assertIs(self.fixture.data.get_page("42"), self.fixture.original)
        self.assertIs(self.fixture.model.current_bid, bid)
        self.assertEqual(self.fixture.original.name, "Renamed")
        self.assertEqual(self.info.name, "Renamed")

    def test_other_database_refresh_does_not_reconcile_active_workspace(self):
        coordinator = UIEventCoordinator.__new__(UIEventCoordinator)
        coordinator.ui_state_manager = SimpleNamespace(
            get_selected_bid_ref=lambda: BidRef("active.mdb", "7"),
            selected_area_uid="",
            selected_page_uids=["42"],
        )
        coordinator._flush_deferred_for_file = Mock(return_value=True)
        coordinator._nav = Mock()
        coordinator._placement = Mock()
        coordinator._do_file_refresh = Mock()
        coordinator._finish_refresh = Mock()
        coordinator._clear_mesh_views_for_scene_update = Mock()
        coordinator._mark_mesh_scene_dirty = Mock()
        coordinator._flush_dirty_mesh_refresh_if_needed = Mock()
        coordinator._restore_project_tree_bid_selection_if_needed = Mock()
        coordinator._update_export_menu_state = Mock()
        coordinator._on_database_refreshed("other.mdb")
        coordinator._do_file_refresh.assert_called_once_with()
        coordinator._nav.start_refresh.assert_not_called()
        coordinator._finish_refresh.assert_not_called()
        coordinator._clear_mesh_views_for_scene_update.assert_not_called()

    def test_metadata_updates_nested_hierarchy_and_cover_sheet_only_in_own_database(
        self,
    ):
        bid_info = self.fixture.model.find_bid_info(self.fixture.bid_ref)
        bid_info.pages_without_folder = []
        bid_info.folders = {
            "parent": HierarchyFolderInfo(
                "Parent",
                subfolders={"child": HierarchyFolderInfo("Child", pages=[self.info])},
            )
        }
        cover_page = CoverSheetPage("42", "", "Original", 10, 10, 1, 48, "", "", 0, 0)
        cover_sheet = CoverSheetData(
            "7",
            "",
            "",
            "",
            "",
            "",
            "",
            "",
            folders={
                "parent": CoverSheetFolder(
                    "parent",
                    "Parent",
                    subfolders={
                        "child": CoverSheetFolder("child", "Child", pages=[cover_page])
                    },
                )
            },
        )
        self.fixture.data.replace_cover_sheet_data("test.mdb", "7", cover_sheet)
        self.fixture.data.replace_cover_sheet_data("other.mdb", "7", cover_sheet)
        self.assertTrue(self.service.save_page_name("test.mdb", "42", "Renamed"))
        self.assertTrue(self.service.save_page_scale("test.mdb", "42", 1, 24))
        self.assertEqual(self.info.name, "Renamed")
        self.assertEqual(self.info.scale_factor2, 24)
        for database, name, scale in (
            ("test.mdb", "Renamed", 24),
            ("other.mdb", "Original", 48),
        ):
            snapshot = self.fixture.data.get_cover_sheet_snapshot(database, "7")
            page = snapshot.folders["parent"].subfolders["child"].pages[0]
            self.assertEqual(page.name, name)
            self.assertEqual(page.scale_factor2, scale)
        self.assertEqual(self.fixture.reloads, [])

    def test_condition_update_reloads_only_condition_family(self):
        condition = Condition("12", "Updated", 0)
        self.service._condition_family_reader = Mock(
            return_value=({"12": condition}, {})
        )
        page = self.fixture.original
        self.assertTrue(
            self.service.reload_conditions_and_notify(
                "test.mdb", "7", ["12"], ["name"], [ChangeOperation.UPDATE]
            )
        )
        self.assertEqual(self.fixture.reloads, [])
        self.assertIs(self.fixture.data.get_page("42"), page)
        self.assertIs(self.fixture.data.get_bid_conditions()["12"], condition)

    def test_condition_folder_and_renumber_refresh_only_the_family(self):
        self.service._condition_family_reader = Mock(return_value=({}, {}))
        for fields, operations in (
            (["ref_no"], [ChangeOperation.REORDER]),
            (["condition_folder"], []),
        ):
            with self.subTest(fields=fields):
                self.assertTrue(
                    self.service.reload_conditions_and_notify(
                        "test.mdb", "7", [], fields, operations
                    )
                )
        self.assertEqual(self.fixture.reloads, [])
        self.assertEqual(self.service._condition_family_reader.call_count, 2)

    def test_condition_delete_retains_full_reload_for_cascades(self):
        self.service._condition_family_reader = Mock()
        self.assertTrue(
            self.service.reload_conditions_and_notify(
                "test.mdb", "7", ["12"], [], [ChangeOperation.DELETE]
            )
        )
        self.assertEqual(len(self.fixture.reloads), 1)
        self.service._condition_family_reader.assert_not_called()

    def test_shared_condition_family_reader_does_not_read_takeoffs_or_pages(self):
        for reader_type in (MdbReader, SqlProjectReader):
            with self.subTest(reader=reader_type):
                reader = reader_type.__new__(reader_type)
                connection = MagicMock()
                reader._connection = lambda _path: nullcontext(connection)
                reader._schema = Mock(return_value=object())
                reader._parse_bid_layers_for_bid = Mock(return_value={})
                reader._parse_cdn_types = Mock(return_value={})
                reader._parse_bid_conditions_for_bid = Mock(
                    return_value={"12": Condition("12", "Updated", 0)}
                )
                reader._parse_bid_condition_folders_for_bid = Mock(return_value={})
                reader._parse_bid_takeoffs_for_bid = Mock(
                    side_effect=AssertionError("Takeoff graph read")
                )
                reader._parse_bid_pages_for_bid = Mock(
                    side_effect=AssertionError("Page graph read")
                )
                with patch(
                    "ost_visualizer.infrastructure.mdb.components.bid_data_reader.require_existing_unique_bid_owned_uid_matches"
                ) as validate:
                    conditions, folders = reader.get_condition_family("test.mdb", "7")
                self.assertEqual(list(conditions), ["12"])
                self.assertEqual(folders, {})
                validate.assert_called_once_with(
                    connection.cursor.return_value.__enter__.return_value,
                    "Bids",
                    ("7",),
                )
                reader._parse_bid_takeoffs_for_bid.assert_not_called()
                reader._parse_bid_pages_for_bid.assert_not_called()

    def test_failed_family_read_retains_original_family_without_success_projection(
        self,
    ):
        original = self.fixture.model.bid_conditions
        self.service._condition_family_reader = Mock(side_effect=OSError("Read failed"))
        self.service._reload_database = Mock(return_value=False)
        with self.assertLogs(self.service.logger, level="WARNING"):
            self.assertFalse(
                self.service.reload_conditions_and_notify(
                    "test.mdb", "7", [], ["name"], [ChangeOperation.UPDATE]
                )
            )
        self.assertIs(self.fixture.model.bid_conditions, original)
        self.service._reload_database.assert_not_called()

    def test_replaced_bid_during_family_read_uses_full_reload(self):
        original_conditions = self.fixture.model.bid_conditions

        def read(*_args):
            self.fixture.model.current_bid = Bid("7", "New lifetime")
            return {"12": Condition("12", "Updated", 0)}, {}

        self.service._condition_family_reader = read
        self.service._reload_database = Mock(return_value=False)
        self.assertFalse(
            self.service.reload_conditions_and_notify(
                "test.mdb", "7", ["12"], ["name"], [ChangeOperation.UPDATE]
            )
        )
        self.assertIs(self.fixture.model.bid_conditions, original_conditions)
        self.service._reload_database.assert_called_once_with("test.mdb")

    def test_missing_takeoff_owner_does_not_partially_project_condition_family(self):
        original = {"12": Condition("12", "Original", 0)}
        self.fixture.model.bid_conditions = original
        self.fixture.original.takeoffs = [Takeoff("3", "12", page_uid="42")]
        self.service._condition_family_reader = Mock(return_value=({}, {}))
        self.service._reload_database = Mock(return_value=False)
        self.assertFalse(
            self.service.reload_conditions_and_notify(
                "test.mdb", "7", ["12"], ["name"], [ChangeOperation.UPDATE]
            )
        )
        self.assertIs(self.fixture.model.bid_conditions, original)
        self.service._reload_database.assert_called_once_with("test.mdb")

    def test_rename_replaced_page_uses_fallback_without_mutating_replacement(self):
        replacement = Page("42", "Different lifetime")

        def persist(*_args):
            self.fixture.model.set_pages({"42": replacement})
            return True

        self.service._save_page_name.execute = persist
        self.service._reload_database = Mock(return_value=True)
        self.assertTrue(self.service.save_page_name("test.mdb", "42", "Renamed"))
        self.assertEqual(replacement.name, "Different lifetime")
        self.service._reload_database.assert_called_once_with("test.mdb")

    def test_failed_rename_preserves_all_metadata(self):
        self.service._save_page_name.execute = lambda *_args: False
        self.assertFalse(self.service.save_page_name("test.mdb", "42", "Renamed"))
        self.assertEqual(self.fixture.original.name, "Page 42")
        self.assertEqual(self.info.name, "Page 42")
        self.assertEqual(self.fixture.reloads, [])

    def test_page_label_projection_keeps_qt_items_selection_and_signals(self):
        bid = self.fixture.model.current_bid
        for combo_type in (PageComboBox, SinglePageComboBox):
            with self.subTest(combo=combo_type):
                combo = combo_type()
                combo.load_bid(bid)
                calls = []
                if isinstance(combo, PageComboBox):
                    combo.restore_selection(["42"], "42")
                    combo.page_selection_changed.connect(
                        lambda *_args: calls.append("selection")
                    )
                else:
                    combo.set_current_page_uid("42")
                    combo.page_activated.connect(
                        lambda *_args: calls.append("activation")
                    )
                item = combo._page_items["42"]
                state = item.checkState()
                combo._model.modelReset.connect(lambda: calls.append("reset"))
                self.fixture.original.name = "New label"
                combo.refresh_page_labels([self.fixture.original])
                self.assertIs(combo._page_items["42"], item)
                self.assertEqual(item.text(), "New label")
                self.assertEqual(item.checkState(), state)
                self.assertIn("New label", combo.currentText())
                self.assertEqual(calls, [])
                combo.cleanup()
                combo.deleteLater()

    def test_name_event_updates_main_labels_without_canvas_or_mesh_projection(self):
        coordinator = UIEventCoordinator.__new__(UIEventCoordinator)
        coordinator.ui_state_manager = SimpleNamespace(
            get_selected_bid_ref=lambda: self.fixture.bid_ref
        )
        coordinator.project_data = self.fixture.data
        coordinator.takeoff_sidebar = Mock()
        coordinator._sync_page_info_status = Mock()
        coordinator._is_summary_tab_active = lambda: False
        coordinator._viewer = Mock()
        coordinator._request_or_defer_mesh_refresh = Mock()
        coordinator._on_page_metadata_changed("test.mdb", "7", ("42",), ("name",))
        coordinator.takeoff_sidebar.refresh_page_labels.assert_called_once_with(
            [self.fixture.original]
        )
        self.assertEqual(coordinator._viewer.mock_calls, [])
        coordinator._request_or_defer_mesh_refresh.assert_not_called()

    def test_scale_save_refreshes_displayed_quantities_without_sidebar_rebuild(self):
        self.fixture.model.bid_conditions = {
            "12": Condition(
                "12", "Line", 0, calc_type1=CALC_LINEAR_LENGTH, uom1=UOM_INCHES
            )
        }
        takeoff = Takeoff("3", "12", page_uid="42", position=[0, 0, 12, 0])
        self.fixture.original.takeoffs = [takeoff]
        self.fixture.model.bid_takeoffs = [takeoff]
        self.fixture.model.select_pages(["42"])
        coordinator = UIEventCoordinator.__new__(UIEventCoordinator)
        coordinator.ui_state_manager = self.fixture.coordinator.ui_state_manager
        coordinator.project_data = self.fixture.data
        coordinator._viewer = Mock()
        coordinator._update_page_settings_bar = Mock()
        coordinator._apply_pending_hotlink_named_view_focus = Mock()
        coordinator._request_or_defer_mesh_refresh = Mock()
        coordinator._is_summary_tab_active = lambda: True
        sidebar = SidebarCoordinator.__new__(SidebarCoordinator)
        sidebar.conditions_sidebar = Mock()
        sidebar._view_stack = None
        sidebar._ui_state = coordinator.ui_state_manager
        sidebar._project_data = self.fixture.data
        sidebar.load_condition_summary_from_memory = Mock()
        coordinator._sidebar = sidebar
        sidebar.update_conditions_quantities()
        before = sidebar.conditions_sidebar.update_quantities.call_args.args[0]["12"][0]
        sidebar.conditions_sidebar.reset_mock()
        self.fixture.events.subscribe(
            AppEvents.PAGE_METADATA_CHANGED, coordinator._on_page_metadata_changed
        )
        self.assertTrue(self.service.save_page_scale("test.mdb", "42", 1, 24))
        sidebar.conditions_sidebar.update_quantities.assert_called_once()
        after = sidebar.conditions_sidebar.update_quantities.call_args.args[0]["12"][0]
        self.assertEqual(before, 12)
        self.assertEqual(after, 6)
        sidebar.load_condition_summary_from_memory.assert_called_once_with()

    def test_name_event_updates_detached_navigation_without_refreshing_other_page(self):
        manager = DetachedPageViewManager.__new__(DetachedPageViewManager)
        manager.is_view_open = lambda: True
        manager.repository = SimpleNamespace(
            get_active_view=lambda: SimpleNamespace(
                bid_ref=self.fixture.bid_ref, target_page_uid="other"
            )
        )
        manager.project_data = self.fixture.data
        manager._window = Mock()
        manager._get_page_data = Mock()
        manager._on_page_metadata_changed("test.mdb", "7", ("42",), ("name",))
        manager._window.refresh_page_labels.assert_called_once_with(
            [self.fixture.original]
        )
        manager._window.update_page_scale.assert_not_called()
        manager._get_page_data.assert_not_called()


if __name__ == "__main__":
    unittest.main()
