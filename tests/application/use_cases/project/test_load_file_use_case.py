import logging
import unittest
from ost_visualizer.application.use_cases.project.load_file_use_case import (
    LoadFileUseCase,
)
from ost_visualizer.domain.aggregates.ost_aggregate import OstAggregate
from ost_visualizer.domain.entities.cdn_type import CdnType
from ost_visualizer.domain.entities.file_results import FileLoadResult
from ost_visualizer.domain.entities.hierarchy_data import (
    HierarchyBidInfo,
    HierarchyData,
    HierarchyFileEntry,
    HierarchyProjectInfo,
)
from PySide6 import QtWidgets


class _DataService:
    def __init__(self):
        self.reset_count = 0

    def reset(self):
        self.reset_count += 1


class _FileManager:
    def __init__(self, result):
        self.result = result
        self.locators = []

    def load_file(self, locator):
        self.locators.append(locator)
        return self.result


def _logger():
    logger = logging.getLogger("test.startup.load")
    logger.addHandler(logging.NullHandler())
    logger.propagate = False
    return logger


class StartupLoadFileFailureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def _loaded_model(self):
        model = OstAggregate(None)
        old_hierarchy = HierarchyData(
            [
                HierarchyFileEntry(
                    file_path="old.mdb",
                    bid_projects={
                        "p-old": HierarchyProjectInfo(
                            name="Old", bids=[HierarchyBidInfo(uid="b-old")]
                        )
                    },
                )
            ]
        )
        model.set_hierarchy(old_hierarchy)
        model.projects = ["access-project"]
        model.cdn_types = {"t-old": CdnType(uid="t-old")}
        model.bid_conditions = {"c-old": object()}
        model.bid_takeoffs = ["takeoff-old"]
        model.bid_takeoff_extras = {"x": {"k": 1}}
        model.set_pages({"page-old": object()})
        model.select_pages(["page-old"])
        return model, old_hierarchy

    def test_failed_database_load_preserves_existing_access_projection(self):
        data_service = _DataService()
        model, old_hierarchy = self._loaded_model()
        old_cdn_types = dict(model.cdn_types)
        old_conditions = dict(model.bid_conditions)
        file_manager = _FileManager(
            FileLoadResult(success=False, error_message="server unavailable")
        )
        use_case = LoadFileUseCase(model, data_service, file_manager, _logger())
        self.assertFalse(use_case.execute("sql-database-id"))
        self.assertEqual(file_manager.locators, ["sql-database-id"])
        self.assertEqual(use_case.last_error, "server unavailable")
        self.assertEqual(data_service.reset_count, 0)
        self.assertEqual(model.projects, ["access-project"])
        self.assertIs(model.get_hierarchy_data(), old_hierarchy)
        self.assertEqual(model.cdn_types, old_cdn_types)
        self.assertEqual(model.bid_conditions, old_conditions)
        self.assertEqual(model.bid_takeoffs, ["takeoff-old"])
        self.assertEqual(model.bid_takeoff_extras, {"x": {"k": 1}})
        self.assertEqual(model.get_selected_pages(), ["page-old"])

    def test_failed_load_without_message_reports_default_error_and_success_clears_it(
        self,
    ):
        data_service = _DataService()
        model, _old_hierarchy = self._loaded_model()
        file_manager = _FileManager(FileLoadResult(success=False))
        use_case = LoadFileUseCase(model, data_service, file_manager, _logger())
        self.assertFalse(use_case.execute("missing.mdb"))
        self.assertEqual(use_case.last_error, "Failed to load file")
        new_hierarchy = HierarchyData(
            [
                HierarchyFileEntry(
                    file_path="new.mdb",
                    bid_projects={
                        "p-new": HierarchyProjectInfo(
                            name="New", bids=[HierarchyBidInfo(uid="b-new")]
                        )
                    },
                )
            ]
        )
        new_cdn_types = {"t-new": CdnType(uid="t-new")}
        file_manager.result = FileLoadResult(
            success=True, hierarchy=new_hierarchy, cdn_types=new_cdn_types
        )
        self.assertTrue(use_case.execute("new.mdb"))
        self.assertIsNone(use_case.last_error)
        self.assertEqual(data_service.reset_count, 1)
        self.assertIs(model.get_hierarchy_data(), new_hierarchy)
        self.assertEqual(model.cdn_types, new_cdn_types)
        self.assertEqual(
            [(project.uid, project.file_path) for project in model.projects],
            [("p-new", "new.mdb")],
        )
        self.assertEqual(model.bid_conditions, {})
        self.assertEqual(model.bid_takeoffs, [])
        self.assertEqual(model.bid_takeoff_extras, {})
        self.assertEqual(model.get_selected_pages(), [])
