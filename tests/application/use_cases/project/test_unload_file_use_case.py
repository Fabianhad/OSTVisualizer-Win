import unittest
from ost_visualizer.application.use_cases.project.unload_file_use_case import (
    UnloadFileUseCase,
)
from ost_visualizer.domain.entities.hierarchy_data import (
    HierarchyData,
    HierarchyFileEntry,
    HierarchyProjectInfo,
)
from ost_visualizer.domain.entities.identity_refs import BidRef


def _file_entry(file_path):
    return HierarchyFileEntry(
        file_path=file_path,
        bid_projects={f"project-{file_path}": HierarchyProjectInfo(name=file_path)},
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
    def __init__(self, file_paths):
        self.current_hierarchy_data = HierarchyData(
            loaded_files=[_file_entry(path) for path in file_paths]
        )
        self.cdn_type_paths = []

    @property
    def active_file_path(self):
        return self.current_hierarchy_data.loaded_files[0].file_path

    def get_cdn_types(self, file_path=None):
        self.cdn_type_paths.append(file_path)
        return {"cdn-for": file_path}

    def remove(self, file_path):
        self.current_hierarchy_data = HierarchyData(
            loaded_files=[
                entry
                for entry in self.current_hierarchy_data.loaded_files
                if entry.file_path != file_path
            ]
        )


class FakeFileManager:
    def __init__(self, file_paths=("active.mdb", "inactive.mdb"), succeed=True):
        self.project_repository = FakeRepo(file_paths)
        self.current_file_path = file_paths[0] if file_paths else None
        self.succeed = succeed
        self.unloaded = []

    def unload_file(self, file_path=None):
        self.unloaded.append(file_path)
        if not self.succeed:
            return False
        repo = self.project_repository
        repo.remove(file_path or self.current_file_path)
        loaded = repo.current_hierarchy_data.loaded_files
        self.current_file_path = loaded[0].file_path if loaded else None
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
        self.assertEqual(model.current_bid_ref, BidRef("active.mdb", "bid-1"))
        self.assertEqual(file_manager.unloaded, ["inactive.mdb"])
        self.assertEqual(data_service.reset_count, 0)
        repo = file_manager.project_repository
        self.assertIs(model.hierarchy, repo.current_hierarchy_data)
        self.assertEqual(
            [project.file_path for project in model.projects], ["active.mdb"]
        )
        self.assertEqual(repo.cdn_type_paths, ["active.mdb"])
        self.assertEqual(model.cdn_types, {"cdn-for": "active.mdb"})

    def test_unloading_active_file_clears_current_bid_model(self):
        model = FakeModel()
        file_manager = FakeFileManager()
        data_service = FakeDataService()
        use_case = UnloadFileUseCase(model, data_service, file_manager)
        self.assertTrue(use_case.execute("active.mdb"))
        self.assertEqual(model.clear_bid_count, 1)
        self.assertIsNone(model.current_bid_ref)
        self.assertEqual(file_manager.unloaded, ["active.mdb"])
        self.assertEqual(data_service.reset_count, 0)
        repo = file_manager.project_repository
        self.assertIs(model.hierarchy, repo.current_hierarchy_data)
        self.assertEqual(
            [project.file_path for project in model.projects], ["inactive.mdb"]
        )
        self.assertEqual(repo.cdn_type_paths, ["inactive.mdb"])
        self.assertEqual(model.cdn_types, {"cdn-for": "inactive.mdb"})

    def test_unloading_current_file_without_path_or_with_unnormalized_path_clears_bid(
        self,
    ):
        for requested_path in (None, "sub/../active.mdb"):
            with self.subTest(requested_path=requested_path):
                model = FakeModel()
                file_manager = FakeFileManager()
                use_case = UnloadFileUseCase(model, FakeDataService(), file_manager)
                self.assertTrue(use_case.execute(requested_path))
                self.assertEqual(file_manager.unloaded, [requested_path])
                self.assertEqual(model.clear_bid_count, 1)
                self.assertIsNone(model.current_bid_ref)

    def test_unloading_last_file_resets_data_service_without_rebuilding_model(self):
        model = FakeModel()
        file_manager = FakeFileManager(file_paths=("active.mdb",))
        data_service = FakeDataService()
        use_case = UnloadFileUseCase(model, data_service, file_manager)
        self.assertTrue(use_case.execute("active.mdb"))
        self.assertEqual(data_service.reset_count, 1)
        self.assertIsNone(model.hierarchy)
        self.assertEqual(model.projects, [])
        self.assertEqual(file_manager.project_repository.cdn_type_paths, [])

    def test_failed_or_unneeded_unload_leaves_model_untouched(self):
        model = FakeModel()
        file_manager = FakeFileManager(succeed=False)
        data_service = FakeDataService()
        use_case = UnloadFileUseCase(model, data_service, file_manager)
        self.assertFalse(use_case.execute("active.mdb"))
        self.assertEqual(file_manager.unloaded, ["active.mdb"])
        self.assertEqual(model.clear_bid_count, 0)
        self.assertEqual(model.current_bid_ref, BidRef("active.mdb", "bid-1"))
        self.assertIsNone(model.hierarchy)
        self.assertEqual(data_service.reset_count, 0)
        empty_manager = FakeFileManager(file_paths=())
        use_case = UnloadFileUseCase(model, data_service, empty_manager)
        self.assertFalse(use_case.execute("active.mdb"))
        self.assertEqual(empty_manager.unloaded, [])
        self.assertEqual(model.clear_bid_count, 0)
        self.assertEqual(data_service.reset_count, 0)
