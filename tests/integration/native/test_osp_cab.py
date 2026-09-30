import os
import shutil
import struct
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path, PureWindowsPath
from ost_visualizer.infrastructure.mdb.importers import (
    osp_importer as osp_importer_module,
)
from ost_visualizer.infrastructure.mdb.importers.osp_importer import OspImporter
from tests.helpers.import_workflow import (
    FakeImporter as _import_workflow_FakeImporter,
    InspectingImporter as _import_workflow_InspectingImporter,
    _write_legacy_ansi_cab as _import_workflow__write_legacy_ansi_cab,
    _write_osp_page_xml_text as _import_workflow__write_osp_page_xml_text,
)


class OspNativeCabImportTests(unittest.TestCase):
    def test_osp_imports_legacy_ansi_members_from_unicode_archive_path(self):
        project_name = "26-061 412 – Corporate Lot K, KS"
        ost_member = f"{project_name}.ost"
        image_member = (
            "TempImages!.tmp\\1 Estimates through 1-12-2015\\2026\\"
            f"{project_name}\\01. Drawings\\A0-0.0.pdf"
        )
        source_image_path = (
            "Q:\\1 Estimates through 1-12-2015\\2026\\"
            f"{project_name}\\01. Drawings\\A0-0.0.pdf"
        )
        ost_xml = _import_workflow__write_osp_page_xml_text(source_image_path).encode(
            "utf-8"
        )
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            osp_path = tmp_path / f"{project_name}.osp"
            _import_workflow__write_legacy_ansi_cab(
                osp_path,
                [(ost_member, ost_xml), (image_member, b"%PDF-1.4 fixture")],
            )
            self.assertEqual(
                list(osp_importer_module.ost_cab.list_cab(str(osp_path))),
                [ost_member, image_member],
            )
            working_dir = tmp_path / "working"
            original_working_dir = osp_importer_module.get_default_working_dir
            osp_importer_module.get_default_working_dir = lambda: working_dir
            try:
                mdb_importer = _import_workflow_InspectingImporter()
                self.assertTrue(
                    OspImporter(mdb_importer).import_osp(
                        str(osp_path), "target.mdb", "project-1"
                    )
                )
                sql_importer = _import_workflow_InspectingImporter()
                recorder = object()
                self.assertEqual(
                    OspImporter(sql_importer).import_osp_mutation(
                        str(osp_path), "target.sql", "project-1", recorder
                    ),
                    {"bid_uids": {"source": "target"}},
                )
            finally:
                osp_importer_module.get_default_working_dir = original_working_dir
            self.assertEqual(
                mdb_importer.imported_image_contents[0], b"%PDF-1.4 fixture"
            )
            self.assertEqual(
                sql_importer.imported_image_contents[0], b"%PDF-1.4 fixture"
            )
            self.assertEqual(mdb_importer.calls[0][0], "ost")
            self.assertEqual(sql_importer.calls[0][0], "ost_mutation")

    def test_invalid_osp_stops_before_mdb_or_sql_import_mutation(self):
        with tempfile.TemporaryDirectory() as tmp:
            osp_path = Path(tmp) / "invalid – package.osp"
            _import_workflow__write_legacy_ansi_cab(
                osp_path, [("not-a-project.txt", b"invalid")]
            )
            importer = _import_workflow_FakeImporter()
            osp_importer = OspImporter(importer)
            with self.assertLogs(osp_importer_module.logger, level="ERROR"):
                self.assertFalse(
                    osp_importer.import_osp(str(osp_path), "target.mdb", "project-1")
                )
            with self.assertRaisesRegex(ValueError, "exactly one top-level .ost file"):
                osp_importer.import_osp_mutation(
                    str(osp_path), "target.sql", "project-1", object()
                )
            self.assertEqual(importer.calls, [])

    def test_native_cab_round_trip_preserves_utf8_paths_and_member_names(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            source_path = tmp_path / "source – drawing.pdf"
            source_path.write_bytes(b"%PDF-1.4 unicode")
            osp_path = tmp_path / "export – project.osp"
            member_name = "TempImages!.tmp\\source – drawing.pdf"
            self.assertTrue(
                osp_importer_module.ost_cab.create_cab_with_names(
                    [str(source_path)], [member_name], str(osp_path)
                )
            )
            self.assertEqual(
                list(osp_importer_module.ost_cab.list_cab(str(osp_path))),
                [member_name],
            )
            extract_path = tmp_path / "extracted – project"
            (extract_path / "TempImages!.tmp").mkdir(parents=True)
            self.assertTrue(
                osp_importer_module.ost_cab.extract_cab(
                    str(osp_path), str(extract_path)
                )
            )
            self.assertEqual(
                (
                    extract_path / "TempImages!.tmp" / "source – drawing.pdf"
                ).read_bytes(),
                b"%PDF-1.4 unicode",
            )

    @unittest.skipUnless(os.name == "nt", "Windows CAB path behavior")
    def test_native_cab_resolves_identical_members_from_long_local_paths(self):
        member_names = ["Project name; 50% (CD).OST", "BidTrans.xml"]
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            local_osp = tmp_path / "Package name; spaces (local).osp"
            _import_workflow__write_legacy_ansi_cab(
                local_osp,
                [(member_names[0], b"<XML_ROOT />"), (member_names[1], b"<XML />")],
            )
            long_parent = tmp_path
            segment_index = 0
            while len(str(long_parent / local_osp.name)) < 300:
                long_parent /= (
                    f"network-style segment {segment_index}; spaces (punctuation)"
                )
                segment_index += 1
            extended_long_parent = Path("\\\\?\\" + str(long_parent))
            extended_long_parent.mkdir(parents=True)
            extended_long_osp = extended_long_parent / local_osp.name
            shutil.copyfile(local_osp, extended_long_osp)
            path_forms = (
                str(local_osp),
                "\\\\?\\" + str(local_osp),
                str(extended_long_osp)[4:],
                str(extended_long_osp),
            )
            expected_package = None
            for source_path in path_forms:
                with self.subTest(source_path=source_path):
                    names = list(osp_importer_module.ost_cab.list_cab(source_path))
                    self.assertEqual(names, member_names)
                    package = osp_importer_module._inspect_package(names)
                    if expected_package is None:
                        expected_package = package
                    self.assertEqual(package, expected_package)
            self.assertEqual(local_osp.read_bytes(), extended_long_osp.read_bytes())

    @unittest.skipUnless(os.name == "nt", "Windows UNC path behavior")
    def test_native_cab_resolves_and_extracts_identically_from_unc_forms(self):
        member_names = ["Project name; 50% (CD).ost", "BidTrans.xml"]
        ost_contents = b"<XML_ROOT />"
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp).resolve()
            local_osp = tmp_path / "Package name; spaces (network).osp"
            _import_workflow__write_legacy_ansi_cab(
                local_osp,
                [(member_names[0], ost_contents), (member_names[1], b"<XML />")],
            )
            long_parent = tmp_path
            segment_index = 0
            while len(str(long_parent / local_osp.name)) < 300:
                long_parent /= (
                    f"network-style segment {segment_index}; spaces (punctuation)"
                )
                segment_index += 1
            extended_long_parent = Path("\\\\?\\" + str(long_parent))
            extended_long_parent.mkdir(parents=True)
            extended_long_osp = extended_long_parent / local_osp.name
            shutil.copyfile(local_osp, extended_long_osp)
            drive_share = f"{tmp_path.drive[0]}$"

            def as_unc(path: Path, *, extended: bool) -> str:
                normal_path = str(path)
                if normal_path.startswith("\\\\?\\"):
                    normal_path = normal_path[4:]
                relative_path = normal_path[len(tmp_path.drive) :]
                prefix = "\\\\?\\UNC\\localhost\\" if extended else "\\\\localhost\\"
                return prefix + drive_share + relative_path

            short_unc = as_unc(local_osp, extended=False)
            if not Path(short_unc).is_file():
                self.skipTest("the local Windows administrative share is unavailable")
            path_forms = (
                str(local_osp),
                short_unc,
                as_unc(local_osp, extended=True),
                as_unc(extended_long_osp, extended=False),
                as_unc(extended_long_osp, extended=True),
            )
            expected_package = None
            for index, source_path in enumerate(path_forms):
                with self.subTest(source_path=source_path):
                    names = list(osp_importer_module.ost_cab.list_cab(source_path))
                    self.assertEqual(names, member_names)
                    package = osp_importer_module._inspect_package(names)
                    if expected_package is None:
                        expected_package = package
                    self.assertEqual(package, expected_package)
                    output_dir = tmp_path / f"extracted {index}; output"
                    output_dir.mkdir()
                    self.assertTrue(
                        osp_importer_module.ost_cab.extract_cab(
                            source_path, str(output_dir)
                        )
                    )
                    self.assertEqual(
                        (output_dir / member_names[0]).read_bytes(), ost_contents
                    )
            self.assertEqual(local_osp.read_bytes(), extended_long_osp.read_bytes())
