import unittest
from types import SimpleNamespace
from unittest.mock import Mock
from ost_visualizer.application.services.file_loading_service import FileLoadingService


class FileLoadingServiceTests(unittest.TestCase):
    def setUp(self):
        self.operations = Mock(last_error="")
        self.data = Mock()
        self.service = FileLoadingService(self.operations, self.data)

    def test_empty_path_is_rejected_before_loading(self):
        result = self.service.load_file("")
        self.assertFalse(result.success)
        self.assertEqual(result.error_message, "No file path provided")
        self.operations.load_file.assert_not_called()

    def test_failed_load_preserves_specific_error_and_has_a_fallback(self):
        self.operations.load_file.return_value = False
        for error, expected in (("denied", "denied"), ("", "Failed to load file")):
            self.operations.last_error = error
            result = self.service.load_file("bid.mdb")
            self.assertFalse(result.success)
            self.assertEqual(result.error_message, expected)

    def test_successful_load_and_reload_report_the_correct_path(self):
        self.assertEqual(self.service.load_file("bid.mdb").file_path, "bid.mdb")
        self.data.get_current_file_path.return_value = "active.mdb"
        self.assertEqual(self.service.reload_database().file_path, "active.mdb")
        self.assertEqual(
            self.service.reload_database("other.mdb").file_path, "other.mdb"
        )
        self.operations.reload_database.assert_called_with("other.mdb")

    def test_failed_reload_and_unload_do_not_report_success(self):
        self.operations.reload_database.return_value = False
        self.operations.unload_file.return_value = False
        self.assertFalse(self.service.reload_database().success)
        self.assertFalse(self.service.unload_file().success)
        self.data.get_current_file_path.assert_not_called()

    def test_loaded_membership_comes_from_current_hierarchy(self):
        self.data.get_hierarchy.return_value = SimpleNamespace(
            loaded_files=[SimpleNamespace(file_path="bid.mdb")]
        )
        self.assertTrue(self.service.is_loaded("bid.mdb"))
        self.assertFalse(self.service.is_loaded("other.mdb"))
        self.data.get_hierarchy.return_value.loaded_files.clear()
        self.assertFalse(self.service.is_loaded("bid.mdb"))
