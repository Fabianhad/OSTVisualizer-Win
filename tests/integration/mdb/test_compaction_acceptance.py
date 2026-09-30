import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import ntsecuritycon
import pyodbc
import pythoncom
import win32api
import win32com.client
import win32con
import win32security
from ost_visualizer.infrastructure.mdb.connection_manager import MdbConnectionManager
from ost_visualizer.infrastructure.mdb.database_maintenance import (
    MdbDatabaseMaintenance,
)


class AccessCompactionAcceptanceTests(unittest.TestCase):
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
