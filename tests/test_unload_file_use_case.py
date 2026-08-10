import unittest
from ost_visualizer.application.use_cases.project.unload_file_use_case import (
    UnloadFileUseCase,
)
from ost_visualizer.domain.entities.hierarchy_data import (
    HierarchyData,
    HierarchyFileEntry,
)
from ost_visualizer.domain.entities.file_results import FileLoadResult
from ost_visualizer.domain.entities.identity_refs import BidRef
from ost_visualizer.application.use_cases.project.reload_database_use_case import (
    ReloadDatabaseUseCase,
)


class FakeModel:
    def __init__(self):
        self.current_bid_ref = BidRef(file_path="active.mdb", bid_uid="bid-1")
        self.clear_bid_count = 0
        self.projects = []
        self.cdn_types = {}
        self.hierarchy = None

    def set_hierarchy(self, hierarchy):
        self.hierarchy = hierarchy

    def clear_bid(self):
        self.clear_bid_count += 1
        self.current_bid_ref = None


class FakeRepo:
    def __init__(self):
        self.current_hierarchy_data = HierarchyData(
            loaded_files=[HierarchyFileEntry(file_path="active.mdb")]
        )

    @property
    def active_file_path(self):
        return self.current_hierarchy_data.loaded_files[0].file_path

    def get_cdn_types(self, _file_path=None):
        return {}


class FakeFileManager:
    def __init__(self):
        self.current_file_path = "active.mdb"
        self.project_repository = FakeRepo()
        self.unloaded = []

    def unload_file(self, file_path=None):
        self.unloaded.append(file_path)
        return True


class FakeDataService:
    def __init__(self):
        self.reset_count = 0

    def reset(self):
        self.reset_count += 1


class UnloadFileUseCaseTests(unittest.TestCase):
    def test_unloading_inactive_file_keeps_current_bid_model(self):
        model = FakeModel()
        file_manager = FakeFileManager()
        data_service = FakeDataService()
        use_case = UnloadFileUseCase(model, data_service, file_manager)
        self.assertTrue(use_case.execute("inactive.mdb"))
        self.assertEqual(model.clear_bid_count, 0)
        self.assertEqual(model.current_bid_ref.file_path, "active.mdb")
        self.assertEqual(file_manager.unloaded, ["inactive.mdb"])

    def test_unloading_active_file_clears_current_bid_model(self):
        model = FakeModel()
        file_manager = FakeFileManager()
        data_service = FakeDataService()
        use_case = UnloadFileUseCase(model, data_service, file_manager)
        self.assertTrue(use_case.execute("active.mdb"))
        self.assertEqual(model.clear_bid_count, 1)
        self.assertIsNone(model.current_bid_ref)


class ReloadDatabaseUseCaseTests(unittest.TestCase):
    def test_reloading_inactive_database_preserves_active_bid_projection(self):
        class ReloadModel(FakeModel):
            def get_selected_pages(self):
                return ["page-1"]

            def bid_exists(self, _bid_ref):
                raise AssertionError(
                    "inactive refresh must not retarget the active bid"
                )

        class ReloadRepo(FakeRepo):
            def get_cdn_types(self, file_path=None):
                self.cdn_type_path = file_path
                return {"active": object()}

        class ReloadFileManager:
            def __init__(self):
                self.current_file_path = "active.mdb"
                self.project_repository = ReloadRepo()

            def reload_database(self, file_path):
                self.reloaded = file_path
                return FileLoadResult(
                    success=True,
                    hierarchy=HierarchyData(
                        loaded_files=[
                            HierarchyFileEntry(file_path="active.mdb"),
                            HierarchyFileEntry(file_path="inactive.mdb"),
                        ]
                    ),
                )

        class LoadBid:
            def __init__(self):
                self.calls = []

            def execute(self, bid_ref):
                self.calls.append(bid_ref)
                return True

        model = ReloadModel()
        file_manager = ReloadFileManager()
        load_bid = LoadBid()
        use_case = ReloadDatabaseUseCase(model, file_manager, load_bid)
        self.assertTrue(use_case.execute("inactive.mdb"))
        self.assertEqual(model.current_bid_ref, BidRef("active.mdb", "bid-1"))
        self.assertEqual(model.clear_bid_count, 0)
        self.assertEqual(load_bid.calls, [])
        self.assertEqual(file_manager.reloaded, "inactive.mdb")
        self.assertEqual(file_manager.project_repository.cdn_type_path, "active.mdb")


if __name__ == "__main__":
    unittest.main()
