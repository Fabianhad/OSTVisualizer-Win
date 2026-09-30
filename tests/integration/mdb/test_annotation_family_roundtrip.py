import math
import unittest
from tests.integration.annotations.family_support import (
    AnnotationFamilyGeometry as _family_support_AnnotationFamilyGeometry,
)


class AnnotationFamilyAccessTests(unittest.TestCase):
    def test_all_families_real_access_save_reload_and_batch_rollback(self):
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
        import tempfile
        from pathlib import Path
        import tests.integration.mdb.text_style_support as fixtures
        from ost_visualizer.domain.entities.named_view import (
            normalize_named_view_position,
        )

        if not fixtures._access_available():
            self.skipTest("Access driver/DAO unavailable")
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as directory:
            path = Path(directory) / "annotation-families.mdb"
            self.assertTrue(
                fixtures.DatabaseCreator().create_database(path, "Annotation audit")
            )
            connections = fixtures.MdbConnectionManager()
            writer = fixtures.MdbWriter(connections)
            reader = fixtures.MdbReader(connections)
            try:
                bid = writer.create_bid(
                    str(path),
                    None,
                    {
                        "job_name": "Families",
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
                conn = fixtures.pyodbc.connect(
                    f"DRIVER={{{fixtures._ACCESS_DRIVER}}};DBQ={path};", autocommit=True
                )
                try:
                    page = str(
                        conn.cursor()
                        .execute("SELECT UID FROM BidPages WHERE BidUID=?", bid)
                        .fetchone()[0]
                    )
                finally:
                    conn.close()
                expected = {
                    kind: (
                        normalize_named_view_position(pos)
                        if kind == "namedview"
                        else list(pos)
                    )
                    for kind, pos in _family_support_AnnotationFamilyGeometry.POSITIONS.items()
                }
                specs = [
                    fixtures.InsertAnnotationSpec(
                        page_uid=page,
                        annotation_type=kind,
                        position=list(pos),
                        color="#123456",
                        width=2.0,
                        properties={
                            "Text": "caf\u00e9",
                            "FontName": "Arial",
                            "FontSize": 17,
                            "FontColor": 0x563412,
                            "FontBold": True,
                            "FontItalic": True,
                            "FontUnderline": True,
                            "TextAlign": 2,
                        },
                    )
                    for kind, pos in expected.items()
                ]
                uids = writer.insert_annotations(str(path), bid, specs)
                self.assertEqual(len(uids), len(specs))

                def reload():
                    connections.close_database(str(path))
                    return {
                        a.annotation_type: a
                        for a in reader.get_bid_data(str(path), bid)[6]
                    }

                loaded = reload()
                self.assertEqual(set(loaded), set(expected))
                for kind, pos in expected.items():
                    with self.subTest(kind=kind):
                        self.assertEqual(loaded[kind].position, pos)
                        self.assertEqual(loaded[kind].page_uid, page)
                        self.assertEqual(loaded[kind].color.upper(), "#123456")
                updates = [
                    (loaded[kind].uid, kind, list(pos))
                    for kind, pos in expected.items()
                ]
                self.assertTrue(writer.save_annotation_positions(str(path), updates))
                self.assertEqual(
                    {kind: a.position for kind, a in reload().items()}, expected
                )
                # Missing member must reject the entire transaction.
                self.assertFalse(
                    writer.save_annotation_positions(
                        str(path),
                        [
                            (
                                loaded["dimension"].uid,
                                "dimension",
                                [1.0, 2.0, 3.0, 4.0],
                            ),
                            ("999999", "ink", [1.0, 2.0, 3.0, 4.0]),
                        ],
                    )
                )
                self.assertEqual(
                    {kind: a.position for kind, a in reload().items()}, expected
                )
                keys = [(a.uid, a.annotation_type) for a in loaded.values()]
                self.assertTrue(writer.delete_annotations(str(path), keys))
                self.assertEqual(reload(), {})
            finally:
                connections.close_database(str(path))
