import logging
import unittest
from ost_visualizer.application.use_cases.project.reload_database_use_case import (
    ReloadDatabaseUseCase,
)
from ost_visualizer.domain.entities.file_results import FileLoadResult
from ost_visualizer.domain.entities.hierarchy_data import (
    HierarchyData,
    HierarchyFileEntry,
    HierarchyProjectInfo,
)
from ost_visualizer.domain.entities.identity_refs import BidRef


def _quiet_logger():
    logger = logging.getLogger("test.reload_database")
    logger.addHandler(logging.NullHandler())
    logger.propagate = False
    return logger


def _hierarchy(*file_paths):
    return HierarchyData(
        loaded_files=[
            HierarchyFileEntry(
                file_path=path,
                bid_projects={f"project-{path}": HierarchyProjectInfo(name=path)},
            )
            for path in file_paths
        ]
    )


class FakeModel:
    def __init__(
        self,
        current_bid_ref=BidRef(file_path="active.mdb", bid_uid="bid-1"),
        selected_pages=(),
        known_pages=(),
        bid_exists=True,
    ):
        self.current_bid_ref = current_bid_ref
        self.selected_pages = list(selected_pages)
        self.known_pages = set(known_pages)
        self.bid_exists_result = bid_exists
        self.bid_exists_calls = []
        self.clear_bid_count = 0
        self.reselected_pages = None
        self.projects = []
        self.cdn_types = {}
        self.hierarchy = None

    def set_hierarchy(self, hierarchy):
        self.hierarchy = hierarchy

    def clear_bid(self):
        self.clear_bid_count += 1
        self.current_bid_ref = None

    def get_selected_pages(self):
        return list(self.selected_pages)

    def bid_exists(self, bid_ref):
        self.bid_exists_calls.append(bid_ref)
        return self.bid_exists_result

    def get_page(self, page_uid):
        return object() if page_uid in self.known_pages else None

    def select_pages(self, page_uids):
        self.reselected_pages = list(page_uids)


class FakeRepo:
    def __init__(self):
        self.cdn_type_paths = []

    def get_cdn_types(self, file_path=None):
        self.cdn_type_paths.append(file_path)
        return {"cdn-for": file_path}


class FakeFileManager:
    def __init__(self, result, current_file_path="active.mdb"):
        self.current_file_path = current_file_path
        self.project_repository = FakeRepo()
        self.result = result
        self.reloads = []

    def reload_database(self, file_path, *, close_connections=True):
        self.reloads.append((file_path, close_connections))
        return self.result


class FakeLoadBid:
    def __init__(self, success=True):
        self.success = success
        self.calls = []

    def execute(self, bid_ref):
        self.calls.append(bid_ref)
        return self.success


def _use_case(model, file_manager, load_bid):
    return ReloadDatabaseUseCase(model, file_manager, load_bid, _quiet_logger())


class ReloadDatabaseUseCaseTests(unittest.TestCase):
    def test_reloading_inactive_database_preserves_active_bid_projection(self):
        class GuardedModel(FakeModel):
            def bid_exists(self, _bid_ref):
                raise AssertionError(
                    "inactive refresh must not retarget the active bid"
                )

        hierarchy = _hierarchy("active.mdb", "inactive.mdb")
        model = GuardedModel(selected_pages=["page-1"], known_pages=["page-1"])
        file_manager = FakeFileManager(
            FileLoadResult(success=True, hierarchy=hierarchy)
        )
        load_bid = FakeLoadBid()
        use_case = _use_case(model, file_manager, load_bid)
        self.assertTrue(use_case.execute("inactive.mdb"))
        self.assertEqual(model.current_bid_ref, BidRef("active.mdb", "bid-1"))
        self.assertEqual(model.clear_bid_count, 0)
        self.assertEqual(load_bid.calls, [])
        self.assertIsNone(model.reselected_pages)
        self.assertEqual(file_manager.reloads, [("inactive.mdb", True)])
        self.assertEqual(file_manager.project_repository.cdn_type_paths, ["active.mdb"])
        self.assertEqual(model.cdn_types, {"cdn-for": "active.mdb"})
        self.assertIs(model.hierarchy, hierarchy)
        self.assertEqual(
            [project.file_path for project in model.projects],
            ["active.mdb", "inactive.mdb"],
        )

    def test_post_write_reload_preserves_current_connection_incarnation(self):
        hierarchy = _hierarchy("active.mdb")
        model = FakeModel(
            selected_pages=["page-1", "page-gone"], known_pages=["page-1"]
        )
        file_manager = FakeFileManager(
            FileLoadResult(success=True, hierarchy=hierarchy)
        )
        load_bid = FakeLoadBid()
        use_case = _use_case(model, file_manager, load_bid)
        self.assertTrue(use_case.execute_after_write("active.mdb"))
        self.assertEqual(file_manager.reloads, [("active.mdb", False)])
        self.assertEqual(model.bid_exists_calls, [BidRef("active.mdb", "bid-1")])
        self.assertEqual(load_bid.calls, [BidRef("active.mdb", "bid-1")])
        self.assertEqual(model.clear_bid_count, 0)
        self.assertEqual(model.reselected_pages, ["page-1"])
        self.assertIs(model.hierarchy, hierarchy)

    def test_execute_without_path_reloads_current_file_and_closes_connections(self):
        model = FakeModel()
        file_manager = FakeFileManager(
            FileLoadResult(success=True, hierarchy=_hierarchy("active.mdb")),
            current_file_path="active.mdb",
        )
        self.assertTrue(_use_case(model, file_manager, FakeLoadBid()).execute())
        self.assertEqual(file_manager.reloads, [("active.mdb", True)])

    def test_reload_without_any_target_path_fails_without_touching_file_manager(self):
        model = FakeModel()
        file_manager = FakeFileManager(
            FileLoadResult(success=True, hierarchy=_hierarchy("active.mdb")),
            current_file_path=None,
        )
        self.assertFalse(_use_case(model, file_manager, FakeLoadBid()).execute())
        self.assertEqual(file_manager.reloads, [])
        self.assertIsNone(model.hierarchy)

    def test_same_file_with_unnormalized_bid_path_reloads_bid_at_target_path(self):
        model = FakeModel(
            current_bid_ref=BidRef(file_path="sub/../active.mdb", bid_uid="bid-1")
        )
        file_manager = FakeFileManager(
            FileLoadResult(success=True, hierarchy=_hierarchy("active.mdb"))
        )
        load_bid = FakeLoadBid()
        self.assertTrue(_use_case(model, file_manager, load_bid).execute("active.mdb"))
        self.assertEqual(load_bid.calls, [BidRef("active.mdb", "bid-1")])
        self.assertEqual(
            file_manager.project_repository.cdn_type_paths, ["sub/../active.mdb"]
        )

    def test_reloaded_database_without_active_bid_clears_bid(self):
        model = FakeModel(bid_exists=False)
        file_manager = FakeFileManager(
            FileLoadResult(success=True, hierarchy=_hierarchy("active.mdb"))
        )
        load_bid = FakeLoadBid()
        self.assertTrue(_use_case(model, file_manager, load_bid).execute("active.mdb"))
        self.assertEqual(model.clear_bid_count, 1)
        self.assertIsNone(model.current_bid_ref)
        self.assertEqual(load_bid.calls, [])

    def test_failed_reload_leaves_model_untouched(self):
        model = FakeModel()
        file_manager = FakeFileManager(
            FileLoadResult(success=False, error_message="locked")
        )
        load_bid = FakeLoadBid()
        self.assertFalse(_use_case(model, file_manager, load_bid).execute("active.mdb"))
        self.assertIsNone(model.hierarchy)
        self.assertEqual(model.projects, [])
        self.assertEqual(model.cdn_types, {})
        self.assertEqual(model.clear_bid_count, 0)
        self.assertEqual(model.current_bid_ref, BidRef("active.mdb", "bid-1"))
        self.assertEqual(load_bid.calls, [])

    def test_failed_bid_reload_is_reported_without_reselecting_pages(self):
        model = FakeModel(selected_pages=["page-1"], known_pages=["page-1"])
        file_manager = FakeFileManager(
            FileLoadResult(success=True, hierarchy=_hierarchy("active.mdb"))
        )
        load_bid = FakeLoadBid(success=False)
        self.assertFalse(_use_case(model, file_manager, load_bid).execute("active.mdb"))
        self.assertEqual(load_bid.calls, [BidRef("active.mdb", "bid-1")])
        self.assertIsNone(model.reselected_pages)
        self.assertEqual(model.clear_bid_count, 0)
