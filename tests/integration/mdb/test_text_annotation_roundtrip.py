import math
import tempfile
import unittest
from pathlib import Path
import tests.integration.mdb.text_style_support as access_fixtures


@unittest.skipUnless(
    access_fixtures._access_available(), "Access driver/DAO unavailable"
)
class TextAnnotationAccessRoundtripTests(unittest.TestCase):
    def test_create_edit_reload_precision_and_failed_batch_rollback(self):
        # Access has a process-wide client-task ceiling; follow the existing
        # live-MDB style test's isolated-process contract.
        import os
        import subprocess
        import sys

        if os.environ.get("OSTV_ANNOTATION_ACCESS_CHILD") != "1":
            environment = dict(os.environ, OSTV_ANNOTATION_ACCESS_CHILD="1")
            result = subprocess.run(
                [
                    sys.executable,
                    "-X",
                    "faulthandler",
                    "-m",
                    "unittest",
                    "tests." + self.id().removeprefix("tests."),
                ],
                capture_output=True,
                text=True,
                timeout=120,
                env=environment,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            return
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as directory:
            path = Path(directory) / "text-lifecycle.mdb"
            self.assertTrue(
                access_fixtures.DatabaseCreator().create_database(
                    path, "Text lifecycle"
                )
            )
            connections = access_fixtures.MdbConnectionManager()
            writer = access_fixtures.MdbWriter(connections)
            reader = access_fixtures.MdbReader(connections)
            try:
                bid = writer.create_bid(
                    str(path),
                    None,
                    {
                        "job_name": "Text",
                        "pages": [
                            {
                                "name": "Page",
                                "width": 42.0,
                                "height": 30.0,
                                "scale_factor1": 1.0,
                                "scale_factor2": 1.0,
                            }
                        ],
                    },
                )
                connection = access_fixtures.pyodbc.connect(
                    f"DRIVER={{{access_fixtures._ACCESS_DRIVER}}};DBQ={path};",
                    autocommit=True,
                )
                try:
                    page = str(
                        connection.cursor()
                        .execute("SELECT UID FROM BidPages WHERE BidUID=?", bid)
                        .fetchone()[0]
                    )
                finally:
                    connection.close()
                position = [1 / 64, -1 / 25.4, 80.123456, 24.654321, math.pi / 7]
                properties = {
                    "Text": "  caf\u00e9\t'quoted'\nnext line  \n",
                    "FontName": "Arial",
                    "FontSize": 37,
                    "FontColor": 0x563412,
                    "FontBold": True,
                    "FontItalic": True,
                    "FontUnderline": True,
                    "TextAlign": 2,
                }
                specs = [
                    access_fixtures.InsertAnnotationSpec(
                        page_uid=page,
                        annotation_type="text",
                        position=list(position),
                        color="#123456",
                        width=0,
                        properties=dict(properties),
                    )
                    for _ in range(2)
                ]
                uids = writer.insert_annotations(str(path), bid, specs)
                self.assertEqual(len(uids), 2)
                connections.close_database(str(path))
                annotations = [
                    item
                    for item in reader.get_bid_data(str(path), bid)[6]
                    if item.is_text
                ]
                self.assertEqual(len(annotations), 2)
                for item in annotations:
                    self.assertEqual(item.position, position)
                    self.assertEqual(item.properties, properties)
                    self.assertEqual(item.page_uid, page)
                # Failure on the second member must roll back the first update.
                self.assertFalse(
                    writer.save_annotation_text_properties(
                        str(path),
                        [
                            (uids[0], "text", {**properties, "Text": "Changed first"}),
                            (uids[1], "text", {**properties, "Text": "\U0001f600"}),
                        ],
                    )
                )
                connections.close_database(str(path))
                annotations = [
                    item
                    for item in reader.get_bid_data(str(path), bid)[6]
                    if item.is_text
                ]
                self.assertEqual(
                    [item.properties for item in annotations], [properties, properties]
                )
                self.assertTrue(
                    writer.save_annotation_text_properties(
                        str(path), [(uids[0], "text", {**properties, "Text": "Retry"})]
                    )
                )
                connections.close_database(str(path))
                retried = {
                    str(item.uid): item.properties["Text"]
                    for item in reader.get_bid_data(str(path), bid)[6]
                    if item.is_text
                }
                # Only the retried member changed; the other keeps its text.
                self.assertEqual(
                    retried,
                    {
                        str(uids[0]): "Retry",
                        str(uids[1]): properties["Text"],
                    },
                )
            finally:
                connections.close_database(str(path))
