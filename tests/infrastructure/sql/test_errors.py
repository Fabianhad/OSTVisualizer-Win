import unittest
from ost_visualizer.infrastructure.sql.errors import (
    SqlErrorCode,
    SqlErrorDetails,
    SqlInfrastructureError,
)
import os
import pyodbc

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


from tests.helpers.sql.strict_sql_fakes import sql_server_error  # noqa: E402


class ErrorsSqlServerDiagnosticShapeTests(unittest.TestCase):
    """Classification of the diagnostics ODBC Driver 18 really produces.
    The shapes follow pyodbc's ``(sqlstate, "[sqlstate] [Microsoft][ODBC Driver
    18 for SQL Server][SQL Server]message (native) (SQLFunction)")`` args, with
    several records joined by ``"; "`` for connection failures.
    """

    def _classify(self, state, message, native=None):
        return classify_pyodbc_error(sql_server_error(state, message, native))

    def test_connection_class_errors_are_separate_from_statement_errors(self):
        Code = SqlErrorCode
        connection_class = (
            ("08S01", "Communication link failure", 0, Code.CONNECTION_FAILED),
            (
                "08001",
                "TCP Provider: An existing connection was forcibly closed by "
                "the remote host.",
                10054,
                Code.CONNECTION_FAILED,
            ),
            ("HYT00", "Login timeout expired", 0, Code.TIMEOUT),
            ("HYT00", "Query timeout expired", 0, Code.TIMEOUT),
        )
        statement_errors = (
            (
                "23000",
                "Violation of PRIMARY KEY constraint 'PK_Bids'. Cannot insert "
                "duplicate key in object 'dbo.Bids'.",
                2627,
                Code.CONSTRAINT_FAILED,
            ),
            (
                "23000",
                "The INSERT statement conflicted with the FOREIGN KEY "
                'constraint "FK_BidPages_Bids".',
                547,
                Code.CONSTRAINT_FAILED,
            ),
            (
                "23000",
                "Cannot insert duplicate key row in object 'dbo.Bids' with "
                "unique index 'IX_Bids_Name'.",
                2601,
                Code.CONSTRAINT_FAILED,
            ),
            ("42S02", "Invalid object name 'dbo.Nope'.", 208, Code.UNKNOWN),
            ("22001", "String or binary data would be truncated.", 8152, Code.UNKNOWN),
            # deadlock victim, lock timeout and snapshot update conflict are
            # statement/transaction errors: they are not connection failures and
            # are currently reported as UNKNOWN (retryable); the commit is never
            # retried by the writer regardless of this classification.
            (
                "40001",
                "Transaction (Process ID 61) was deadlocked on lock "
                "resources with another process and has been chosen as the deadlock "
                "victim. Rerun the transaction.",
                1205,
                Code.UNKNOWN,
            ),
            ("42000", "Lock request time out period exceeded.", 1222, Code.UNKNOWN),
            (
                "S0001",
                "Snapshot isolation transaction aborted due to update " "conflict.",
                3960,
                Code.UNKNOWN,
            ),
        )
        for state, message, native, expected in (*connection_class, *statement_errors):
            with self.subTest(state=state, native=native):
                details = self._classify(state, message, native)
                self.assertEqual(details.code, expected)
                self.assertEqual(details.sql_state, state)

    def test_numbers_inside_the_message_do_not_override_the_server_diagnostic(self):
        # The duplicate key value is echoed in the message. A key equal to a
        # code the classifier knows (53, 229, 4060, 18456, ...) must not turn an
        # integrity-constraint violation into a connection, permission or login
        # failure (which would also flip the session read-only or retry it).
        for key in (53, 64, 229, 233, 262, 297, 4060, 10054, 10060, 18456):
            with self.subTest(key=key):
                details = self._classify(
                    "23000",
                    "Violation of PRIMARY KEY constraint 'PK_x'. Cannot insert "
                    f"duplicate key in object 'dbo.x'. The duplicate key value is "
                    f"({key}).",
                    2627,
                )
                self.assertEqual(details.code, SqlErrorCode.CONSTRAINT_FAILED)
                error = SqlInfrastructureError(details)
                self.assertFalse(error.retryable)
                self.assertFalse(error.read_only_required)
                self.assertFalse(error.credential_required)

    def test_object_names_containing_permission_do_not_make_a_constraint_a_denial(self):
        details = self._classify(
            "23000",
            "The DELETE statement conflicted with the REFERENCE constraint "
            '"FK_x". The conflict occurred in database "Permissions_Test", '
            "table \"dbo.Bids\", column 'UID'.",
            547,
        )
        self.assertEqual(details.code, SqlErrorCode.CONSTRAINT_FAILED)

    def test_multi_record_connection_failure_still_finds_the_native_code(self):
        message = (
            "[08001] [Microsoft][ODBC Driver 18 for SQL Server]Named Pipes "
            "Provider: Could not open a connection to SQL Server [53].  (53) "
            "(SQLDriverConnect); [08001] [Microsoft][ODBC Driver 18 for SQL "
            "Server]Login timeout expired (0); [08001] [Microsoft][ODBC Driver "
            "18 for SQL Server]A network-related or instance-specific error has "
            "occurred while establishing a connection to SQL Server. (53)"
        )
        details = classify_pyodbc_error(pyodbc.Error("08001", message))
        self.assertEqual(details.code, SqlErrorCode.TIMEOUT)
        # without the timeout record the same state is a connection failure
        details = classify_pyodbc_error(
            pyodbc.Error("08001", message.replace("Login timeout expired (0); ", ""))
        )
        self.assertEqual(details.code, SqlErrorCode.CONNECTION_FAILED)
        self.assertEqual(details.native_code, 53)


class ErrorsNativeNumberAndTextMappingTests(unittest.TestCase):
    """Survivors of the second-pass mutation sweep over errors.py."""

    KNOWN = (
        (18456, SqlErrorCode.AUTHENTICATION_FAILED),
        (4060, SqlErrorCode.DATABASE_MISSING),
        (229, SqlErrorCode.PERMISSION_DENIED),
        (262, SqlErrorCode.PERMISSION_DENIED),
        (297, SqlErrorCode.PERMISSION_DENIED),
        (53, SqlErrorCode.CONNECTION_FAILED),
        (64, SqlErrorCode.CONNECTION_FAILED),
        (233, SqlErrorCode.CONNECTION_FAILED),
        (10054, SqlErrorCode.CONNECTION_FAILED),
        (10060, SqlErrorCode.CONNECTION_FAILED),
    )

    def test_each_known_native_number_decides_the_code_in_every_message_shape(self):
        for number, expected in self.KNOWN:
            shapes = (
                # real driver diagnostic ("(N) (SQLFunction)")
                pyodbc.Error(
                    "42000",
                    f"[42000] [Microsoft][ODBC Driver 18 for SQL Server]An error occurred ({number}) (SQLExecDirectW)",
                ),
                # trailing number only
                pyodbc.Error("42000", f"An error occurred ({number})"),
                # hand-written shapes without a driver suffix: parenthesised and bare
                pyodbc.Error(
                    "42000", f"An error occurred ({number}) while working; retry"
                ),
                pyodbc.Error("42000", f"native error {number} happened"),
            )
            for index, error in enumerate(shapes):
                with self.subTest(native=number, shape=index):
                    details = classify_pyodbc_error(error)
                    self.assertEqual(details.code, expected)
                    self.assertEqual(details.native_code, number)

    def test_numbers_next_to_the_known_ones_are_not_mistaken_for_them(self):
        for number, _expected in self.KNOWN:
            for neighbour in (number - 1, number + 1):
                if neighbour in {n for n, _ in self.KNOWN}:
                    continue
                for text in (
                    f"An error occurred ({neighbour}) (SQLExecDirectW)",
                    f"An error occurred ({neighbour})",
                    f"native error {neighbour} happened",
                ):
                    with self.subTest(neighbour=neighbour, text=text):
                        details = classify_pyodbc_error(pyodbc.Error("42000", text))
                        self.assertEqual(details.code, SqlErrorCode.UNKNOWN)
                        self.assertIsNone(details.native_code)

    def test_known_native_numbers_win_in_priority_order_when_several_are_reported(self):
        details = classify_pyodbc_error(
            pyodbc.Error(
                "08001",
                "first (53) (SQLDriverConnect); second (18456) (SQLDriverConnect)",
            )
        )
        self.assertEqual(
            (details.code, details.native_code),
            (SqlErrorCode.AUTHENTICATION_FAILED, 18456),
        )

    def test_message_text_alone_decides_when_no_native_number_is_reported(self):
        cases = (
            (
                "42000",
                'Cannot open database "X" requested by the login. The login failed.',
                SqlErrorCode.DATABASE_MISSING,
            ),
            (
                "42000",
                "The user does not have permission to perform this action.",
                SqlErrorCode.PERMISSION_DENIED,
            ),
            (
                "42000",
                "The SELECT permission was denied on the object 'X'",
                SqlErrorCode.PERMISSION_DENIED,
            ),
            ("HY000", "Query timeout expired", SqlErrorCode.TIMEOUT),
            ("HYT01", "Connection timeout", SqlErrorCode.TIMEOUT),
            ("HYT00", "Something else", SqlErrorCode.TIMEOUT),
            ("08001", "No route", SqlErrorCode.CONNECTION_FAILED),
            ("08S01", "Link failure", SqlErrorCode.CONNECTION_FAILED),
            ("28000", "Anything", SqlErrorCode.AUTHENTICATION_FAILED),
            ("23000", "Duplicate", SqlErrorCode.CONSTRAINT_FAILED),
            ("23505", "Duplicate", SqlErrorCode.CONSTRAINT_FAILED),
            ("42000", "Syntax error", SqlErrorCode.UNKNOWN),
        )
        for state, text, expected in cases:
            with self.subTest(state=state, text=text):
                self.assertEqual(
                    classify_pyodbc_error(pyodbc.Error(state, text)).code, expected
                )

    def test_certificate_failures_need_the_certificate_word_and_a_trust_phrase(self):
        trusted_phrases = (
            "The certificate is not trusted",
            "A certificate chain was issued by an authority that is not recognised",
            "SSL error: certificate verify failed",
        )
        for phrase in trusted_phrases:
            with self.subTest(phrase=phrase):
                details = classify_pyodbc_error(pyodbc.Error("08001", phrase))
                self.assertEqual(details.code, SqlErrorCode.CERTIFICATE_FAILED)
        # either half alone is not enough
        self.assertEqual(
            classify_pyodbc_error(
                pyodbc.Error("08001", "certificate expired soon")
            ).code,
            SqlErrorCode.CONNECTION_FAILED,
        )
        self.assertEqual(
            classify_pyodbc_error(
                pyodbc.Error("08001", "the host is not trusted")
            ).code,
            SqlErrorCode.CONNECTION_FAILED,
        )

    def test_a_single_argument_is_the_state_only_and_is_never_searched_as_text(self):
        details = classify_pyodbc_error(
            pyodbc.ProgrammingError("timeout using permission")
        )
        self.assertEqual(details.code, SqlErrorCode.UNKNOWN)
        self.assertEqual(details.sql_state, "timeout using permission")

    def test_error_details_are_immutable(self):
        import dataclasses

        details = classify_pyodbc_error(pyodbc.Error("08S01", "x"))
        with self.assertRaises(dataclasses.FrozenInstanceError):
            details.code = SqlErrorCode.UNKNOWN
        self.assertTrue(details.user_message)


class ErrorsDriverReportedNumberTests(unittest.TestCase):
    """Survivor of the second-pass mutation sweep over errors.py."""

    def test_an_unrecognised_driver_number_hides_known_numbers_echoed_in_the_message(
        self,
    ):
        # (8114) is the real native error; "(229)", " 53 " and " 10060 " are data
        # echoed from the statement. Without a state class 23 shortcut the
        # classification must still follow the driver-reported number only.
        message = (
            "[42000] [Microsoft][ODBC Driver 18 for SQL Server][SQL Server]Error "
            "converting data near (229) with ' 53 ' and ' 10060 '. (8114) (SQLExecDirectW)"
        )
        details = classify_pyodbc_error(pyodbc.Error("42000", message))
        self.assertEqual(details.code, SqlErrorCode.UNKNOWN)
        self.assertIsNone(details.native_code)
        # the same message without a driver-reported number falls back to the legacy scan
        legacy = classify_pyodbc_error(
            pyodbc.Error("42000", "Error converting data near (229) with ' 53 '")
        )
        self.assertEqual(legacy.code, SqlErrorCode.PERMISSION_DENIED)
        self.assertEqual(legacy.native_code, 229)


class ErrorsTransactionConflictPinTests(unittest.TestCase):
    """Decision D12 (pin): a deadlock victim (1205), a lock timeout (1222) and a
    snapshot update conflict (3960) are NOT given a dedicated error code. They
    classify as UNKNOWN (retryable, no native code) and are never connection,
    permission, authentication or constraint failures. The writer never retries
    them (see WriterTransactionConflictPinTests); only a caller may.
    The diagnostics follow ODBC Driver 18 for pyodbc: ``(sqlstate, "[sqlstate]
    [Microsoft][ODBC Driver 18 for SQL Server][SQL Server]message (native)
    (SQLExecDirectW)")``. The SQLSTATEs 40001 (1205) are the documented ones; the
    states seen for 1222 and 3960 are from memory of driver output (no live
    server is available), so every plausible state is covered.
    """

    DEADLOCK = (
        "Transaction (Process ID {pid}) was deadlocked on lock resources with "
        "another process and has been chosen as the deadlock victim. Rerun the "
        "transaction."
    )
    LOCK_TIMEOUT = "Lock request time out period exceeded."
    SNAPSHOT = (
        "Snapshot isolation transaction aborted due to update conflict. You "
        "cannot use snapshot isolation to access table '{table}' directly or "
        "indirectly in database '{database}' to update, delete, or insert the "
        "row that has been modified or deleted by another transaction. Retry "
        "the transaction or change the isolation level for the update/delete "
        "statement."
    )

    def _shapes(self):
        return (
            (
                "deadlock victim",
                ("40001",),
                self.DEADLOCK.format(pid=55),
                1205,
            ),
            ("lock timeout", ("42000", "HY000"), self.LOCK_TIMEOUT, 1222),
            (
                "snapshot conflict",
                ("42000", "S0001"),
                self.SNAPSHOT.format(table="dbo.BidLayers", database="OSTV"),
                3960,
            ),
        )

    def _classify(self, state, message, native):
        error = sql_server_error(state, message, native)
        details = classify_pyodbc_error(error)
        return details, SqlInfrastructureError(details)

    def test_each_conflict_error_is_unknown_without_native_code_and_retryable(self):
        for label, states, message, native in self._shapes():
            for state in states:
                with self.subTest(error=label, state=state):
                    details, error = self._classify(state, message, native)
                    self.assertEqual(details.code, SqlErrorCode.UNKNOWN)
                    self.assertIsNone(details.native_code)
                    self.assertEqual(details.sql_state, state)
                    self.assertEqual(
                        details.user_message, "SQL Server returned an unexpected error."
                    )
                    self.assertEqual(
                        (
                            error.retryable,
                            error.session_expired,
                            error.credential_required,
                            error.read_only_required,
                        ),
                        (True, False, False, False),
                    )

    def test_lock_timeout_reported_with_the_timeout_sqlstate_is_a_retryable_timeout(
        self,
    ):
        # Current behaviour, pinned: if the driver reports 1222 with SQLSTATE
        # HYT00 the SQLSTATE alone selects TIMEOUT (the message "time out" has a
        # space, so the text rule is not what matches). It is still retryable and
        # still not a connection / permission failure, so the recovery flags equal
        # the UNKNOWN ones; only the code (and user message) differ.
        details, error = self._classify("HYT00", self.LOCK_TIMEOUT, 1222)
        self.assertEqual(details.code, SqlErrorCode.TIMEOUT)
        self.assertIsNone(details.native_code)
        self.assertEqual(details.user_message, "The SQL Server connection timed out.")
        self.assertEqual(
            (
                error.retryable,
                error.session_expired,
                error.credential_required,
                error.read_only_required,
            ),
            (True, False, False, False),
        )

    def test_numbers_echoed_in_the_conflict_message_never_change_the_classification(
        self,
    ):
        known = (53, 64, 229, 233, 262, 297, 4060, 10054, 10060, 18456)
        for number in known:
            with self.subTest(number=number):
                # the deadlock victim's process id and a table name that ends in a
                # parenthesised number are data, not diagnostics
                for message, native in (
                    (self.DEADLOCK.format(pid=number), 1205),
                    (
                        self.SNAPSHOT.format(
                            table=f"dbo.Bids({number})", database=f"OSTV {number} x"
                        ),
                        3960,
                    ),
                    (f"Lock request time out period exceeded. ({number})", 1222),
                ):
                    details, error = self._classify("42000", message, native)
                    self.assertEqual(details.code, SqlErrorCode.UNKNOWN)
                    self.assertIsNone(details.native_code)
                    self.assertTrue(error.retryable)
                    self.assertFalse(error.read_only_required)
                    self.assertFalse(error.credential_required)

    def test_conflict_words_alone_do_not_trip_the_text_rules(self):
        # lock / deadlock / snapshot / login / certificate / transaction wording
        # (also echoed in other messages) is not part of any classification rule
        message = (
            "Transaction was deadlocked on lock resources. The login for the "
            "snapshot certificate store was rerun. "
        )
        for state in ("40001", "42000", "S0001", "HY000"):
            for native in (1205, 1222, 3960):
                with self.subTest(state=state, native=native):
                    details, _error = self._classify(state, message, native)
                    self.assertEqual(details.code, SqlErrorCode.UNKNOWN)
                    self.assertIsNone(details.native_code)

    def test_conflict_errors_are_the_documented_exception_to_the_connection_rules(
        self,
    ):
        # positive control: the same conflict messages become CONNECTION_FAILED
        # only when the driver says the link failed (08xxx), proving the UNKNOWN
        # outcomes above come from the SQLSTATE and text rules, not a default.
        details, error = self._classify("08S01", self.DEADLOCK.format(pid=55), 1205)
        self.assertEqual(details.code, SqlErrorCode.CONNECTION_FAILED)
        self.assertTrue(error.retryable)
        details, error = self._classify("23000", self.DEADLOCK.format(pid=55), 1205)
        self.assertEqual(details.code, SqlErrorCode.CONSTRAINT_FAILED)
        self.assertFalse(error.retryable)


ECHOED_NAMES = (
    "Permissions_Test",
    "Login_Failed_Db",
    "Timeout_Table",
    "Connection_Reset",
    "read-only_t",
    "deadlock_users",
    "permission denied",
    "login failed",
    "timeout expired",
    "read only",
    "connection timeout",
    "cannot open database X",
    "certificate chain is not trusted",
)


def _flags(error):
    return (
        error.retryable,
        error.session_expired,
        error.credential_required,
        error.read_only_required,
    )


class ErrorsNumberAndStateBeforeTextTests(unittest.TestCase):
    """Decision (F1): the SQLSTATE and the driver-reported native number
    classify a diagnostic; message text never overrides them. Every message here
    echoes a database / table / column / value name that contains a word the old
    unanchored text rules searched for (permission, login, timeout, read only,
    connection, cannot open database, certificate ...). Fakes: pyodbc.Error
    built from the documented ODBC Driver 18 diagnostic shape, no live server.
    """

    def _classify(self, state, message, native=None):
        details = classify_pyodbc_error(sql_server_error(state, message, native))
        return details, SqlInfrastructureError(details)

    def test_transaction_conflicts_stay_unknown_whatever_names_they_echo(self):
        snapshot = (
            "Snapshot isolation transaction aborted due to update conflict. "
            "You cannot use snapshot isolation to access table '{table}' "
            "directly or indirectly in database '{echo}' to update, delete, "
            "or insert the row that has been modified or deleted by another "
            "transaction. Retry the transaction or change the isolation "
            "level for the update/delete statement."
        )
        templates = (
            (
                "deadlock victim",
                "40001",
                1205,
                "Transaction (Process ID 55) was deadlocked on lock resources "
                "with another process and has been chosen as the deadlock "
                "victim. Rerun the transaction. Object '{echo}'.",
            ),
            (
                "lock timeout",
                "42000",
                1222,
                "Lock request time out period exceeded. Object '{echo}'.",
            ),
            (
                "lock timeout (HY000)",
                "HY000",
                1222,
                "Lock request time out period exceeded. Object '{echo}'.",
            ),
            (
                "snapshot conflict",
                "S0001",
                3960,
                snapshot.replace("{table}", "{echo}"),
            ),
            (
                "snapshot conflict (42000)",
                "42000",
                3960,
                snapshot.replace("{table}", "dbo.Bids"),
            ),
        )
        for label, state, number, template in templates:
            for echo in ECHOED_NAMES:
                with self.subTest(error=label, echo=echo):
                    details, error = self._classify(
                        state, template.format(echo=echo), number
                    )
                    self.assertEqual(details.code, SqlErrorCode.UNKNOWN)
                    self.assertIsNone(details.native_code)
                    self.assertEqual(details.sql_state, state)
                    self.assertEqual(_flags(error), (True, False, False, False))

    def test_constraint_violations_stay_constraint_failures_whatever_names_they_echo(
        self,
    ):
        templates = (
            (
                2627,
                "Violation of PRIMARY KEY constraint 'PK_{echo}'. Cannot insert "
                "duplicate key in object 'dbo.{echo}'. The duplicate key value "
                "is ({echo}).",
            ),
            (
                547,
                "The DELETE statement conflicted with the REFERENCE constraint "
                '"FK_x". The conflict occurred in database "{echo}", table '
                "\"dbo.{echo}\", column '{echo}'.",
            ),
            (
                2601,
                "Cannot insert duplicate key row in object 'dbo.Bids' with "
                "unique index 'IX_{echo}'. The duplicate key value is ({echo}).",
            ),
        )
        for number, template in templates:
            for echo in ECHOED_NAMES:
                with self.subTest(number=number, echo=echo):
                    details, error = self._classify(
                        "23000", template.format(echo=echo), number
                    )
                    self.assertEqual(details.code, SqlErrorCode.CONSTRAINT_FAILED)
                    self.assertEqual(_flags(error), (False, False, False, False))

    def test_denied_login_missing_database_and_connection_failures_ignore_echoed_words(
        self,
    ):
        Code = SqlErrorCode
        templates = (
            (
                "permission 229",
                "42000",
                229,
                "The SELECT permission was denied on the object '{echo}', "
                "database '{echo}', schema 'dbo'.",
                Code.PERMISSION_DENIED,
                (False, False, False, True),
            ),
            (
                "permission 262",
                "42000",
                262,
                "CREATE TABLE permission denied in database '{echo}'.",
                Code.PERMISSION_DENIED,
                (False, False, False, True),
            ),
            (
                "login 18456",
                "28000",
                18456,
                "Login failed for user '{echo}'.",
                Code.AUTHENTICATION_FAILED,
                (False, False, True, False),
            ),
            (
                "login 18456 without the login state",
                "42000",
                18456,
                "Login failed for user '{echo}'.",
                Code.AUTHENTICATION_FAILED,
                (False, False, True, False),
            ),
            (
                "database 4060",
                "42000",
                4060,
                'Cannot open database "{echo}" requested by the login. The '
                "login failed.",
                Code.DATABASE_MISSING,
                (False, False, False, False),
            ),
            (
                "database 4060 (08004)",
                "08004",
                4060,
                'Cannot open database "{echo}" requested by the login. The '
                "login failed.",
                Code.DATABASE_MISSING,
                (False, False, False, False),
            ),
            (
                "connection 10060",
                "08001",
                10060,
                "TCP Provider: A connection attempt to host '{echo}' failed.",
                Code.CONNECTION_FAILED,
                (True, False, False, False),
            ),
            (
                "connection 53",
                "08001",
                53,
                "Named Pipes Provider: Could not open a connection to SQL "
                "Server [{echo}].",
                Code.CONNECTION_FAILED,
                (True, False, False, False),
            ),
            (
                "link failure",
                "08S01",
                0,
                "Communication link failure to '{echo}'.",
                Code.CONNECTION_FAILED,
                (True, False, False, False),
            ),
            (
                "driver timeout",
                "HYT00",
                0,
                "Query timeout expired for '{echo}'.",
                Code.TIMEOUT,
                (True, False, False, False),
            ),
        )
        for label, state, number, template, code, flags in templates:
            for echo in ECHOED_NAMES:
                with self.subTest(error=label, echo=echo):
                    details, error = self._classify(
                        state, template.format(echo=echo), number
                    )
                    self.assertEqual(details.code, code)
                    self.assertEqual(details.sql_state, state)
                    self.assertEqual(_flags(error), flags)

    def test_other_statement_errors_stay_unknown_whatever_names_they_echo(self):
        templates = (
            ("42S02", 208, "Invalid object name 'dbo.{echo}'."),
            ("42S22", 207, "Invalid column name '{echo}'."),
            ("22001", 8152, "String or binary data would be truncated in '{echo}'."),
            ("42000", 8114, "Error converting data type near '{echo}'."),
        )
        for state, number, template in templates:
            for echo in ECHOED_NAMES:
                with self.subTest(number=number, echo=echo):
                    details, error = self._classify(
                        state, template.format(echo=echo), number
                    )
                    self.assertEqual(details.code, SqlErrorCode.UNKNOWN)
                    self.assertIsNone(details.native_code)
                    self.assertEqual(_flags(error), (True, False, False, False))

    def test_sqlstate_and_number_outrank_text_that_names_another_category(self):
        Code = SqlErrorCode
        permission = "The SELECT permission was denied on the object 'X'"
        missing = 'Cannot open database "X" requested by the login.'
        cases = (
            # SQLSTATE beats text
            ("HYT00", permission, Code.TIMEOUT),
            ("HYT01", missing, Code.TIMEOUT),
            ("23000", missing, Code.CONSTRAINT_FAILED),
            ("23000", "Query timeout expired", Code.CONSTRAINT_FAILED),
            ("28000", "Query timeout expired", Code.AUTHENTICATION_FAILED),
            ("28000", permission, Code.AUTHENTICATION_FAILED),
        )
        for state, message, expected in cases:
            with self.subTest(state=state, message=message):
                self.assertEqual(
                    classify_pyodbc_error(pyodbc.Error(state, message)).code, expected
                )
        # the driver-reported number beats text that names another category
        number_cases = (
            (53, "Login timeout expired", Code.CONNECTION_FAILED),
            (229, "Query timeout expired", Code.PERMISSION_DENIED),
            (
                4060,
                "The user does not have permission to perform this action.",
                Code.DATABASE_MISSING,
            ),
            (18456, missing, Code.AUTHENTICATION_FAILED),
            (8114, "Query timeout expired", Code.UNKNOWN),
        )
        for number, message, expected in number_cases:
            with self.subTest(number=number, message=message):
                details = classify_pyodbc_error(
                    sql_server_error("42000", message, number)
                )
                self.assertEqual(details.code, expected)


class ErrorsAnchoredTextFallbackTests(unittest.TestCase):
    """Decision (F1): message text is only a last-resort fallback for records
    that carry no usable number or SQLSTATE, and it is anchored to the start of
    the server message (after the pyodbc / driver prefix) like the documented
    message templates; an echoed word in the middle never fires it."""

    PREFIX = "[Microsoft][ODBC Driver 18 for SQL Server][SQL Server]"

    def _shapes(self, state, message):
        # bare message, driver-prefixed message, and the number-less diagnostic
        return (
            pyodbc.Error(state, message),
            pyodbc.Error(state, f"[{state}] {self.PREFIX}{message}"),
            pyodbc.Error(state, f"[{state}] {self.PREFIX}{message} (SQLExecDirectW)"),
        )

    def test_documented_templates_classify_when_no_number_is_reported(self):
        Code = SqlErrorCode
        cases = (
            (
                "42000",
                'Cannot open database "X" requested by the login. The login failed.',
                Code.DATABASE_MISSING,
            ),
            (
                "42000",
                "The SELECT permission was denied on the object 'X', database "
                "'Y', schema 'dbo'.",
                Code.PERMISSION_DENIED,
            ),
            (
                "42000",
                "The EXECUTE permission was denied on the object 'sp_x', "
                "database 'Y', schema 'dbo'.",
                Code.PERMISSION_DENIED,
            ),
            (
                "42000",
                "CREATE TABLE permission denied in database 'Y'.",
                Code.PERMISSION_DENIED,
            ),
            (
                "42000",
                "VIEW SERVER STATE permission was denied on object 'server', "
                "database 'master'.",
                Code.PERMISSION_DENIED,
            ),
            (
                "42000",
                "The user does not have permission to perform this action.",
                Code.PERMISSION_DENIED,
            ),
            ("HY000", "Login timeout expired", Code.TIMEOUT),
            ("HY000", "Query timeout expired", Code.TIMEOUT),
            ("HY000", "Connection timeout expired", Code.TIMEOUT),
            (
                "08001",
                "SSL Provider: The certificate chain was issued by an "
                "authority that is not trusted.",
                Code.CERTIFICATE_FAILED,
            ),
            ("08001", "The certificate is not trusted", Code.CERTIFICATE_FAILED),
            ("08001", "SSL error: certificate verify failed", Code.CERTIFICATE_FAILED),
        )
        for state, message, expected in cases:
            for index, error in enumerate(self._shapes(state, message)):
                with self.subTest(message=message, shape=index):
                    self.assertEqual(classify_pyodbc_error(error).code, expected)

    def test_trigger_words_in_the_middle_of_a_message_do_not_fire_the_fallback(self):
        mid_message = (
            "Invalid object name 'dbo.Permissions_Test'.",
            "Invalid column name 'Timeout_Table'.",
            "Incorrect syntax near 'permission denied'.",
            "Incorrect syntax near the keyword 'timeout'.",
            "The statement failed for user 'Login_Failed_Db' (read-only_t).",
            "Could not find stored procedure 'cannot open database X'.",
            "Invalid object name 'certificate chain is not trusted'.",
            "Warning: the user does not have permission to perform this action.",
            "Error: Query timeout expired",
            "Failed. Cannot open database X",
            "The snapshot of Connection_Reset is read only: deadlock_users.",
        )
        for message in mid_message:
            for index, error in enumerate(self._shapes("42000", message)):
                with self.subTest(message=message, shape=index):
                    details = classify_pyodbc_error(error)
                    self.assertEqual(details.code, SqlErrorCode.UNKNOWN)

    def test_a_reported_non_zero_number_disables_the_text_fallback_for_its_record(self):
        # same anchored templates, but the driver reports an unmapped number: the
        # number decides (UNKNOWN), the template text is not consulted
        for message in (
            'Cannot open database "X" requested by the login. The login failed.',
            "The user does not have permission to perform this action.",
            "Query timeout expired",
            "The certificate is not trusted",
        ):
            with self.subTest(message=message):
                details = classify_pyodbc_error(
                    sql_server_error("42000", message, 8114)
                )
                self.assertEqual(details.code, SqlErrorCode.UNKNOWN)
        # a zero number means "no native error": the fallback still applies
        details = classify_pyodbc_error(
            sql_server_error("42000", "Query timeout expired", 0)
        )
        self.assertEqual(details.code, SqlErrorCode.TIMEOUT)

    def test_a_known_number_found_by_the_legacy_scan_also_outranks_the_text_fallback(
        self,
    ):
        # no driver-reported "(N)" at the end of a record: the hand-written
        # shape is scanned for the known numbers; that number (53, a connection
        # failure) must beat a template that starts the message
        for message in (
            "Login timeout expired after native error 53 happened",
            "Query timeout expired (10060) while working; retry",
        ):
            with self.subTest(message=message):
                details = classify_pyodbc_error(pyodbc.Error("42000", message))
                self.assertEqual(details.code, SqlErrorCode.CONNECTION_FAILED)
                self.assertIn(details.native_code, (53, 10060))
        # positive control: the same template without any number is a timeout
        self.assertEqual(
            classify_pyodbc_error(
                pyodbc.Error("42000", "Login timeout expired after it happened")
            ).code,
            SqlErrorCode.TIMEOUT,
        )

    def test_a_number_in_another_record_outranks_the_fallback_text_of_a_record(self):
        prefix = "[42000] " + self.PREFIX
        timeout_record = f"{prefix}Login timeout expired (0)"
        for number, expected in (
            (229, SqlErrorCode.PERMISSION_DENIED),
            (262, SqlErrorCode.PERMISSION_DENIED),
            (4060, SqlErrorCode.DATABASE_MISSING),
            (18456, SqlErrorCode.AUTHENTICATION_FAILED),
        ):
            with self.subTest(number=number):
                details = classify_pyodbc_error(
                    pyodbc.Error(
                        "42000",
                        f"{timeout_record}; {prefix}Failed for user {number} "
                        f"({number}) (SQLExecDirectW)",
                    )
                )
                self.assertEqual(details.code, expected)
                self.assertEqual(details.native_code, number)

    def test_multi_record_text_is_anchored_per_record(self):
        prefix = "[08001] " + self.PREFIX
        # the timeout record starts its own message: anchored fallback applies
        started = classify_pyodbc_error(
            pyodbc.Error(
                "08001",
                f"{prefix}Could not open a connection to SQL Server [53]. (53) "
                f"(SQLDriverConnect); {prefix}Login timeout expired (0)",
            )
        )
        self.assertEqual(started.code, SqlErrorCode.TIMEOUT)
        # the same words in the middle of a record do not
        echoed = classify_pyodbc_error(
            pyodbc.Error(
                "08001",
                f"{prefix}Could not open a connection to SQL Server [53]. (53) "
                f"(SQLDriverConnect); {prefix}Failed for Login timeout expired (0)",
            )
        )
        self.assertEqual(echoed.code, SqlErrorCode.CONNECTION_FAILED)
        self.assertEqual(echoed.native_code, 53)
