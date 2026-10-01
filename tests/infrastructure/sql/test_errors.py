import unittest
from ost_visualizer.infrastructure.sql.errors import (
    SqlErrorCode,
    SqlErrorDetails,
    SqlInfrastructureError,
)
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from ost_visualizer.infrastructure.sql.errors import SqlErrorCode, classify_pyodbc_error
from PySide6 import QtCore, QtWidgets
from tests.helpers.sql.database_foundation_support import (
    _IconProvider as _database_foundation_support__IconProvider,
    _app as _database_foundation_support__app,
)


class ErrorsCollaborationTests(unittest.TestCase):
    def test_collaboration_failures_classify_credentials_and_schema_read_only(self):
        credential = SqlInfrastructureError(
            SqlErrorDetails(SqlErrorCode.AUTHENTICATION_FAILED, "Sign in again.")
        )
        schema = SqlInfrastructureError(
            SqlErrorDetails(SqlErrorCode.SCHEMA_MISMATCH, "Schema mismatch.")
        )
        permission = SqlInfrastructureError(
            SqlErrorDetails(SqlErrorCode.PERMISSION_DENIED, "Permission revoked.")
        )
        self.assertTrue(credential.credential_required)
        self.assertFalse(credential.read_only_required)
        self.assertFalse(credential.retryable)
        self.assertFalse(credential.session_expired)
        self.assertTrue(schema.read_only_required)
        self.assertTrue(permission.read_only_required)
        self.assertFalse(schema.credential_required)
        self.assertFalse(permission.credential_required)
        self.assertFalse(schema.retryable)
        self.assertFalse(permission.retryable)
        self.assertEqual(str(permission), "Permission revoked.")
        self.assertEqual(permission.details.code, SqlErrorCode.PERMISSION_DENIED)

    def test_every_error_code_maps_to_its_exact_recovery_flags(self):
        expected = {
            SqlErrorCode.CONNECTION_FAILED: (True, False, False, False),
            SqlErrorCode.TIMEOUT: (True, False, False, False),
            SqlErrorCode.UNKNOWN: (True, False, False, False),
            SqlErrorCode.SESSION_EXPIRED: (False, True, False, False),
            SqlErrorCode.AUTHENTICATION_FAILED: (False, False, True, False),
            SqlErrorCode.CREDENTIAL_MISSING: (False, False, True, False),
            SqlErrorCode.PERMISSION_DENIED: (False, False, False, True),
            SqlErrorCode.SCHEMA_MISMATCH: (False, False, False, True),
            SqlErrorCode.CERTIFICATE_FAILED: (False, False, False, False),
            SqlErrorCode.DATABASE_MISSING: (False, False, False, False),
            SqlErrorCode.LOCKED: (False, False, False, False),
            SqlErrorCode.CONFLICT: (False, False, False, False),
            SqlErrorCode.CONSTRAINT_FAILED: (False, False, False, False),
        }
        self.assertEqual(set(expected), set(SqlErrorCode))
        for code, flags in expected.items():
            with self.subTest(code=code):
                error = SqlInfrastructureError(SqlErrorDetails(code, "message"))
                self.assertEqual(
                    (
                        error.retryable,
                        error.session_expired,
                        error.credential_required,
                        error.read_only_required,
                    ),
                    flags,
                )


class ErrorsSqlDialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _database_foundation_support__app()
        cls.icon_provider = _database_foundation_support__IconProvider()

    def test_certificate_error_explains_default_trust_behavior(self):
        error = RuntimeError(
            "08001",
            "SSL Provider: The certificate chain was issued by an authority "
            "that is not trusted.",
        )
        details = classify_pyodbc_error(error)
        self.assertEqual(details.code, SqlErrorCode.CERTIFICATE_FAILED)
        self.assertEqual(details.sql_state, "08001")
        self.assertIn("normally trusts", details.user_message)
        self.assertIn("reconnect the database", details.user_message)

    def test_pyodbc_errors_classify_to_exact_code_state_and_native_number(self):
        Code = SqlErrorCode
        cases = (
            (
                ("28000", "Login failed (18456)"),
                Code.AUTHENTICATION_FAILED,
                "28000",
                18456,
            ),
            (
                ("42000", "Login failed for user (18456)"),
                Code.AUTHENTICATION_FAILED,
                "42000",
                18456,
            ),
            (
                ("42000", "Cannot open database X (4060)"),
                Code.DATABASE_MISSING,
                "42000",
                4060,
            ),
            (
                ("42000", "The SELECT permission was denied (229)"),
                Code.PERMISSION_DENIED,
                "42000",
                229,
            ),
            (("HYT00", "Login timeout expired"), Code.TIMEOUT, "HYT00", None),
            (
                ("08001", "TCP Provider: attempt failed (10060)"),
                Code.CONNECTION_FAILED,
                "08001",
                10060,
            ),
            (
                ("23000", "Violation of PRIMARY KEY constraint"),
                Code.CONSTRAINT_FAILED,
                "23000",
                None,
            ),
            (("42S02", "Invalid object name"), Code.UNKNOWN, "42S02", None),
        )
        for args, code, state, native in cases:
            with self.subTest(code=code):
                details = classify_pyodbc_error(RuntimeError(*args))
                self.assertEqual(details.code, code)
                self.assertEqual(details.sql_state, state)
                self.assertEqual(details.native_code, native)
                self.assertTrue(details.user_message)

    def test_error_without_arguments_is_unknown(self):
        details = classify_pyodbc_error(RuntimeError())
        self.assertEqual(details.code, SqlErrorCode.UNKNOWN)
        self.assertEqual(details.sql_state, "")
        self.assertIsNone(details.native_code)

    def test_untrusted_certificate_is_not_reported_as_connection_failure(self):
        # SQLSTATE 08001 would otherwise match the connection-failed branch.
        details = classify_pyodbc_error(
            RuntimeError("08001", "certificate verify failed: self signed")
        )
        self.assertEqual(details.code, SqlErrorCode.CERTIFICATE_FAILED)
        self.assertEqual(details.sql_state, "08001")
