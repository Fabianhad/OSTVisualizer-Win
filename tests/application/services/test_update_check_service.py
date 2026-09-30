import unittest
from unittest.mock import Mock
from ost_visualizer.application.services.update_check_service import UpdateCheckService


class UpdateCheckServiceVersionTests(unittest.TestCase):
    def setUp(self):
        self.client = Mock()
        self.service = UpdateCheckService(self.client, Mock())

    def test_numeric_comparison_pads_missing_components_and_rejects_invalid_versions(
        self,
    ):
        for server, current, expected in (
            ("1.2.0", "1.2", False),
            ("1.10", "1.9", True),
            ("2.0", "1.99", True),
            ("1.9", "2", False),
            ("invalid", "1.2", False),
        ):
            with self.subTest(server=server, current=current):
                self.assertEqual(
                    self.service._is_version_newer(server, current), expected
                )

    def test_changelog_filters_malformed_sections_without_mutating_response(self):
        response = {"Added": [" item ", "", 3], "Broken": "not a list", 1: ["skip"]}
        self.assertEqual(
            self.service._normalize_changelog(response), {"added": ["item"]}
        )
        self.assertEqual(response["Added"], [" item ", "", 3])
        self.assertIsNone(self.service._normalize_changelog(["invalid"]))

    def test_api_failure_exception_and_missing_version_return_no_result(self):
        for response in ((False, {}), (True, {}), (True, {"latest_version": 4})):
            self.client.check_version.return_value = response
            self.assertEqual(self.service.check_for_updates(), (False, None))
        self.client.check_version.side_effect = OSError("offline")
        self.assertEqual(self.service.check_for_updates(), (False, None))

    def test_success_normalizes_strings_and_optional_fields(self):
        self.service.CURRENT_VERSION = "1.0"
        self.client.check_version.return_value = (
            True,
            {
                "latest_version": " 1.1 ",
                "download_url": " https://example.invalid/download ",
                "release_notes_url": 3,
            },
        )
        newer, result = self.service.check_for_updates()
        self.assertTrue(newer)
        self.assertEqual(result.current_version, "1.1")
        self.assertEqual(result.your_version, "1.0")
        self.assertEqual(result.download_url, "https://example.invalid/download")
        self.assertIsNone(result.release_notes_url)
