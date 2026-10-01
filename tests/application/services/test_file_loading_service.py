import unittest
from unittest.mock import Mock, call
from ost_visualizer.application.dtos.file_dto import FileLoadResultDto
from ost_visualizer.application.services.file_loading_service import FileLoadingService
from ost_visualizer.application.services.project_operations_service import (
    ProjectOperationsService,
)
from ost_visualizer.domain.entities.hierarchy_data import (
    HierarchyData,
    HierarchyFileEntry,
)
from ost_visualizer.domain.services.project_data_service import ProjectDataService


class FileLoadingServiceTests(unittest.TestCase):
    def setUp(self):
        self.operations = Mock(spec=ProjectOperationsService, last_error="")
        self.operations.load_file.return_value = True
        self.operations.reload_database.return_value = True
        self.operations.unload_file.return_value = True
        self.data = Mock(spec=ProjectDataService)
        self.service = FileLoadingService(self.operations, self.data)

    def test_empty_path_is_rejected_before_loading(self):
        result = self.service.load_file("")
        self.assertEqual(
            result, FileLoadResultDto(False, error_message="No file path provided")
        )
        self.assertEqual(self.operations.mock_calls, [])
        self.assertEqual(self.data.mock_calls, [])

    def test_failed_load_preserves_specific_error_and_has_a_fallback(self):
        self.operations.load_file.return_value = False
        for error, expected in (("denied", "denied"), ("", "Failed to load file")):
            with self.subTest(error=error):
                self.operations.last_error = error
                result = self.service.load_file("bid.mdb")
                self.assertEqual(
                    result, FileLoadResultDto(False, error_message=expected)
                )
        self.assertEqual(self.operations.mock_calls, [call.load_file("bid.mdb")] * 2)
        self.assertEqual(self.data.mock_calls, [])

    def test_successful_load_and_reload_report_the_correct_path(self):
        self.assertEqual(
            self.service.load_file("bid.mdb"), FileLoadResultDto(True, "bid.mdb")
        )
        self.data.get_current_file_path.return_value = "active.mdb"
        self.assertEqual(
            self.service.reload_database(), FileLoadResultDto(True, "active.mdb")
        )
        self.assertEqual(
            self.service.reload_database("other.mdb"),
            FileLoadResultDto(True, "other.mdb"),
        )
        self.assertEqual(
            self.operations.mock_calls,
            [
                call.load_file("bid.mdb"),
                call.reload_database(None),
                call.reload_database("other.mdb"),
            ],
        )
        self.data.get_current_file_path.assert_called_once_with()

    def test_failed_reload_and_unload_do_not_report_success(self):
        self.operations.reload_database.return_value = False
        self.operations.unload_file.return_value = False
        self.assertEqual(
            self.service.reload_database(),
            FileLoadResultDto(False, error_message="Failed to reload database"),
        )
        self.assertEqual(
            self.service.unload_file(),
            FileLoadResultDto(False, error_message="Failed to unload file"),
        )
        self.assertEqual(
            self.operations.mock_calls,
            [call.reload_database(None), call.unload_file(None)],
        )
        self.assertEqual(self.data.mock_calls, [])

    def test_unload_forwards_optional_target_and_returns_complete_success(self):
        for target in (None, "other.mdb"):
            with self.subTest(target=target):
                self.assertEqual(
                    self.service.unload_file(target), FileLoadResultDto(True)
                )
        self.assertEqual(
            self.operations.mock_calls,
            [call.unload_file(None), call.unload_file("other.mdb")],
        )
        self.assertEqual(self.data.mock_calls, [])

    def test_loaded_membership_comes_from_current_hierarchy(self):
        self.data.get_hierarchy.return_value = HierarchyData(
            loaded_files=[HierarchyFileEntry(file_path="bid.mdb")]
        )
        self.assertTrue(self.service.is_loaded("bid.mdb"))
        self.assertFalse(self.service.is_loaded("other.mdb"))
        self.data.get_hierarchy.return_value.loaded_files.clear()
        self.assertFalse(self.service.is_loaded("bid.mdb"))
        self.data.get_hierarchy.return_value = HierarchyData(
            loaded_files=[HierarchyFileEntry(file_path="other.mdb")]
        )
        self.assertTrue(self.service.is_loaded("other.mdb"))
        self.assertFalse(self.service.is_loaded("bid.mdb"))
        self.assertEqual(self.operations.mock_calls, [])
