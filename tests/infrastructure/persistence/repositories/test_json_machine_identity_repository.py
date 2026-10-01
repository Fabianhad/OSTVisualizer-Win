"""Pinned identity persistence must never silently generate a replacement."""

import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch
from ost_visualizer.domain.services.hardware_identity import (
    HardwareIdentitySource,
    MachineIdentity,
)
from ost_visualizer.infrastructure.persistence.repositories.json_machine_identity_repository import (
    JsonMachineIdentityRepository,
)


class JsonMachineIdentityRepositoryTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / "identity.json"
        self.repository = JsonMachineIdentityRepository(self.path)
        self.identity = MachineIdentity.create(
            HardwareIdentitySource.INSTALLATION_UUID,
            uuid.UUID("12345678-1234-4567-8901-123456789abc"),
        )

    def test_initial_creation_reload_and_competing_creation_keep_pinned_identity(self):
        self.assertIsNone(self.repository.load())
        self.assertIs(self.repository.create_if_absent(self.identity), self.identity)
        replacement = MachineIdentity.create(
            HardwareIdentitySource.SMBIOS_SYSTEM_UUID,
            uuid.UUID("87654321-4321-4765-8901-cba987654321"),
        )
        reopened = JsonMachineIdentityRepository(self.path)
        self.assertEqual(reopened.load(), self.identity)
        self.assertEqual(reopened.create_if_absent(replacement), self.identity)
        self.assertEqual(reopened.load(), self.identity)

    def test_missing_previously_initialized_record_is_not_first_run(self):
        self.repository.create_if_absent(self.identity)
        self.path.unlink()
        with self.assertRaisesRegex(
            OSError, "pinned machine identity record is missing"
        ):
            self.repository.load()

    def test_concurrent_creation_after_missing_read_loads_the_pinned_identity(self):
        load_json = self.repository._load_json
        competing_repository = JsonMachineIdentityRepository(self.path)
        persisted = []

        def read_while_another_process_initializes():
            try:
                return load_json()
            except FileNotFoundError:
                # Real first read observed no file. The other startup now commits
                # both files before this reader can inspect the initialized marker.
                competing_repository.create_if_absent(self.identity)
                persisted.append(self.path.read_bytes())
                raise

        with patch.object(
            self.repository,
            "_load_json",
            side_effect=read_while_another_process_initializes,
        ) as reads:
            self.assertEqual(self.repository.load(), self.identity)
        self.assertEqual(reads.call_count, 2)
        self.assertEqual(persisted, [self.path.read_bytes()])
        self.assertEqual(competing_repository.load(), self.identity)

    def test_record_disappearing_after_competing_create_is_failure(self):
        with patch.object(self.repository, "_save_json_if_absent", return_value=False):
            with self.assertRaisesRegex(OSError, "disappeared during initialization"):
                self.repository.create_if_absent(self.identity)
        self.assertFalse(self.path.exists())

    def test_marked_record_reread_preserves_failure_without_reinitializing(self):
        self.repository.create_if_absent(self.identity)
        before = self.path.read_bytes()
        for error in (
            FileNotFoundError("still absent"),
            ValueError("invalid identity"),
            PermissionError("read denied"),
        ):
            with self.subTest(error=type(error).__name__), patch.object(
                self.repository, "_load_json", side_effect=[FileNotFoundError(), error]
            ) as reads:
                expected_type = (
                    OSError if isinstance(error, FileNotFoundError) else type(error)
                )
                with self.assertRaises(expected_type) as raised:
                    self.repository.load()
                if isinstance(error, FileNotFoundError):
                    self.assertIn(
                        "pinned machine identity record is missing",
                        str(raised.exception),
                    )
                    self.assertIs(raised.exception.__cause__, error)
                else:
                    self.assertIs(raised.exception, error)
                self.assertEqual(reads.call_count, 2)
                self.assertEqual(self.path.read_bytes(), before)
