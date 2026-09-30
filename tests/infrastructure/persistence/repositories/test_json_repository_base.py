"""Atomic replacement, first-writer ownership, and read failures."""

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
            with self.assertRaises(PermissionError):
                self.repository._save_json({"committed": False})
        self.assertEqual(self.repository._load_json(), {"committed": True})
        self.assertEqual(list(self.path.parent.iterdir()), [self.path])

    def test_create_if_absent_preserves_first_writer(self):
        self.assertTrue(self.repository._save_json_if_absent({"owner": "first"}))
        self.assertFalse(self.repository._save_json_if_absent({"owner": "second"}))
        self.assertEqual(self.repository._load_json(), {"owner": "first"})
        self.assertEqual(list(self.path.parent.iterdir()), [self.path])

    def test_missing_and_malformed_records_have_distinct_failures(self):
        with self.assertRaises(FileNotFoundError):
            self.repository._load_json()
        self.path.parent.mkdir()
        self.path.write_text("{broken", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "Invalid JSON"):
            self.repository._load_json()
