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


from tests.helpers.sql.database_foundation_support import (  # noqa: E402
    _FakeApiFunction,
)


class _StrictCredentialApi:
    """Windows Credential Manager rules the permissive fake does not enforce.
    CredWriteW/CredReadW/CredDeleteW only accept the generic credential type
    (1) with zero flags, write needs a real persistence mode (2 = local
    machine so the password survives the session) and a blob of at most 2560
    bytes (CRED_MAX_CREDENTIAL_BLOB_SIZE); a read hands back memory that must
    be released exactly once with CredFree.
    """

    NOT_FOUND = 1168
    BAD_ARGUMENTS = 87

    def __init__(self):
        self.records = {}
        self.last_error = 0
        self.writes = []
        self.freed = []
        self.reads = 0
        self._buffers = []
        self.CredWriteW = _FakeApiFunction(self._write)
        self.CredReadW = _FakeApiFunction(self._read)
        self.CredDeleteW = _FakeApiFunction(self._delete)
        self.CredFree = _FakeApiFunction(self._free)

    def _write(self, credential_pointer, flags):
        credential = credential_pointer._obj
        self.writes.append(
            (credential.Type, credential.Persist, flags, credential.CredentialBlobSize)
        )
        if flags != 0 or credential.Type != 1 or credential.Persist not in (1, 2, 3):
            self.last_error = self.BAD_ARGUMENTS
            return False
        if not credential.TargetName or credential.CredentialBlobSize > 2560:
            self.last_error = self.BAD_ARGUMENTS
            return False
        if credential.CredentialBlobSize and not credential.CredentialBlob:
            # a NULL blob with a size is refused by the real API (reading it
            # here would only return uninitialised memory)
            self.last_error = self.BAD_ARGUMENTS
            return False
        blob = ctypes.string_at(
            credential.CredentialBlob, credential.CredentialBlobSize
        )
        self.records[credential.TargetName] = (credential.UserName, blob)
        return True

    def _read(self, target, credential_type, flags, result_pointer):
        if credential_type != 1 or flags != 0:
            self.last_error = self.BAD_ARGUMENTS
            return False
        if target not in self.records:
            self.last_error = self.NOT_FOUND
            return False
        username, blob_bytes = self.records[target]
        blob = (ctypes.c_ubyte * len(blob_bytes)).from_buffer_copy(blob_bytes)
        credential = _CREDENTIALW()
        credential.UserName = username
        credential.CredentialBlobSize = len(blob_bytes)
        credential.CredentialBlob = ctypes.cast(blob, ctypes.POINTER(ctypes.c_ubyte))
        pointer = ctypes.pointer(credential)
        ctypes.cast(result_pointer, ctypes.POINTER(ctypes.POINTER(_CREDENTIALW)))[
            0
        ] = pointer
        self._buffers.append((blob, credential, pointer))
        self.reads += 1
        return True

    def _delete(self, target, credential_type, flags):
        if credential_type != 1 or flags != 0:
            self.last_error = self.BAD_ARGUMENTS
            return False
        if target not in self.records:
            self.last_error = self.NOT_FOUND
            return False
        del self.records[target]
        return True

    def _free(self, pointer):
        self.freed.append(pointer)


class CredentialStoreStrictApiTests(unittest.TestCase):
    TARGET = "OSTVisualizer/SqlServer/test-id"

    def _store(self):
        api = _StrictCredentialApi()
        patcher = patch(
            "ost_visualizer.infrastructure.sql.credential_store.ctypes.get_last_error",
            side_effect=lambda: api.last_error,
        )
        patcher.start()
        self.addCleanup(patcher.stop)
        return WindowsCredentialStore(api), api

    def test_round_trip_uses_generic_type_local_machine_persistence_and_frees_the_read(
        self,
    ):
        store, api = self._store()
        password = secrets.token_urlsafe(24)
        store.write_password(self.TARGET, "user", password)
        # type 1 (generic), persist 2 (local machine), no flags
        self.assertEqual(api.writes[0][:3], (1, 2, 0))
        self.assertEqual(store.read_password(self.TARGET), password)
        self.assertEqual((api.reads, len(api.freed)), (1, 1))
        store.delete_password(self.TARGET)
        self.assertIsNone(store.read_password(self.TARGET))
        store.delete_password(self.TARGET)

    def test_read_memory_is_released_even_when_the_stored_blob_cannot_be_decoded(self):
        store, api = self._store()
        api.records[self.TARGET] = (
            "user",
            b"\x00\xd8\x00",
        )  # lone surrogate + odd byte
        with self.assertRaises(UnicodeDecodeError):
            store.read_password(self.TARGET)
        self.assertEqual((api.reads, len(api.freed)), (1, 1))
        # an empty blob reads as the empty string and is released too
        api.records[self.TARGET] = ("user", b"")
        self.assertEqual(store.read_password(self.TARGET), "")
        self.assertEqual((api.reads, len(api.freed)), (2, 2))

    def test_write_wipes_the_buffer_holding_the_password_even_when_the_api_refuses(
        self,
    ):
        store, api = self._store()
        password = "päss-" + secrets.token_urlsafe(12)
        seen = []
        real_memset = ctypes.memset

        def spying_memset(address, value, size):
            seen.append((ctypes.string_at(address, size), value, size))
            result = real_memset(address, value, size)
            seen.append((ctypes.string_at(address, size), value, size))
            return result

        with patch(
            "ost_visualizer.infrastructure.sql.credential_store.ctypes.memset",
            side_effect=spying_memset,
        ):
            store.write_password(self.TARGET, "user", password)
            api.records.clear()
            api.writes.clear()
            # a blob above the 2560-byte limit is refused by the API
            with self.assertRaises(OSError) as refused:
                store.write_password(self.TARGET, "user", "x" * 1281)
        encoded = password.encode("utf-16-le")
        self.assertEqual(seen[0][0], encoded)  # the wiped region held the password
        self.assertEqual(seen[1][0], b"\x00" * len(encoded))  # and is zero afterwards
        self.assertEqual(seen[2][0], ("x" * 1281).encode("utf-16-le"))
        self.assertEqual(seen[3][0], b"\x00" * 2562)
        self.assertEqual(refused.exception.winerror, _StrictCredentialApi.BAD_ARGUMENTS)
        self.assertNotIn(password, str(refused.exception))
        self.assertNotIn("x" * 20, str(refused.exception))
        self.assertEqual(api.records, {})

    def test_failures_never_echo_the_password_or_target_secret_material(self):
        store, api = self._store()
        secret = secrets.token_urlsafe(24)
        api.CredWriteW = _FakeApiFunction(
            lambda *_args: setattr(api, "last_error", 5) or False
        )
        with self.assertRaises(OSError) as failed:
            store.write_password(self.TARGET, "user", secret)
        for rendering in (
            str(failed.exception),
            repr(failed.exception),
            repr(failed.exception.args),
        ):
            self.assertNotIn(secret, rendering)


class CredentialStoreAdapterContractTests(unittest.TestCase):
    """Survivors of the second-pass mutation sweep over credential_store.py."""

    def test_default_adapter_is_the_advapi32_dll_with_last_error_tracking(self):
        with patch(
            "ost_visualizer.infrastructure.sql.credential_store.ctypes.WinDLL",
            create=True,
        ) as dll:
            store = WindowsCredentialStore()
        # ctypes.get_last_error() only reports Win32 errors when the DLL was
        # loaded with use_last_error=True; ERROR_NOT_FOUND handling depends on it
        dll.assert_called_once_with("Advapi32.dll", use_last_error=True)
        self.assertIs(store._api, dll.return_value)

    def test_every_entry_point_declares_pointer_safe_signatures(self):
        from ctypes import wintypes

        api = _StrictCredentialApi()
        for function in (api.CredWriteW, api.CredReadW, api.CredDeleteW, api.CredFree):
            function.argtypes = "undeclared"
            function.restype = "undeclared"
        WindowsCredentialStore(api)
        # without argtypes/restype 64-bit pointers are truncated to 32-bit ints
        self.assertEqual(
            api.CredWriteW.argtypes, [ctypes.POINTER(_CREDENTIALW), wintypes.DWORD]
        )
        self.assertIs(api.CredWriteW.restype, wintypes.BOOL)
        self.assertEqual(
            api.CredReadW.argtypes,
            [
                wintypes.LPCWSTR,
                wintypes.DWORD,
                wintypes.DWORD,
                ctypes.POINTER(ctypes.POINTER(_CREDENTIALW)),
            ],
        )
        self.assertIs(api.CredReadW.restype, wintypes.BOOL)
        self.assertEqual(
            api.CredDeleteW.argtypes,
            [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD],
        )
        self.assertIs(api.CredDeleteW.restype, wintypes.BOOL)
        self.assertEqual(api.CredFree.argtypes, [ctypes.c_void_p])
        self.assertIsNone(api.CredFree.restype)

    def test_an_adapter_missing_an_entry_point_is_reported_as_unavailable(self):
        class _Incomplete:
            pass

        with self.assertRaisesRegex(
            OSError, "Credential Manager is unavailable"
        ) as caught:
            WindowsCredentialStore(_Incomplete())
        self.assertIsInstance(caught.exception.__cause__, AttributeError)

    def test_a_record_without_a_usable_blob_reads_as_empty_and_is_released(self):
        for label, size in (
            ("null pointer, no size", 0),
            ("null pointer, stale size", 5),
        ):
            with self.subTest(label=label):
                api = _StrictCredentialApi()
                released = []

                def read(target, credential_type, flags, result_pointer):
                    credential = _CREDENTIALW()
                    credential.CredentialBlobSize = size
                    pointer = ctypes.pointer(credential)
                    ctypes.cast(
                        result_pointer, ctypes.POINTER(ctypes.POINTER(_CREDENTIALW))
                    )[0] = pointer
                    api._buffers.append((credential, pointer))
                    return True

                api.CredReadW = _FakeApiFunction(read)
                api.CredFree = _FakeApiFunction(
                    lambda pointer: released.append(pointer)
                )
                store = WindowsCredentialStore(api)
                # the NULL blob is never dereferenced (that would crash the process)
                self.assertEqual(store.read_password("OSTVisualizer/SqlServer/x"), "")
                self.assertEqual(len(released), 1)
