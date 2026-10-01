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
        self.assertEqual(wipe.call_args.args[1], 0)
        self.assertEqual(wipe.call_args.args[2], len(password.encode("utf-16-le")))
        self.assertEqual(
            api._records[target], ("test-user", password.encode("utf-16-le"))
        )
        self.assertEqual(store.read_password(target), password)
        store.delete_password(target)
        self.assertNotIn(target, api._records)

    def test_missing_credential_reads_as_none_and_delete_is_idempotent(self):
        api = _database_foundation_support__FakeCredentialApi()
        api.CredReadW = _database_foundation_support__FakeApiFunction(
            lambda *_args: False
        )
        api.CredDeleteW = _database_foundation_support__FakeApiFunction(
            lambda *_args: False
        )
        store = WindowsCredentialStore(api)
        with patch(
            "ost_visualizer.infrastructure.sql.credential_store.ctypes.get_last_error",
            return_value=1168,
        ):
            self.assertIsNone(store.read_password("OSTVisualizer/SqlServer/missing"))
            store.delete_password("OSTVisualizer/SqlServer/missing")

    def test_unexpected_credential_manager_errors_are_raised_not_swallowed(self):
        api = _database_foundation_support__FakeCredentialApi()
        for name in ("CredReadW", "CredDeleteW", "CredWriteW"):
            setattr(
                api,
                name,
                _database_foundation_support__FakeApiFunction(lambda *_args: False),
            )
        store = WindowsCredentialStore(api)
        with patch(
            "ost_visualizer.infrastructure.sql.credential_store.ctypes.get_last_error",
            return_value=5,
        ):
            with self.assertRaises(OSError) as read_error:
                store.read_password("OSTVisualizer/SqlServer/t")
            with self.assertRaises(OSError):
                store.delete_password("OSTVisualizer/SqlServer/t")
            with patch(
                "ost_visualizer.infrastructure.sql.credential_store.ctypes.memset",
                wraps=ctypes.memset,
            ) as wipe:
                with self.assertRaises(OSError):
                    store.write_password("OSTVisualizer/SqlServer/t", "u", "secret")
        self.assertEqual(read_error.exception.winerror, 5)
        wipe.assert_called_once()

    def test_invalid_targets_are_rejected_before_touching_the_api(self):
        api = _database_foundation_support__FakeCredentialApi()
        store = WindowsCredentialStore(api)
        for target in ("", "nul\x00target"):
            with self.subTest(target=target):
                with self.assertRaises(ValueError):
                    store.write_password(target, "user", "secret")
                with self.assertRaises(ValueError):
                    store.read_password(target)
                with self.assertRaises(ValueError):
                    store.delete_password(target)
        self.assertEqual(api._records, {})
