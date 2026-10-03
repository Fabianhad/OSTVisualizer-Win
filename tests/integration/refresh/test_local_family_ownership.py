import os
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch, MagicMock

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
from ost_visualizer.domain.entities.condition import Condition
from ost_visualizer.domain.services.uom_service import CALC_LINEAR_LENGTH, UOM_INCHES
from ost_visualizer.application.events.app_events import AppEvents
from ost_visualizer.presentation.components.conditions_sidebar import ConditionsSidebar
from ost_visualizer.presentation.coordinators.sidebar_coordinator import (
    SidebarCoordinator,
)
from ost_visualizer.application.dtos.collaboration_dtos import ChangeOperation
from ost_visualizer.presentation.coordinators.ui_event_coordinator import (
    UIEventCoordinator,
)
import tests.integration.pages.test_set_scale_apply as scale_fixture
from ost_visualizer.domain.entities.page import Page
from ost_visualizer.domain.entities.takeoff import Takeoff


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
        sidebar.conditions_sidebar = Mock(spec=ConditionsSidebar)
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
        # Only the quantity projection ran; the sidebar was not rebuilt or reloaded.
        self.assertEqual(
            [call[0] for call in sidebar.conditions_sidebar.method_calls],
            ["update_quantities"],
        )
        sidebar.load_condition_summary_from_memory.assert_called_once_with()
