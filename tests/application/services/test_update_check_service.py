import unittest
from copy import deepcopy
from unittest.mock import Mock
from ost_visualizer.application.services.update_check_service import UpdateCheckService
from ost_visualizer.domain.entities.version_info import VersionInfo


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
            ("1.2", "1.2.0.0", False),
            ("1.2.0.1", "1.2", True),
            ("1.2", "invalid", False),
            ("1..2", "1.2", False),
            (None, "1.2", False),
        ):
            with self.subTest(server=server, current=current):
                self.assertEqual(
                    self.service._is_version_newer(server, current), expected
                )

    def test_changelog_filters_malformed_sections_without_mutating_response(self):
        response = {"Added": [" item ", "", 3], "Broken": "not a list", 1: ["skip"]}
        original = deepcopy(response)
        self.assertEqual(
            self.service._normalize_changelog(response), {"added": ["item"]}
        )
        self.assertEqual(response, original)
        self.assertIsNone(self.service._normalize_changelog(["invalid"]))
        self.assertIsNone(self.service._normalize_changelog({"Added": ["", 3]}))

    def test_api_failure_exception_and_missing_version_return_no_result(self):
        for response in (
            (False, {}),
            (True, {}),
            (True, {"latest_version": 4}),
            (True, {"latest_version": "   "}),
        ):
            self.client.check_version.return_value = response
            self.assertEqual(self.service.check_for_updates(), (False, None))
        self.client.check_version.side_effect = OSError("offline")
        self.assertEqual(self.service.check_for_updates(), (False, None))
        self.assertEqual(self.client.check_version.call_count, 5)

    def test_success_normalizes_strings_and_optional_fields(self):
        self.service.CURRENT_VERSION = "1.0"
        self.client.check_version.return_value = (
            True,
            {
                "latest_version": " 1.1 ",
                "download_url": " https://example.invalid/download ",
                "release_notes_url": 3,
                "release_url": " https://example.invalid/release ",
                "release_date": " 2026-09-30 ",
                "changelog": {"Fixed": [" corrected ", ""]},
            },
        )
        newer, result = self.service.check_for_updates()
        self.assertTrue(newer)
        self.assertEqual(
            result,
            VersionInfo(
                current_version="1.1",
                your_version="1.0",
                is_newer=True,
                download_url="https://example.invalid/download",
                release_url="https://example.invalid/release",
                release_date="2026-09-30",
                changelog={"fixed": ["corrected"]},
                release_notes_url=None,
            ),
        )
        self.client.check_version.assert_called_once_with()

    def test_successful_equal_or_older_check_preserves_release_information(self):
        self.service.CURRENT_VERSION = "2.0"
        for version in ("2", "1.9"):
            with self.subTest(version=version):
                self.client.check_version.return_value = (
                    True,
                    {
                        "latest_version": version,
                        "release_notes_url": " https://example.invalid/notes ",
                    },
                )
                self.assertEqual(
                    self.service.check_for_updates(),
                    (
                        False,
                        VersionInfo(
                            current_version=version,
                            your_version="2.0",
                            is_newer=False,
                            release_notes_url="https://example.invalid/notes",
                        ),
                    ),
                )
