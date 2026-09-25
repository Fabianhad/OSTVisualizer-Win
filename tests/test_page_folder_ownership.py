import logging
import sqlite3
import unittest
from copy import deepcopy
from unittest.mock import Mock
from ost_visualizer.application.dtos.user_workspace_state_dtos import (
    UserBidWorkspaceState,
)
from ost_visualizer.application.use_cases.project.load_bid_use_case import (
    LoadBidUseCase,
    PreparedBidLoad,
)
from ost_visualizer.domain.aggregates.ost_aggregate import OstAggregate
from ost_visualizer.domain.entities.bid import Bid
from ost_visualizer.domain.entities.file_results import BidLoadResult
from ost_visualizer.domain.entities.hierarchy_data import (
    HierarchyBidInfo,
    HierarchyData,
    HierarchyFileEntry,
    HierarchyFolderInfo,
    HierarchyPageInfo,
)
from ost_visualizer.domain.entities.identity_refs import BidRef
from ost_visualizer.domain.entities.page import Page, build_pages_from_bid_data
from ost_visualizer.domain.entities.project_factory import build_bid
from ost_visualizer.domain.services.file_manager_service import FileManager
from ost_visualizer.domain.services.project_data_service import ProjectDataService
from ost_visualizer.infrastructure.mdb.components.bid_data_reader import (
    BidDataReaderMixin,
)
from ost_visualizer.infrastructure.mdb.components.hierarchy_reader import (
    HierarchyReaderMixin,
)
from ost_visualizer.infrastructure.persistence.repositories.file_project_repository import (
    FileProjectRepository,
)
from tests.test_bid_data_reader import _LimitedReadConnection
from tests.test_hierarchy_reader import _SqliteHierarchySchema


class PageFolderOwnershipTests(unittest.TestCase):
    def setUp(self):
        self.connection = sqlite3.connect(":memory:")
        self.addCleanup(self.connection.close)
        self.connection.execute(
            "CREATE TABLE BidPages (UID INTEGER, BidUID INTEGER, Name TEXT, Sequence INTEGER, BidPageFolderUID INTEGER)"
        )
        self.connection.executemany(
            "INSERT INTO BidPages VALUES (?, ?, ?, ?, ?)",
            [
                (1, 8, "Nested second", 20, 11),
                (2, 8, "Nested first", 10, 11),
                (3, 8, "Root", 30, None),
                (4, 8, "Parent", 5, 10),
                (5, 9, "Other bid", 1, 11),
            ],
        )
        self.bid_ref = BidRef("database", "8")
        self.info = HierarchyBidInfo(
            uid="8",
            name="Bid",
            folders={
                "10": HierarchyFolderInfo(
                    name="Parent",
                    pages=[HierarchyPageInfo(uid="4", name="Parent")],
                    subfolders={
                        "11": HierarchyFolderInfo(
                            name="Nested",
                            pages=[
                                HierarchyPageInfo(uid="1", name="Nested second"),
                                HierarchyPageInfo(uid="2", name="Nested first"),
                            ],
                        )
                    },
                )
            },
            pages_without_folder=[HierarchyPageInfo(uid="3", name="Root")],
        )
        self.model = OstAggregate(Mock())
        self.model.set_hierarchy(
            HierarchyData(
                loaded_files=[
                    HierarchyFileEntry(file_path="database", orphan_bids=[self.info])
                ]
            )
        )
        self.model.current_bid_ref = self.bid_ref
        self.model.current_bid = build_bid(self.info)

    def read(self):
        reader = BidDataReaderMixin()
        reader.logger = logging.getLogger(__name__)
        schema = _SqliteHierarchySchema(self.connection)
        infos = reader._parse_bid_pages_for_bid(
            _LimitedReadConnection(self.connection, schema), "8", {}, schema
        )
        return BidLoadResult(
            bid_pages=infos, pages=build_pages_from_bid_data(infos, [])
        )

    def assert_nested(self):
        bid = self.model.current_bid
        nested = bid.folders["10"].subfolders["11"]
        self.assertEqual([page.uid for page in nested.pages], ["2", "1"])
        for page in nested.pages:
            self.assertIs(self.model.get_page(page.uid), page)
            self.assertEqual(page.folder_uid, "11")
        self.assertEqual([page.uid for page in bid.pages_without_folder], ["3"])
        self.assertEqual(bid.page_count, 4)

    def test_remote_hydration_preserves_nested_ownership_and_exact_pages(self):
        old = self.model.current_bid.folders["10"].subfolders["11"].pages[0]
        service = ProjectDataService(self.model)
        self.assertTrue(
            service.replace_remote_bid_families(self.bid_ref, self.read(), {"pages"})
        )
        self.assert_nested()
        self.assertIsNot(self.model.get_page("1"), old)

    def test_mdb_and_sql_prepared_loads_preserve_ownership(self):
        for workspace in (None, UserBidWorkspaceState()):
            for prebuilt in (False, True):
                with self.subTest(sql=workspace is not None, prebuilt=prebuilt):
                    data = self.read()
                    if not prebuilt:
                        data.pages = {}
                    use_case = LoadBidUseCase(
                        self.model, Mock(), Mock(), Mock(), Mock()
                    )
                    self.assertTrue(
                        use_case.apply_prepared(
                            self.bid_ref, PreparedBidLoad(data, workspace)
                        )
                    )
                    self.assert_nested()

    def test_load_does_not_overwrite_new_folder_assignment_with_cached_hierarchy(self):
        self.connection.execute(
            "UPDATE BidPages SET BidPageFolderUID = 10 WHERE UID = 1"
        )
        use_case = LoadBidUseCase(self.model, Mock(), Mock(), Mock(), Mock())
        use_case.apply_prepared(self.bid_ref, PreparedBidLoad(self.read(), None))
        self.assertEqual(self.model.get_page("1").folder_uid, "10")
        self.assertIn(
            self.model.get_page("1"), self.model.current_bid.folders["10"].pages
        )

    def test_build_bid_sets_direct_and_nested_folder_ownership(self):
        bid = build_bid(self.info)
        self.assertEqual(bid.folders["10"].pages[0].folder_uid, "10")
        self.assertEqual(bid.folders["10"].subfolders["11"].pages[0].folder_uid, "11")
        self.assertIsNone(bid.pages_without_folder[0].folder_uid)

    def test_replace_pages_accepts_its_own_root_list_and_lazy_hierarchy(self):
        for lazy in (False, True):
            with self.subTest(lazy=lazy):
                page = Page(uid="1", name="Root")
                bid = Bid(uid="8", name="Bid", pages_without_folder=[page])
                pages = (
                    (p for p in bid.pages_without_folder)
                    if lazy
                    else bid.pages_without_folder
                )
                bid.replace_pages(pages)
                self.assertEqual(bid.pages_without_folder, [page])
                self.assertEqual(bid.page_count, 1)

    def test_missing_optional_folder_column_loads_unfoldered_pages(self):
        self.connection.execute("ALTER TABLE BidPages DROP COLUMN BidPageFolderUID")
        data = self.read()
        self.assertTrue(all(page.folder_uid is None for page in data.pages.values()))
        self.model.set_pages(data.pages)
        self.assertEqual(
            [p.uid for p in self.model.current_bid.pages_without_folder],
            ["4", "2", "1", "3"],
        )

    def test_remote_reassignment_to_root_and_deletion_replace_stale_pages(self):
        service = ProjectDataService(self.model)
        service.replace_remote_bid_families(self.bid_ref, self.read(), {"pages"})
        self.model.select_pages(["2"])
        old = self.model.get_page("2")
        self.connection.execute(
            "UPDATE BidPages SET BidPageFolderUID = 0 WHERE UID = 2"
        )
        self.connection.execute("DELETE FROM BidPages WHERE UID = 1")
        data = self.read()
        service.replace_remote_bid_families(self.bid_ref, data, {"pages"})
        self.assertIs(self.model.get_page("2"), data.pages["2"])
        self.assertIsNot(self.model.get_page("2"), old)
        self.assertEqual(self.model.get_selected_pages(), ["2"])
        self.assertIsNone(self.model.get_page("2").folder_uid)
        self.assertEqual(
            self.model.current_bid.folders["10"].subfolders["11"].pages, []
        )
        self.assertEqual(
            [p.uid for p in self.model.current_bid.pages_without_folder], ["2", "3"]
        )
        self.assertEqual(self.model.current_bid.page_count, 3)

    def test_other_bid_remote_pages_do_not_replace_active_graph(self):
        old = self.model.current_bid
        self.assertFalse(
            ProjectDataService(self.model).replace_remote_bid_families(
                BidRef("other-database", "8"), self.read(), {"pages"}
            )
        )
        self.assertIs(self.model.current_bid, old)
        self.assertEqual(
            old.folders["10"].subfolders["11"].pages[0].name, "Nested second"
        )

    def test_reader_rejects_duplicate_page_uids_before_projection(self):
        self.connection.execute(
            "INSERT INTO BidPages VALUES (1, 8, 'Duplicate', 99, 10)"
        )
        with self.assertRaisesRegex(RuntimeError, "duplicate UID 1"):
            self.read()

    def hierarchy_service(self):
        repository = FileProjectRepository(Mock())
        self.model.file_manager = FileManager(repository)
        self.model.file_manager.register_loaded_hierarchy(
            HierarchyFileEntry(file_path="database", orphan_bids=[self.info]), {}
        )
        self.model.set_pages(self.read().pages)
        return ProjectDataService(self.model)

    def test_hierarchy_refresh_binds_new_nested_folder_to_loaded_page(self):
        service = self.hierarchy_service()
        self.connection.execute(
            "UPDATE BidPages SET BidPageFolderUID = 12 WHERE UID = 1"
        )
        data = self.read()
        service.replace_remote_bid_families(self.bid_ref, data, {"pages"})
        self.model.select_pages(["1"])
        refreshed = deepcopy(self.info)
        refreshed.folders["10"].subfolders["12"] = HierarchyFolderInfo(
            name="New folder", pages=[HierarchyPageInfo(uid="1", name="Old metadata")]
        )
        refreshed.folders["10"].subfolders["11"].pages = [
            HierarchyPageInfo(uid="2", name="Nested first")
        ]
        service.replace_database_hierarchy(
            HierarchyFileEntry(file_path="database", orphan_bids=[refreshed]), {}
        )
        bid = service.get_bid(self.bid_ref)
        self.assertIn("12", bid.folders["10"].subfolders)
        self.assertEqual(bid.folders["10"].subfolders["12"].pages, [data.pages["1"]])
        self.assertIs(
            bid.folders["10"].subfolders["12"].pages[0], self.model.get_page("1")
        )
        self.assertEqual(self.model.get_page("1").name, "Nested second")
        self.assertEqual(self.model.get_selected_pages(), ["1"])

    def test_hierarchy_refresh_reparents_and_renames_existing_folder(self):
        service = self.hierarchy_service()
        page = self.model.get_page("1")
        refreshed = deepcopy(self.info)
        nested = refreshed.folders["10"].subfolders.pop("11")
        nested.name = "Moved to root"
        nested.parent_uid = None
        refreshed.folders["11"] = nested
        service.replace_database_hierarchy(
            HierarchyFileEntry(file_path="database", orphan_bids=[refreshed]), {}
        )
        bid = service.get_bid(self.bid_ref)
        self.assertIn("11", bid.folders)
        self.assertEqual(bid.folders["11"].name, "Moved to root")
        self.assertIs(bid.folders["11"].pages[1], page)

    def test_deleted_bid_is_not_returned_from_loaded_navigation_cache(self):
        service = self.hierarchy_service()
        service.replace_database_hierarchy(HierarchyFileEntry(file_path="database"), {})
        self.assertIsNone(service.get_bid(self.bid_ref))

    def test_hierarchy_refresh_updates_cached_bid_metadata_without_replacing_pages(
        self,
    ):
        service = self.hierarchy_service()
        bid = service.get_bid(self.bid_ref)
        page = self.model.get_page("1")
        self.model.select_pages(["1"])
        refreshed = deepcopy(self.info)
        refreshed.name = "Renamed remotely"
        refreshed.status_uid = "locked-status"
        refreshed.status = "Locked"
        refreshed.measure_base = 1
        refreshed.takeoff_increments = 2.5
        service.replace_database_hierarchy(
            HierarchyFileEntry(file_path="database", orphan_bids=[refreshed]), {}
        )
        current = service.get_bid(self.bid_ref)
        self.assertIs(current, bid)
        self.assertEqual(current.name, "Renamed remotely")
        self.assertEqual(current.status_uid, "locked-status")
        self.assertEqual(current.status, "Locked")
        self.assertEqual(current.measure_base, 1)
        self.assertEqual(current.takeoff_increments, 2.5)
        self.assertIs(self.model.get_page("1"), page)
        self.assertIs(current.folders["10"].subfolders["11"].pages[1], page)
        self.assertEqual(self.model.get_selected_pages(), ["1"])

    def test_other_database_hierarchy_does_not_rebuild_current_bid(self):
        service = self.hierarchy_service()
        bid = service.get_bid(self.bid_ref)
        folder = bid.folders["10"]
        service.replace_database_hierarchy(
            HierarchyFileEntry(
                file_path="other-database", orphan_bids=[deepcopy(self.info)]
            ),
            {},
        )
        self.assertIs(service.get_bid(self.bid_ref), bid)
        self.assertIs(bid.folders["10"], folder)

    def test_hydration_and_remote_refresh_retain_hierarchy_tie_order(self):
        self.connection.execute(
            "CREATE TABLE BidPageFolders (UID INTEGER, BidUID INTEGER, Name TEXT, ParentUID INTEGER)"
        )
        self.connection.executemany(
            "INSERT INTO BidPageFolders VALUES (?, 8, ?, ?)",
            [(10, "Parent", None), (11, "Nested", 10)],
        )
        self.connection.execute("UPDATE BidPages SET Sequence = 1")
        self.connection.executemany(
            "INSERT INTO BidPages VALUES (?, 8, ?, 1, ?)",
            [
                (7, "Alpha", None),
                (6, "Alpha", None),
                (9, "Nested first", 11),
                (8, "Nested first", 11),
            ],
        )
        schema = _SqliteHierarchySchema(self.connection)
        folders, root = HierarchyReaderMixin()._get_bid_folder_page_structure(
            _LimitedReadConnection(self.connection, schema), "8", schema
        )
        self.info = HierarchyBidInfo(
            uid="8", name="Bid", folders=folders, pages_without_folder=root
        )
        service = self.hierarchy_service()
        expected_root = [page.uid for page in root]
        expected_nested = [page.uid for page in folders["10"].subfolders["11"].pages]
        self.assertEqual(expected_root, ["6", "7", "3"])
        self.assertEqual(expected_nested, ["2", "8", "9", "1"])
        for refresh in (False, True):
            with self.subTest(remote=refresh):
                if refresh:
                    service.replace_remote_bid_families(
                        self.bid_ref, self.read(), {"pages"}
                    )
                bid = service.get_bid(self.bid_ref)
                self.assertEqual(
                    [page.uid for page in bid.pages_without_folder], expected_root
                )
                self.assertEqual(
                    [page.uid for page in bid.folders["10"].subfolders["11"].pages],
                    expected_nested,
                )
                for page in bid.pages_without_folder:
                    self.assertIs(self.model.get_page(page.uid), page)
