import ctypes
import os
import secrets
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from ost_visualizer.infrastructure.sql.credential_store import (
    _CREDENTIALW,
    WindowsCredentialStore,
)
from tests.helpers.sql.database_foundation_support import (
    _FakeApiFunction as _database_foundation_support__FakeApiFunction,
    _FakeCredentialApi as _database_foundation_support__FakeCredentialApi,
)


class CredentialStoreDatabaseDescriptorTests(unittest.TestCase):
    def test_windows_credential_store_round_trip_uses_os_adapter(self):
        api = _database_foundation_support__FakeCredentialApi()
        store = WindowsCredentialStore(api)
        target = "OSTVisualizer/SqlServer/test-id"
        password = secrets.token_urlsafe(24)
        with patch(
            "ost_visualizer.infrastructure.sql.credential_store.ctypes.memset",
            wraps=ctypes.memset,
        ) as wipe:
            store.write_password(target, "test-user", password)
        wipe.assert_called_once()
        self.assertEqual(wipe.call_args.args[2], len(password.encode("utf-16-le")))
        self.assertEqual(store.read_password(target), password)
        store.delete_password(target)
        self.assertNotIn(target, api._records)
