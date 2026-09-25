import os
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import ntsecuritycon
import pyodbc
import pythoncom
import win32api
import win32com.client
import win32con
import win32security
from ost_visualizer.application.interfaces.i_database_maintenance import (
    DatabaseMaintenanceResult,
)
from ost_visualizer.application.services.database_maintenance_service import (
    DatabaseMaintenanceService,
)
from ost_visualizer.domain.entities.database_descriptor import (
    DatabaseDescriptor,
    SqlServerDatabaseLocation,
)
from ost_visualizer.domain.entities.file_state import FileEntry
from ost_visualizer.infrastructure.database.descriptor_registry import (
    DatabaseDescriptorRegistry,
)
from ost_visualizer.infrastructure.database.maintenance_router import (
    DatabaseMaintenanceRouter,
)
from ost_visualizer.infrastructure.mdb.connection_manager import MdbConnectionManager
from ost_visualizer.infrastructure.mdb.database_maintenance import (
    MdbDatabaseMaintenance,
)
from ost_visualizer.infrastructure.sql.database_maintenance import (
    SqlDatabaseMaintenance,
)
from ost_visualizer.presentation.dialogs.open_files_dialog import OpenFilesDialog
from ost_visualizer.presentation.handlers.file_operation_handler import (
    FileOperationHandler,
)
from PySide6 import QtWidgets
from shiboken6 import delete
from tests.workspace_state_test_support import make_workspace_state_model


class DatabaseMaintenanceTests(unittest.TestCase):
    def test_backend_router_and_explicit_sql_unsupported(self):
        registry = DatabaseDescriptorRegistry()
        descriptor = DatabaseDescriptor.for_sql_server(
            SqlServerDatabaseLocation(
                server="server",
                database="db",
                database_guid="00000000-0000-0000-0000-000000000001",
            ),
            schema_version=1,
        )
        registry.register(descriptor)
        access = Mock()
        router = DatabaseMaintenanceRouter(registry, access, SqlDatabaseMaintenance())
        router.compact("sample.mdb")
        access.compact.assert_called_once_with("sample.mdb")
        result = router.compact(descriptor.database_id)
        self.assertFalse(result.success)
        self.assertIn("not available for SQL Server", result.message)
        self.assertEqual(access.compact.call_count, 1)

    def test_connection_manager_excludes_leases_and_closes_both_pools(self):
        manager = MdbConnectionManager()
        path = os.path.normcase(os.path.abspath("sample.mdb"))
        read, write = Mock(), Mock()
        manager._read_conns[path] = read
        manager._write_conns[path] = write
        with manager.maintenance(path):
            read.close.assert_called_once()
            write.close.assert_called_once()
            for mode in (True, False):
                with self.assertRaisesRegex(RuntimeError, "maintenance"):
                    with manager.connection(path.upper(), autocommit=mode):
                        self.fail("lease granted during maintenance")
            with self.assertRaisesRegex(RuntimeError, "active operations"):
                with manager.maintenance(path):
                    self.fail("overlapping maintenance")
        self.assertFalse(manager._maintenance_paths)
        self.assertFalse(manager._read_conns)
        self.assertFalse(manager._write_conns)

    def test_active_lease_and_failed_close_prevent_maintenance(self):
        manager = MdbConnectionManager()
        path = os.path.normcase(os.path.abspath("sample.mdb"))
        with patch(
            "ost_visualizer.infrastructure.mdb.connection_manager.pyodbc.connect",
            return_value=Mock(),
        ):
            with manager.connection(path):
                with self.assertRaisesRegex(RuntimeError, "active operations"):
                    with manager.maintenance(path):
                        self.fail("active lease compacted")
        conn = manager._read_conns[path]
        conn.close.side_effect = pyodbc.Error("close failed")
        with self.assertRaises(pyodbc.Error):
            with manager.maintenance(path):
                self.fail("failed close permitted maintenance")
        self.assertIs(manager._read_conns[path], conn)
        self.assertFalse(manager._maintenance_paths)

    def test_compaction_and_validation_failure_leave_original_intact(self):
        for failure in ("compact", "validation", "replace"):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as folder:
                source = Path(folder) / "test.mdb"
                source.write_bytes(b"original database contents")
                engine = Mock()

                def compact(_source, destination):
                    Path(destination).write_bytes(b"compacted")
                    if failure == "compact":
                        raise RuntimeError("engine failure")

                engine.CompactDatabase.side_effect = compact
                counts = [{"Data": 2}, {"Data": 1 if failure == "validation" else 2}]
                with patch(
                    "ost_visualizer.infrastructure.mdb.database_maintenance.win32com.client.Dispatch",
                    return_value=engine,
                ), patch(
                    "ost_visualizer.infrastructure.mdb.database_maintenance._table_counts",
                    side_effect=counts,
                ), patch(
                    "ost_visualizer.infrastructure.mdb.database_maintenance._replace_file",
                    side_effect=OSError("replacement failed"),
                ):
                    service = DatabaseMaintenanceService(
                        MdbDatabaseMaintenance(MdbConnectionManager()), Mock(), Mock()
                    )
                    result = service.compact(str(source))
                self.assertFalse(result.success)
                self.assertEqual(source.read_bytes(), b"original database contents")
                self.assertEqual(list(Path(folder).iterdir()), [source])

    def test_source_change_during_compaction_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "test.mdb"
            source.write_bytes(b"original")
            engine = Mock()

            def compact(_source, destination):
                Path(destination).write_bytes(b"compacted")
                source.write_bytes(b"newer external contents")

            engine.CompactDatabase.side_effect = compact
            with patch(
                "ost_visualizer.infrastructure.mdb.database_maintenance.win32com.client.Dispatch",
                return_value=engine,
            ), patch(
                "ost_visualizer.infrastructure.mdb.database_maintenance._table_counts",
                return_value={"Data": 1},
            ):
                result = DatabaseMaintenanceService(
                    MdbDatabaseMaintenance(MdbConnectionManager()), Mock(), Mock()
                ).compact(str(source))
            self.assertFalse(result.success)
            self.assertEqual(source.read_bytes(), b"newer external contents")

    def test_duplicate_operation_and_main_thread_refresh(self):
        backend, files, events = Mock(), Mock(), Mock()
        backend.unavailable_reason.return_value = ""
        service = DatabaseMaintenanceService(backend, files, events)
        overlapping = []

        def compact(_locator):
            overlapping.append(service.compact("db.mdb"))
            return DatabaseMaintenanceResult(True, "done")

        backend.compact.side_effect = compact
        self.assertFalse(service.compact("").success)
        self.assertTrue(service.compact("db.mdb").success)
        self.assertFalse(overlapping[0].success)
        backend.compact.assert_called_once()
        files.is_loaded.return_value = True
        files.data_service.get_hierarchy.return_value.loaded_files = [
            SimpleNamespace(file_path="db.mdb")
        ]
        files.reload_database.return_value.success = True
        self.assertTrue(service.refresh_loaded_database("db.mdb", Mock()).success)
        files.reload_database.assert_called_once_with("db.mdb")
        events.publish.assert_called_once()

    def test_real_access_compaction_preserves_data_reclaims_space_and_reconnects(self):
        pythoncom.CoInitialize()
        try:
            try:
                engine = win32com.client.Dispatch("DAO.DBEngine.120")
            except pythoncom.com_error as exc:
                self.skipTest(f"Access DAO unavailable: {exc.hresult}")
            with tempfile.TemporaryDirectory() as folder:
                source = Path(folder) / "fixture.mdb"
                database = engine.CreateDatabase(
                    str(source), ";LANGID=0x0409;CP=1252;COUNTRY=0", 64
                )
                database.Execute(
                    "CREATE TABLE SurvivingData (UID INTEGER, Payload MEMO)"
                )
                payload = "data" * 4000
                for uid in range(180):
                    database.Execute(
                        f"INSERT INTO SurvivingData VALUES ({uid}, '{payload}')"
                    )
                database.Execute("DELETE FROM SurvivingData WHERE UID >= 3")
                database.Execute(
                    "CREATE UNIQUE INDEX SurvivingUID ON SurvivingData (UID)"
                )
                database.Execute(
                    "CREATE TABLE Payloads (UID LONG CONSTRAINT PayloadPK PRIMARY KEY, ParentUID INTEGER, Identifier GUID, Position LONGBINARY)"
                )
                database.Execute(
                    "ALTER TABLE Payloads ADD CONSTRAINT ParentFK FOREIGN KEY (ParentUID) REFERENCES SurvivingData (UID)"
                )
                database.Close()
                blob = (
                    b'<Legends><Legend dX="123.456" dY="789.012" /></Legends>'
                    + bytes(range(256))
                )
                guid = "01234567-89AB-CDEF-0123-456789ABCDEF"
                with pyodbc.connect(
                    "DRIVER={Microsoft Access Driver (*.mdb, *.accdb)};DBQ="
                    + str(source),
                    autocommit=True,
                ) as connection:
                    connection.execute(
                        "INSERT INTO Payloads VALUES (?, ?, ?, ?)",
                        10,
                        1,
                        guid,
                        pyodbc.Binary(blob),
                    )
                connection.close()
                token = win32security.OpenProcessToken(
                    win32api.GetCurrentProcess(), win32con.TOKEN_QUERY
                )
                try:
                    sid = win32security.GetTokenInformation(
                        token, win32security.TokenUser
                    )[0]
                finally:
                    token.Close()
                acl = win32security.ACL()
                acl.AddAccessAllowedAce(
                    win32security.ACL_REVISION, ntsecuritycon.FILE_ALL_ACCESS, sid
                )
                security = win32security.SECURITY_DESCRIPTOR()
                security.SetSecurityDescriptorDacl(True, acl, False)
                win32security.SetFileSecurity(
                    str(source),
                    win32security.DACL_SECURITY_INFORMATION
                    | win32security.PROTECTED_DACL_SECURITY_INFORMATION,
                    security,
                )
                before_acl = win32security.GetFileSecurity(
                    str(source), win32security.DACL_SECURITY_INFORMATION
                ).GetSecurityDescriptorDacl()
                manager = MdbConnectionManager()
                try:
                    for mode in (True, False):
                        with manager.connection(
                            str(source), autocommit=mode
                        ) as connection:
                            with connection.cursor() as cursor:
                                cursor.execute("SELECT COUNT(*) FROM SurvivingData")
                                self.assertEqual(cursor.fetchone()[0], 3)
                                if not mode:
                                    cursor.execute(
                                        "UPDATE SurvivingData SET Payload = ? WHERE UID = 0",
                                        (payload,),
                                    )
                                    connection.commit()
                    before = source.stat().st_size
                    self.assertTrue(
                        MdbDatabaseMaintenance(manager).compact(str(source)).success
                    )
                    after_acl = win32security.GetFileSecurity(
                        str(source), win32security.DACL_SECURITY_INFORMATION
                    ).GetSecurityDescriptorDacl()
                    self.assertEqual(
                        [after_acl.GetAce(i) for i in range(after_acl.GetAceCount())],
                        [before_acl.GetAce(i) for i in range(before_acl.GetAceCount())],
                    )
                    after = source.stat().st_size
                    self.assertLess(after, before)
                    with manager.connection(str(source)) as connection:
                        with connection.cursor() as cursor:
                            cursor.execute(
                                "SELECT UID, Payload FROM SurvivingData ORDER BY UID"
                            )
                            rows = cursor.fetchall()
                            cursor.execute(
                                "SELECT UID, ParentUID, Identifier, Position FROM Payloads"
                            )
                            restored = cursor.fetchone()
                            self.assertEqual((restored[0], restored[1]), (10, 1))
                            self.assertEqual(str(restored[2]).strip("{}").upper(), guid)
                            self.assertEqual(bytes(restored[3]), blob)
                    manager.close()
                    metadata = engine.OpenDatabase(str(source), True, True)
                    try:
                        self.assertIn(
                            "SurvivingUID",
                            [
                                index.Name
                                for index in metadata.TableDefs("SurvivingData").Indexes
                            ],
                        )
                        self.assertIn(
                            "ParentFK",
                            [relation.Name for relation in metadata.Relations],
                        )
                    finally:
                        metadata.Close()
                    self.assertEqual(
                        [(row[0], row[1]) for row in rows],
                        [(i, payload) for i in range(3)],
                    )
                    print(
                        f"Access compact fixture: {before} -> {after} bytes; all 3 surviving payloads intact"
                    )
                finally:
                    manager.close()
        finally:
            pythoncom.CoUninitialize()


class DatabaseMaintenanceUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def test_sql_result_is_explicit_and_access_denial_is_inert(self):
        host = QtWidgets.QWidget()
        registry = DatabaseDescriptorRegistry()
        descriptor = DatabaseDescriptor.for_sql_server(
            SqlServerDatabaseLocation(
                server="server",
                database="db",
                database_guid="00000000-0000-0000-0000-000000000001",
            ),
            schema_version=1,
        )
        registry.register(descriptor)
        access = Mock()
        service = DatabaseMaintenanceService(
            DatabaseMaintenanceRouter(registry, access, SqlDatabaseMaintenance()),
            Mock(),
            Mock(),
        )
        handler = FileOperationHandler(
            host,
            Mock(),
            Mock(),
            Mock(),
            Mock(),
            Mock(),
            Mock(),
            Mock(),
            Mock(),
            Mock(),
            Mock(),
            make_workspace_state_model(),
            database_maintenance_service=service,
        )
        handler._ui_access_manager.can_maintain_database.return_value = True
        dialog = OpenFilesDialog(
            Mock(),
            host,
            [FileEntry(descriptor=descriptor)],
            Mock(),
            make_workspace_state_model(),
            maintenance_allowed_fn=handler._maintenance_allowed,
        )
        try:
            dialog.table.setCurrentItem(dialog.table.topLevelItem(0))
            dialog.maintenance_requested.connect(
                lambda entry: handler._compact_database(dialog, entry)
            )
            with patch(
                "ost_visualizer.presentation.handlers.file_operation_handler.show_warning"
            ) as warning:
                dialog.compact_button.click()
                warning.assert_called_once()
                self.assertIn("not available for SQL Server", warning.call_args.args[2])
            access.compact.assert_not_called()
            handler._ui_access_manager.can_maintain_database.return_value = False
            dialog._update_remove_button_state()
            self.assertFalse(dialog.compact_button.isEnabled())
            with patch(
                "ost_visualizer.presentation.handlers.file_operation_handler.show_warning"
            ) as warning:
                dialog._on_compact()
                warning.assert_not_called()
        finally:
            dialog.cleanup()
            delete(host)

    def test_actions_and_single_result_without_rebuilding_selection(self):
        for succeeds in (True, False):
            with self.subTest(succeeds=succeeds):
                host = QtWidgets.QWidget()
                service = Mock()
                service.unavailable_reason.return_value = ""
                service.finish.return_value = DatabaseMaintenanceResult(
                    succeeds, "result"
                )
                handler = FileOperationHandler(
                    host,
                    Mock(),
                    Mock(),
                    Mock(),
                    Mock(),
                    Mock(),
                    Mock(),
                    Mock(),
                    Mock(),
                    Mock(),
                    Mock(),
                    make_workspace_state_model(),
                    database_maintenance_service=service,
                )
                handler._ui_access_manager.can_maintain_database.return_value = True
                handler._deferred_persistence.flush_for_file.return_value = True
                dialog = OpenFilesDialog(
                    Mock(),
                    host,
                    [FileEntry(file_path="test.mdb")],
                    Mock(),
                    make_workspace_state_model(),
                    maintenance_allowed_fn=handler._maintenance_allowed,
                )
                try:
                    self.assertEqual(
                        dialog.findChild(QtWidgets.QGroupBox).title(),
                        "Database Actions",
                    )
                    self.assertFalse(dialog.compact_button.isEnabled())
                    dialog.compact_button.click()
                    service.compact.assert_not_called()
                    item = dialog.table.topLevelItem(0)
                    dialog.table.setCurrentItem(item)
                    self.assertTrue(dialog.compact_button.isEnabled())
                    dialog.maintenance_requested.connect(
                        lambda entry: handler._compact_database(dialog, entry)
                    )

                    def exec_progress(progress):
                        dialog.compact_button.click()
                        progress._result = progress._task_fn()
                        return QtWidgets.QDialog.DialogCode.Accepted

                    with patch(
                        "ost_visualizer.presentation.handlers.file_operation_handler.confirm",
                        return_value=True,
                    ), patch(
                        "ost_visualizer.presentation.handlers.file_operation_handler.ProgressDialog.exec",
                        exec_progress,
                    ), patch(
                        "ost_visualizer.presentation.handlers.file_operation_handler.show_info"
                    ) as info, patch(
                        "ost_visualizer.presentation.handlers.file_operation_handler.show_warning"
                    ) as warning:
                        dialog.compact_button.click()
                    service.prepare.assert_called_once_with(
                        service.capture_target.return_value
                    )
                    service.finish.assert_called_once_with(
                        service.capture_target.return_value,
                        service.prepare.return_value,
                        handler._unload_file_fn,
                    )
                    self.assertEqual(info.call_count, int(succeeds))
                    self.assertEqual(warning.call_count, int(not succeeds))
                    self.assertIs(dialog.table.currentItem(), item)
                    self.assertTrue(dialog.compact_button.isEnabled())
                    self.assertFalse(handler._file_operation_pending)
                finally:
                    dialog.cleanup()
                    delete(host)


if __name__ == "__main__":
    unittest.main()
