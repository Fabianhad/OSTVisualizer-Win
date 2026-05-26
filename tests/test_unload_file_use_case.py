import unittest
from ost_visualizer.application.use_cases.project.unload_file_use_case import (
    UnloadFileUseCase,
)
from ost_visualizer.domain.entities.hierarchy_data import (
    HierarchyData,
    HierarchyFileEntry,
)
from ost_visualizer.domain.entities.identity_refs import BidRef


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

    def get_merged_cdn_types(self):
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


if __name__ == "__main__":
    unittest.main()
