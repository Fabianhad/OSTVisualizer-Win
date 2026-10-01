import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from ost_visualizer.infrastructure.mdb.connection_manager import MdbConnectionManager
from ost_visualizer.infrastructure.mdb.database_maintenance import (
    MdbDatabaseMaintenance,
    _table_counts,
)
from PySide6 import QtCore, QtGui, QtTest, QtWidgets


class AccessMaintenanceOwnershipTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def test_capture_reserves_closed_handles_until_cancelled(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "db.mdb"
            source.write_bytes(b"original")
            manager = MdbConnectionManager()
            backend = MdbDatabaseMaintenance(manager)
            identity = backend.capture_target(str(source))
            try:
                for mode in (True, False):
                    with self.assertRaisesRegex(RuntimeError, "maintenance"):
                        with manager.connection(str(source), autocommit=mode):
                            self.fail("confirmation reopened an MDB connection")
                self.assertTrue(backend.is_target_current(str(source), identity))
                with self.assertRaisesRegex(RuntimeError, "active operations"):
                    backend.capture_target(str(source))
            finally:
                backend.release_target(str(source), identity)
            backend.release_target(str(source), identity)
            self.assertFalse(manager._maintenance_paths)
            self.assertFalse(backend.is_target_current(str(source), identity))
            replacement = backend.capture_target(str(source))
            backend.release_target(str(source), replacement)
            self.assertFalse(manager._maintenance_paths)

    def test_replacement_during_handle_release_is_not_adopted(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "db.mdb"
            source.write_bytes(b"original")
            replacement = source.with_suffix(".replacement")
            replacement.write_bytes(b"replacement")
            manager = MdbConnectionManager()
            writer = Mock()
            writer.close.side_effect = lambda: os.replace(replacement, source)
            manager._write_conns[os.path.normcase(str(source))] = writer
            with self.assertRaisesRegex(RuntimeError, "selected database changed"):
                MdbDatabaseMaintenance(manager).capture_target(str(source))
            self.assertFalse(manager._maintenance_paths)
            self.assertFalse(manager._write_conns)
            self.assertEqual(source.read_bytes(), b"replacement")

    def test_staging_holds_leases_until_commit_or_discard(self):
        for failure in ("fsync", "replace", "partial_replace", "restore", "none"):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as folder:
                source = Path(folder) / "db.mdb"
                source.write_bytes(b"original")
                manager = MdbConnectionManager()
                engine = Mock()
                engine.CompactDatabase.side_effect = lambda _src, dst: Path(
                    dst
                ).write_bytes(b"compacted")
                real_rename = os.rename

                def replace(src, dst, backup):
                    if failure in ("partial_replace", "restore"):
                        real_rename(src, backup)
                    if failure != "none":
                        raise OSError("replacement failure")
                    real_rename(src, backup)
                    real_rename(dst, src)

                def rename(src, dst):
                    if failure == "restore":
                        raise OSError("recovery blocked")
                    real_rename(src, dst)

                with patch(
                    "ost_visualizer.infrastructure.mdb.database_maintenance.win32com.client.Dispatch",
                    return_value=engine,
                ), patch(
                    "ost_visualizer.infrastructure.mdb.database_maintenance._table_counts",
                    return_value={"Data": 1},
                ), patch(
                    "ost_visualizer.infrastructure.mdb.database_maintenance.os.fsync",
                    side_effect=OSError("fsync") if failure == "fsync" else None,
                ), patch(
                    "ost_visualizer.infrastructure.mdb.database_maintenance._replace_file",
                    replace,
                ), patch(
                    "ost_visualizer.infrastructure.mdb.database_maintenance.os.rename",
                    rename,
                ):
                    backend = MdbDatabaseMaintenance(manager)
                    if failure == "fsync":
                        with self.assertRaises(OSError):
                            backend.prepare(
                                str(source), backend.capture_target(str(source))
                            )
                    else:
                        staged = backend.prepare(
                            str(source), backend.capture_target(str(source))
                        )
                        try:
                            self.assertEqual(source.read_bytes(), b"original")
                            with self.assertRaisesRegex(RuntimeError, "maintenance"):
                                with manager.connection(str(source)):
                                    self.fail("lease escaped staging exclusion")
                            if failure == "none":
                                self.assertTrue(staged.commit().success)
                            else:
                                with self.assertRaises((OSError, RuntimeError)):
                                    staged.commit()
                        finally:
                            staged.close()
                self.assertFalse(manager._maintenance_paths)
                if failure == "restore":
                    backups = list(Path(folder).glob(".ost-compact-*/original.backup"))
                    self.assertEqual(len(backups), 1)
                    self.assertEqual(backups[0].read_bytes(), b"original")
                else:
                    self.assertEqual(
                        source.read_bytes(),
                        b"compacted" if failure == "none" else b"original",
                    )
                    self.assertEqual(list(Path(folder).iterdir()), [source])

    def test_last_moment_external_write_is_not_lost(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "db.mdb"
            source.write_bytes(b"original")
            manager = MdbConnectionManager()
            engine = Mock()
            engine.CompactDatabase.side_effect = lambda _src, dst: Path(
                dst
            ).write_bytes(b"compacted")
            calls = []

            def replace(src, dst, backup):
                if not calls:
                    source.write_bytes(b"newer external data")
                calls.append(True)
                os.rename(src, backup)
                os.rename(dst, src)

            with patch(
                "ost_visualizer.infrastructure.mdb.database_maintenance.win32com.client.Dispatch",
                return_value=engine,
            ), patch(
                "ost_visualizer.infrastructure.mdb.database_maintenance._table_counts",
                return_value={"Data": 1},
            ), patch(
                "ost_visualizer.infrastructure.mdb.database_maintenance._replace_file",
                replace,
            ):
                with self.assertRaisesRegex(RuntimeError, "changed"):
                    MdbDatabaseMaintenance(manager).compact(str(source))
            self.assertEqual(source.read_bytes(), b"newer external data")
            self.assertEqual(list(Path(folder).iterdir()), [source])
            self.assertFalse(manager._maintenance_paths)

    def test_unavailable_reason_reports_blocked_missing_and_non_mdb_targets(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "db.mdb"
            source.write_bytes(b"original")
            other = Path(folder) / "db.accdb"
            other.write_bytes(b"original")
            manager = MdbConnectionManager()
            backend = MdbDatabaseMaintenance(manager)
            self.assertEqual(backend.unavailable_reason(str(source)), "")
            self.assertEqual(
                backend.unavailable_reason(str(Path(folder) / "missing.mdb")),
                "Select an existing Microsoft Access MDB database.",
            )
            self.assertEqual(
                backend.unavailable_reason(str(other)),
                "Select an existing Microsoft Access MDB database.",
            )
            manager.set_write_blocked(True)
            self.assertEqual(
                backend.unavailable_reason(str(source)),
                "Close On-Screen Takeoff before database maintenance.",
            )

    def test_compacted_table_count_mismatch_keeps_original_and_cleans_work(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "db.mdb"
            source.write_bytes(b"original")
            manager = MdbConnectionManager()
            engine = Mock()
            engine.CompactDatabase.side_effect = lambda _src, dst: Path(
                dst
            ).write_bytes(b"compacted")
            with patch(
                "ost_visualizer.infrastructure.mdb.database_maintenance.win32com.client.Dispatch",
                return_value=engine,
            ), patch(
                "ost_visualizer.infrastructure.mdb.database_maintenance._table_counts",
                side_effect=[{"Data": 2}, {"Data": 1}],
            ):
                with self.assertRaisesRegex(RuntimeError, "validation failed"):
                    MdbDatabaseMaintenance(manager).compact(str(source))
            self.assertEqual(source.read_bytes(), b"original")
            self.assertEqual(list(Path(folder).iterdir()), [source])
            self.assertFalse(manager._maintenance_paths)

    def test_commit_after_write_block_or_after_success_is_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "db.mdb"
            source.write_bytes(b"original")
            manager = MdbConnectionManager()
            engine = Mock()
            engine.CompactDatabase.side_effect = lambda _src, dst: Path(
                dst
            ).write_bytes(b"compacted")

            def replace(src, dst, backup):
                os.rename(src, backup)
                os.rename(dst, src)

            with patch(
                "ost_visualizer.infrastructure.mdb.database_maintenance.win32com.client.Dispatch",
                return_value=engine,
            ), patch(
                "ost_visualizer.infrastructure.mdb.database_maintenance._table_counts",
                return_value={"Data": 1},
            ), patch(
                "ost_visualizer.infrastructure.mdb.database_maintenance._replace_file",
                replace,
            ):
                backend = MdbDatabaseMaintenance(manager)
                blocked = backend.prepare(
                    str(source), backend.capture_target(str(source))
                )
                try:
                    manager.set_write_blocked(True)
                    with self.assertRaisesRegex(RuntimeError, "interrupted"):
                        blocked.commit()
                    self.assertEqual(source.read_bytes(), b"original")
                finally:
                    blocked.close()
                manager.set_write_blocked(False)
                prepared = backend.prepare(
                    str(source), backend.capture_target(str(source))
                )
                try:
                    self.assertTrue(prepared.commit().success)
                    with self.assertRaisesRegex(RuntimeError, "no longer pending"):
                        prepared.commit()
                finally:
                    prepared.close()
            self.assertEqual(source.read_bytes(), b"compacted")
            self.assertEqual(list(Path(folder).iterdir()), [source])
            self.assertFalse(manager._maintenance_paths)

    def test_table_counts_skips_system_tables_and_rejects_compact_errors(self):
        def table(name, attributes=0):
            return Mock(Name=name, Attributes=attributes)

        def engine_for(tables, counts):
            database = Mock()
            database.TableDefs = tables

            def open_recordset(sql, _kind):
                rows = Mock()
                rows.Fields.return_value.Value = counts[sql]
                return rows

            database.OpenRecordset.side_effect = open_recordset
            engine = Mock()
            engine.OpenDatabase.return_value = database
            return engine, database

        engine, database = engine_for(
            [
                table("MSysObjects"),
                table("MSysCompactError"),
                table("Linked", 0x40000000),
                table("Odd]Name"),
                table("Data"),
            ],
            {
                "SELECT COUNT(*) FROM [MSysCompactError]": 0,
                "SELECT COUNT(*) FROM [Odd]]Name]": 3,
                "SELECT COUNT(*) FROM [Data]": 5,
            },
        )
        self.assertEqual(
            _table_counts(engine, Path("db.mdb")),
            {"Linked": None, "Odd]Name": 3, "Data": 5},
        )
        database.Close.assert_called_once_with()
        engine, database = engine_for(
            [table("MSysCompactError")],
            {"SELECT COUNT(*) FROM [MSysCompactError]": 2},
        )
        with self.assertRaisesRegex(RuntimeError, "repair errors"):
            _table_counts(engine, Path("db.mdb"))
        database.Close.assert_called_once_with()
