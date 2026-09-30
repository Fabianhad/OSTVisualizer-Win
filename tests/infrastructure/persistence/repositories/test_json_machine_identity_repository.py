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

    def test_record_disappearing_after_competing_create_is_failure(self):
        with patch.object(self.repository, "_save_json_if_absent", return_value=False):
            with self.assertRaisesRegex(OSError, "disappeared during initialization"):
                self.repository.create_if_absent(self.identity)
        self.assertFalse(self.path.exists())
