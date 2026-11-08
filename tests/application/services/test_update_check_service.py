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


class UpdateCheckServiceVersionAndLogTests(unittest.TestCase):
    class _Logger:
        def __init__(self):
            self.records = []

        def warning(self, message, *args):
            self.records.append(("warning", message % args))

        def exception(self, message, *args):
            self.records.append(("exception", message % args))

    class _Client:
        def __init__(self, result=None, error=None):
            self.result, self.error = result, error

        def check_version(self):
            if self.error:
                raise self.error
            return self.result

    def service(self, result=None, error=None):
        from ost_visualizer.application.services.update_check_service import (
            UpdateCheckService,
        )

        logger = self._Logger()
        return UpdateCheckService(self._Client(result, error), logger), logger

    def test_version_ordering_compares_numeric_parts_and_pads_the_shorter_version(self):
        service, _ = self.service()
        newer = service._is_version_newer
        self.assertIs(newer("1.2.3", "1.2.2"), True)
        self.assertIs(newer("1.2.2", "1.2.3"), False)
        self.assertIs(newer("1.2.3", "1.2.3"), False)
        self.assertIs(newer("1.10", "1.9"), True)
        self.assertIs(newer("2", "1.9.9"), True)
        self.assertIs(newer("1.2", "1.2.0"), False)
        self.assertIs(newer("1.2.0.1", "1.2"), True)
        self.assertIs(newer("1.2", "1.2.0.1"), False)
        self.assertIs(newer("1.0", "1.0.0.0.0"), False)
        self.assertIs(newer("1.3", "1.2.9.9"), True)
        self.assertIs(newer("0.9", "1.0"), False)

    def test_unparseable_versions_are_not_newer_and_are_logged_with_both_values(self):
        service, logger = self.service()
        self.assertIs(service._is_version_newer("1.x", "1.0"), False)
        self.assertEqual(len(logger.records), 1)
        level, message = logger.records[0]
        self.assertEqual(level, "warning")
        self.assertTrue(
            message.startswith("Failed to parse version strings: 1.x vs 1.0 (")
        )
        service, logger = self.service()
        self.assertIs(service._is_version_newer(None, "1.0"), False)
        self.assertEqual(len(logger.records), 1)

    def test_server_problems_are_reported_with_distinct_log_messages_and_no_update(
        self,
    ):
        for result, error, expected in (
            (
                (False, {"latest_version": "9.9"}),
                None,
                ("warning", "Failed to check for updates: no response from server"),
            ),
            (
                (True, {}),
                None,
                ("warning", "Failed to check for updates: no response from server"),
            ),
            (
                (True, None),
                None,
                ("warning", "Failed to check for updates: no response from server"),
            ),
            (
                (True, {"latest_version": "  "}),
                None,
                ("warning", "Server response missing version information"),
            ),
            (
                (True, {"latest_version": 5}),
                None,
                ("warning", "Server response missing version information"),
            ),
            (
                None,
                RuntimeError("down"),
                ("exception", "Error checking for updates: down"),
            ),
        ):
            service, logger = self.service(result, error)
            with self.subTest(result=result, error=error):
                self.assertEqual(service.check_for_updates(), (False, None))
                self.assertEqual(logger.records, [expected])
        service, _ = self.service((False, {}))
        self.assertEqual(service.check_for_updates(), (False, None))

    def test_the_current_version_is_the_application_version(self):
        from ost_visualizer.application.dtos.application_info import APPLICATION_VERSION
        from ost_visualizer.application.services.update_check_service import (
            UpdateCheckService,
        )

        self.assertEqual(UpdateCheckService.CURRENT_VERSION, APPLICATION_VERSION)
        self.assertTrue(APPLICATION_VERSION)


class UpdateCheckServiceStrictnessTests(unittest.TestCase):
    class _Logger:
        def __init__(self):
            self.warnings = []

        def warning(self, message, *args):
            self.warnings.append(message % args)

        def exception(self, message, *args):
            raise AssertionError("unexpected exception log")

    def test_components_must_be_plain_integers_not_any_float_spelling(self):
        logger = self._Logger()
        service = UpdateCheckService(Mock(), logger)
        for server, current in (
            ("1e3", "1.0"),
            ("inf", "1.0"),
            ("nan", "1.0"),
            ("2e0", "1"),
            ("1.0", "1e3"),
        ):
            with self.subTest(server=server, current=current):
                before = len(logger.warnings)
                self.assertIs(service._is_version_newer(server, current), False)
                self.assertEqual(len(logger.warnings), before + 1)
                self.assertTrue(
                    logger.warnings[-1].startswith(
                        f"Failed to parse version strings: {server} vs {current} ("
                    )
                )
        self.assertIs(service._is_version_newer("1.5", "1.0"), True)

    def test_an_interrupt_from_the_client_is_not_swallowed_as_a_failed_check(self):
        client = Mock()
        client.check_version.side_effect = KeyboardInterrupt
        service = UpdateCheckService(client, Mock())
        with self.assertRaises(KeyboardInterrupt):
            service.check_for_updates()


class UpdateCheckServiceNegativeComponentTests(unittest.TestCase):
    def test_negative_components_are_accepted_characterisation(self):
        """CHARACTERISATION: production accepts negative components.
        ``int()`` parses "-1", so "1.-1" is a valid version that sorts below "1".
        The owner may prefer to reject negative components as unparseable; if so
        the server-side zero padding would become redundant (only then).
        """
        service = UpdateCheckService(Mock(), Mock())
        for server, current, expected in (
            ("1", "1.-1", True),
            ("0", "0.-1", True),
            ("1.-1", "1", False),
            ("1.0", "1.-1", True),
            ("1.-1", "1.-1", False),
            ("1.-2", "1.-1", False),
            ("1.-1", "1.-2", True),
        ):
            with self.subTest(server=server, current=current):
                self.assertIs(service._is_version_newer(server, current), expected)
