"""Atomic replacement, first-writer ownership, and read failures."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from ost_visualizer.infrastructure.persistence.repositories.json_repository_base import (
    JsonRepositoryBase,
)


class JsonRepositoryBaseTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / "nested" / "state.json"
        self.repository = JsonRepositoryBase(self.path, "test state")

    def test_save_replaces_complete_record_and_removes_temporary_files(self):
        self.repository._save_json({"old": [1, 2]})
        self.repository._save_json({"new": "café"})
        self.assertEqual(self.repository._load_json(), {"new": "café"})
        self.assertEqual(list(self.path.parent.iterdir()), [self.path])

    def test_failed_replace_preserves_prior_record_and_removes_temporary_file(self):
        self.repository._save_json({"committed": True})
        with patch.object(Path, "replace", side_effect=PermissionError("locked")):
            with self.assertLogs(self.repository.logger, level="ERROR") as logs:
                with self.assertRaises(PermissionError):
                    self.repository._save_json({"committed": False})
        self.assertEqual(len(logs.records), 1)
        self.assertIn("Failed to save test state", logs.records[0].getMessage())
        self.assertEqual(self.repository._load_json(), {"committed": True})
        self.assertEqual(list(self.path.parent.iterdir()), [self.path])

    def test_create_if_absent_preserves_first_writer(self):
        self.assertTrue(self.repository._save_json_if_absent({"owner": "first"}))
        self.assertFalse(self.repository._save_json_if_absent({"owner": "second"}))
        self.assertEqual(self.repository._load_json(), {"owner": "first"})
        self.assertEqual(list(self.path.parent.iterdir()), [self.path])

    def test_failed_create_if_absent_leaves_no_record_or_temporary_file(self):
        with patch("os.link", side_effect=PermissionError("denied")):
            with self.assertLogs(self.repository.logger, level="ERROR") as logs:
                with self.assertRaises(PermissionError):
                    self.repository._save_json_if_absent({"owner": "first"})
        self.assertEqual(len(logs.records), 1)
        self.assertIn("Failed to initialize test state", logs.records[0].getMessage())
        self.assertEqual(list(self.path.parent.iterdir()), [])
        self.assertTrue(self.repository._save_json_if_absent({"owner": "retry"}))
        self.assertEqual(self.repository._load_json(), {"owner": "retry"})

    def test_missing_and_malformed_records_have_distinct_failures(self):
        with self.assertRaises(FileNotFoundError):
            self.repository._load_json()
        self.path.parent.mkdir()
        self.path.write_text("{broken", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "Invalid JSON") as raised:
            self.repository._load_json()
        self.assertNotIsInstance(raised.exception, FileNotFoundError)
        self.assertIsInstance(raised.exception.__cause__, json.JSONDecodeError)

    def test_unreadable_record_is_reported_as_read_failure_not_missing(self):
        self.path.mkdir(parents=True)
        with self.assertRaisesRegex(OSError, "Unable to read test state") as raised:
            self.repository._load_json()
        self.assertNotIsInstance(raised.exception, FileNotFoundError)
        self.assertIsInstance(raised.exception.__cause__, OSError)
