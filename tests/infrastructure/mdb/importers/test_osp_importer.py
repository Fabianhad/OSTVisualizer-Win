import hashlib
import tempfile
import unittest
from pathlib import Path, PureWindowsPath
from ost_visualizer.infrastructure.mdb.importers import (
    osp_importer as osp_importer_module,
)
from ost_visualizer.infrastructure.mdb.importers.osp_importer import OspImporter
from tests.helpers.import_workflow import (
    FakeImporter as _import_workflow_FakeImporter,
    FakeOspCab as _import_workflow_FakeOspCab,
    _write_osp_page_xml as _import_workflow__write_osp_page_xml,
    _write_osp_page_xml_text as _import_workflow__write_osp_page_xml_text,
    _write_packaged_image as _import_workflow__write_packaged_image,
)


class _StagedOstRecorder(_import_workflow_FakeImporter):
    def __init__(self):
        super().__init__()
        self.staged = []

    def import_ost(self, source_path, target_path, project_uid=None):
        path = Path(source_path)
        self.staged.append((path, path.is_file(), path.read_text(encoding="utf-8")))
        return super().import_ost(source_path, target_path, project_uid)


class _FailingExtractCab(_import_workflow_FakeOspCab):
    def extract_cab(self, source_path, output_dir):
        self.extract_calls.append(output_dir)
        return False


def _image_members(*member_names):
    return osp_importer_module._inspect_package(
        ["Project.ost", *member_names]
    ).image_members_by_path


class OspImporterImageAndPackageTests(unittest.TestCase):
    def test_osp_import_extracts_cab_with_windows_extended_output_path(self):
        fake_cab = _import_workflow_FakeOspCab()
        importer = _StagedOstRecorder()
        original_cab = osp_importer_module.ost_cab
        try:
            osp_importer_module.ost_cab = fake_cab
            self.assertTrue(
                OspImporter(importer).import_osp(
                    "source.osp", "target.mdb", "project-1"
                )
            )
        finally:
            osp_importer_module.ost_cab = original_cab
        self.assertEqual(len(fake_cab.extract_calls), 1)
        if osp_importer_module.os.name == "nt":
            self.assertTrue(fake_cab.extract_calls[0].startswith("\\\\?\\"))
        self.assertEqual(len(importer.calls), 1)
        self.assertEqual(importer.calls[0][0], "ost")
        self.assertEqual(importer.calls[0][2:], ("target.mdb", "project-1"))
        staged_path, staged_existed, staged_text = importer.staged[0]
        self.assertEqual(staged_path.name, "Project.ost")
        self.assertEqual(staged_path.parent, fake_cab.root)
        self.assertTrue(staged_existed)
        self.assertEqual(staged_text, "<XML_ROOT />")
        self.assertFalse(fake_cab.root.exists())

    def test_osp_import_extraction_failure_fails_import_and_cleans_temp_files(self):
        fake_cab = _FailingExtractCab()
        importer = _import_workflow_FakeImporter()
        original_cab = osp_importer_module.ost_cab
        try:
            osp_importer_module.ost_cab = fake_cab
            with self.assertLogs(osp_importer_module.logger, level="ERROR") as logs:
                result = OspImporter(importer).import_osp(
                    "source.osp", "target.mdb", "project-1"
                )
        finally:
            osp_importer_module.ost_cab = original_cab
        self.assertFalse(result)
        self.assertIn("could not be extracted", "\n".join(logs.output))
        self.assertEqual(importer.calls, [])
        self.assertEqual(len(fake_cab.extract_calls), 1)
        extracted_root = Path(fake_cab._normal_windows_path(fake_cab.extract_calls[0]))
        self.assertFalse(extracted_root.exists())

    def test_osp_import_unexpected_importer_failure_returns_false_and_cleans_temp_files(
        self,
    ):
        class RaisingImporter(_import_workflow_FakeImporter):
            def import_ost(self, source_path, target_path, project_uid=None):
                raise RuntimeError("importer exploded")

        fake_cab = _import_workflow_FakeOspCab()
        original_cab = osp_importer_module.ost_cab
        try:
            osp_importer_module.ost_cab = fake_cab
            with self.assertLogs(osp_importer_module.logger, level="ERROR") as logs:
                result = OspImporter(RaisingImporter()).import_osp(
                    "source.osp", "target.mdb", "project-1"
                )
        finally:
            osp_importer_module.ost_cab = original_cab
        self.assertFalse(result)
        self.assertIn("Unexpected OSP import failure", "\n".join(logs.output))
        self.assertFalse(fake_cab.root.exists())

    def test_osp_mutation_uses_shared_extraction_and_cleans_temp_files(self):
        fake_cab = _import_workflow_FakeOspCab()
        importer = _import_workflow_FakeImporter()
        recorder = object()
        original_cab = osp_importer_module.ost_cab
        try:
            osp_importer_module.ost_cab = fake_cab
            result = OspImporter(importer).import_osp_mutation(
                "source.osp", "target.sql", "project-1", recorder
            )
        finally:
            osp_importer_module.ost_cab = original_cab
        self.assertEqual(result, {"bid_uids": {"source": "target"}})
        self.assertEqual(len(importer.calls), 1)
        self.assertEqual(importer.calls[0][0], "ost_mutation")
        self.assertEqual(importer.calls[0][2:], ("target.sql", "project-1", recorder))
        self.assertFalse(fake_cab.root.exists())

    def test_osp_mutation_propagates_package_errors_and_cleans_temp_files(self):
        original_cab = osp_importer_module.ost_cab
        try:
            invalid = _import_workflow_FakeOspCab(names=["First.ost", "Second.ost"])
            importer = _import_workflow_FakeImporter()
            osp_importer_module.ost_cab = invalid
            with self.assertRaisesRegex(ValueError, "exactly one top-level .ost"):
                OspImporter(importer).import_osp_mutation(
                    "source.osp", "target.sql", "project-1", object()
                )
            self.assertEqual(invalid.extract_calls, [])
            corrupt = _import_workflow_FakeOspCab(ost_xml="<XML_ROOT>")
            osp_importer_module.ost_cab = corrupt
            with self.assertRaises(osp_importer_module.ET.ParseError):
                OspImporter(importer).import_osp_mutation(
                    "source.osp", "target.sql", "project-1", object()
                )
            self.assertFalse(corrupt.root.exists())
        finally:
            osp_importer_module.ost_cab = original_cab
        self.assertEqual(importer.calls, [])

    def test_osp_import_rejects_unsafe_cab_member_paths_before_extraction(self):
        unsafe_names = (
            "..\\outside\\payload.ost",
            "C:\\outside\\payload.ost",
            "\\outside\\payload.ost",
            "\\\\server\\share\\payload.ost",
            "payload.ost:stream",
            "../outside/payload.ost",
            ".",
        )
        original_cab = osp_importer_module.ost_cab
        try:
            for unsafe_name in unsafe_names:
                with self.subTest(member_name=unsafe_name):
                    fake_cab = _import_workflow_FakeOspCab(
                        names=["Project.ost", unsafe_name]
                    )
                    importer = _import_workflow_FakeImporter()
                    osp_importer_module.ost_cab = fake_cab
                    with self.assertLogs(
                        osp_importer_module.logger, level="ERROR"
                    ) as logs:
                        result = OspImporter(importer).import_osp(
                            "source.osp", "target.mdb", "project-1"
                        )
                    self.assertFalse(result)
                    self.assertIn("unsafe CAB member path", "\n".join(logs.output))
                    self.assertEqual(fake_cab.extract_calls, [])
                    self.assertEqual(importer.calls, [])
        finally:
            osp_importer_module.ost_cab = original_cab

    def test_osp_import_requires_exactly_one_top_level_ost_member(self):
        archive_members = (
            ([], "found 0"),
            (["First.ost", "Second.ost"], "found 2"),
            (["nested\\Project.ost"], "found 0"),
        )
        original_cab = osp_importer_module.ost_cab
        try:
            for names, expected_count in archive_members:
                with self.subTest(names=names):
                    fake_cab = _import_workflow_FakeOspCab(names=names)
                    importer = _import_workflow_FakeImporter()
                    osp_importer_module.ost_cab = fake_cab
                    with self.assertLogs(
                        osp_importer_module.logger, level="ERROR"
                    ) as logs:
                        result = OspImporter(importer).import_osp(
                            "source.osp", "target.mdb", "project-1"
                        )
                    self.assertFalse(result)
                    self.assertIn(
                        f"exactly one top-level .ost file; {expected_count}",
                        "\n".join(logs.output),
                    )
                    self.assertEqual(fake_cab.extract_calls, [])
                    self.assertEqual(importer.calls, [])
        finally:
            osp_importer_module.ost_cab = original_cab

    def test_osp_import_cleanup_failure_does_not_fail_successful_import(self):
        fake_cab = _import_workflow_FakeOspCab()
        importer = _import_workflow_FakeImporter()
        original_cab = osp_importer_module.ost_cab
        original_rmtree = osp_importer_module.shutil.rmtree

        def failing_rmtree(_path):
            raise OSError("cleanup blocked")

        try:
            osp_importer_module.ost_cab = fake_cab
            osp_importer_module.shutil.rmtree = failing_rmtree
            with self.assertLogs(osp_importer_module.logger, level="WARNING") as logs:
                self.assertTrue(
                    OspImporter(importer).import_osp(
                        "source.osp", "target.mdb", "project-1"
                    )
                )
        finally:
            osp_importer_module.ost_cab = original_cab
            osp_importer_module.shutil.rmtree = original_rmtree
            if fake_cab.root and fake_cab.root.exists():
                original_rmtree(fake_cab.root)
        self.assertIn(
            "Failed to remove temporary OSP extraction directory",
            "\n".join(logs.output),
        )
        self.assertEqual(len(importer.calls), 1)
        self.assertEqual(importer.calls[0][0], "ost")

    def test_osp_import_uses_short_temp_root_for_long_archive_paths(self):
        if osp_importer_module.os.name != "nt":
            self.skipTest("Windows path length behavior only applies on Windows")
        base_dir = Path(tempfile.mkdtemp(prefix="ostv_test_osp_"))
        long_parent = base_dir / ("long_parent_" * 10)
        short_parent = base_dir / "s"
        long_member = "TempImages!.tmp\\" + "a" * 180 + ".pdf"
        fake_cab = _import_workflow_FakeOspCab(names=["Project.ost", long_member])
        importer = _import_workflow_FakeImporter()
        original_cab = osp_importer_module.ost_cab
        original_candidates = osp_importer_module._extract_temp_parent_candidates
        try:
            osp_importer_module.ost_cab = fake_cab
            osp_importer_module._extract_temp_parent_candidates = lambda: [
                long_parent,
                short_parent,
            ]
            self.assertTrue(
                OspImporter(importer).import_osp(
                    "source.osp", "target.mdb", "project-1"
                )
            )
        finally:
            osp_importer_module.ost_cab = original_cab
            osp_importer_module._extract_temp_parent_candidates = original_candidates
            if base_dir.exists():
                osp_importer_module.shutil.rmtree(base_dir)
        self.assertEqual(len(importer.calls), 1)
        self.assertTrue(str(fake_cab.root).startswith(str(short_parent)))

    def test_osp_import_accepts_nested_legacy_visualizer_layout(self):
        nested_member = "TempImages!.tmp\\generated-folder\\sheet.pdf"
        fake_cab = _import_workflow_FakeOspCab(names=["Project.ost", nested_member])
        importer = _import_workflow_FakeImporter()
        original_cab = osp_importer_module.ost_cab
        try:
            osp_importer_module.ost_cab = fake_cab
            result = OspImporter(importer).import_osp(
                "legacy.osp", "target.mdb", "project-1"
            )
        finally:
            osp_importer_module.ost_cab = original_cab
        self.assertTrue(result)
        self.assertEqual(len(fake_cab.extract_calls), 1)
        self.assertEqual(len(importer.calls), 1)

    def test_osp_import_rejects_unsupported_members_under_temp_images_root(self):
        original_cab = osp_importer_module.ost_cab
        try:
            for member in ("TempImages!.tmp\\notes.txt", "tempimages!.TMP"):
                with self.subTest(member=member):
                    fake_cab = _import_workflow_FakeOspCab(
                        names=["Project.ost", member]
                    )
                    importer = _import_workflow_FakeImporter()
                    osp_importer_module.ost_cab = fake_cab
                    with self.assertLogs(
                        osp_importer_module.logger, level="ERROR"
                    ) as logs:
                        result = OspImporter(importer).import_osp(
                            "legacy.osp", "target.mdb", "project-1"
                        )
                    self.assertFalse(result)
                    self.assertIn(
                        "unsupported member under TempImages!.tmp",
                        "\n".join(logs.output),
                    )
                    self.assertEqual(fake_cab.extract_calls, [])
                    self.assertEqual(importer.calls, [])
        finally:
            osp_importer_module.ost_cab = original_cab

    def test_osp_import_uses_same_flat_lookup_for_original_and_visualizer_paths(self):
        member_name = "TempImages!.tmp\\A00.00.pdf"
        image_paths = (
            "C:\\OCS Documents\\OST\\Project\\A00.00.pdf",
            member_name,
        )
        for source_path in image_paths:
            with self.subTest(
                source_path=source_path
            ), tempfile.TemporaryDirectory() as tmp:
                tmp_path = Path(tmp)
                _import_workflow__write_packaged_image(
                    tmp_path, member_name, b"packaged"
                )
                ost_path = tmp_path / "Project.ost"
                _import_workflow__write_osp_page_xml(ost_path, source_path)
                dest_dir = tmp_path / "dest"
                OspImporter(_import_workflow_FakeImporter())._extract_images(
                    tmp_path,
                    ost_path,
                    dest_dir,
                    _image_members(member_name),
                )
                dest_path = dest_dir / "A00.00.pdf"
                self.assertEqual(dest_path.read_bytes(), b"packaged")
                rewritten = ost_path.read_text(encoding="utf-8")
                self.assertIn(str(dest_path), rewritten)
                self.assertNotIn(source_path, rewritten)

    def test_osp_import_resolves_page_and_overlay_images_from_flat_members(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            page_member = "TempImages!.tmp\\page.pdf"
            overlay_member = "TempImages!.tmp\\overlay.tif"
            _import_workflow__write_packaged_image(tmp_path, page_member, b"page")
            _import_workflow__write_packaged_image(tmp_path, overlay_member, b"overlay")
            ost_path = tmp_path / "Project.ost"
            ost_path.write_text(
                """
                <XML_ROOT><Bid><BidPages><BidPage
                  ImagePath="C:\\plans\\page.pdf"
                  OverlayImagePath="TempImages!.tmp\\overlay.tif"
                /></BidPages></Bid></XML_ROOT>
                """,
                encoding="utf-8",
            )
            dest_dir = tmp_path / "dest"
            OspImporter(_import_workflow_FakeImporter())._extract_images(
                tmp_path,
                ost_path,
                dest_dir,
                _image_members(page_member, overlay_member),
            )
            self.assertEqual((dest_dir / "page.pdf").read_bytes(), b"page")
            self.assertEqual((dest_dir / "overlay.tif").read_bytes(), b"overlay")
            rewritten = ost_path.read_text(encoding="utf-8")
            self.assertIn(str(dest_dir / "page.pdf"), rewritten)
            self.assertIn(str(dest_dir / "overlay.tif"), rewritten)

    def test_osp_import_does_not_overwrite_different_existing_image(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            member_name = "TempImages!.tmp\\sheet.pdf"
            _import_workflow__write_packaged_image(
                tmp_path, member_name, b"new drawing"
            )
            ost_path = tmp_path / "Project.ost"
            _import_workflow__write_osp_page_xml(ost_path, r"C:\plans\sheet.pdf")
            dest_dir = tmp_path / "dest"
            dest_dir.mkdir()
            original_path = dest_dir / "sheet.pdf"
            original_path.write_bytes(b"existing drawing")
            OspImporter(_import_workflow_FakeImporter())._extract_images(
                tmp_path,
                ost_path,
                dest_dir,
                _image_members(member_name),
            )
            self.assertEqual(original_path.read_bytes(), b"existing drawing")
            imported_paths = [
                path for path in dest_dir.glob("sheet-*.pdf") if path.is_file()
            ]
            self.assertEqual(len(imported_paths), 1)
            self.assertEqual(
                imported_paths[0].name,
                f"sheet-{hashlib.sha256(b'new drawing').hexdigest()[:16]}.pdf",
            )
            self.assertEqual(imported_paths[0].read_bytes(), b"new drawing")
            self.assertIn(str(imported_paths[0]), ost_path.read_text(encoding="utf-8"))

    def test_osp_import_reuses_identical_existing_image(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            member_name = "TempImages!.tmp\\sheet.pdf"
            _import_workflow__write_packaged_image(
                tmp_path, member_name, b"same drawing"
            )
            ost_path = tmp_path / "Project.ost"
            _import_workflow__write_osp_page_xml(ost_path, r"C:\plans\sheet.pdf")
            dest_dir = tmp_path / "dest"
            dest_dir.mkdir()
            existing_path = dest_dir / "sheet.pdf"
            existing_path.write_bytes(b"same drawing")
            OspImporter(_import_workflow_FakeImporter())._extract_images(
                tmp_path,
                ost_path,
                dest_dir,
                _image_members(member_name),
            )
            self.assertEqual(list(dest_dir.iterdir()), [existing_path])
            self.assertIn(str(existing_path), ost_path.read_text(encoding="utf-8"))

    def test_osp_import_resolves_most_specific_nested_member_without_overwrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            flat_member = "TempImages!.tmp\\A701-D.pdf"
            nested_member = "TempImages!.tmp\\estimates\\project\\drawings\\A701-D.pdf"
            _import_workflow__write_packaged_image(tmp_path, flat_member, b"generated")
            _import_workflow__write_packaged_image(tmp_path, nested_member, b"original")
            generated_path = "C:\\OST\\Project\\A701-D.pdf"
            original_path = "Q:\\estimates\\project\\drawings\\A701-D.pdf"
            ost_path = tmp_path / "Project.ost"
            ost_path.write_text(
                f"""
                <XML_ROOT><Bid><BidPages><BidPage
                  ImagePath="{generated_path}"
                  OverlayImagePath="{original_path}"
                /></BidPages></Bid></XML_ROOT>
                """,
                encoding="utf-8",
            )
            dest_dir = tmp_path / "dest"
            OspImporter(_import_workflow_FakeImporter())._extract_images(
                tmp_path,
                ost_path,
                dest_dir,
                _image_members(flat_member, nested_member),
            )
            generated_dest = dest_dir / "A701-D.pdf"
            nested_destinations = list((dest_dir / "Images").glob("*/A701-D.pdf"))
            self.assertEqual(generated_dest.read_bytes(), b"generated")
            self.assertEqual(len(nested_destinations), 1)
            self.assertEqual(nested_destinations[0].read_bytes(), b"original")
            rewritten = ost_path.read_text(encoding="utf-8")
            self.assertIn(str(generated_dest), rewritten)
            self.assertIn(str(nested_destinations[0]), rewritten)

    def test_osp_image_member_resolution_prefers_deepest_match_in_any_member_order(
        self,
    ):
        flat_member = "TempImages!.tmp\\A701-D.pdf"
        mid_member = "TempImages!.tmp\\drawings\\A701-D.pdf"
        deep_member = "TempImages!.tmp\\estimates\\project\\drawings\\A701-D.pdf"
        reference = "Q:\\estimates\\project\\drawings\\A701-D.pdf"
        for members in (
            (flat_member, mid_member, deep_member),
            (deep_member, mid_member, flat_member),
            (mid_member, deep_member, flat_member),
        ):
            with self.subTest(members=members):
                self.assertEqual(
                    osp_importer_module._resolve_image_member(
                        reference, _image_members(*members)
                    ),
                    deep_member,
                )
        self.assertEqual(
            osp_importer_module._resolve_image_member(
                "C:\\other\\drawings\\A701-D.pdf",
                _image_members(deep_member, flat_member, mid_member),
            ),
            mid_member,
        )
        self.assertIsNone(
            osp_importer_module._resolve_image_member(
                "C:\\other\\A701-D.pdf", _image_members(deep_member, mid_member)
            )
        )

    def test_osp_import_does_not_fall_back_to_nested_basename(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            nested_member = "TempImages!.tmp\\first\\sheet.pdf"
            _import_workflow__write_packaged_image(tmp_path, nested_member, b"nested")
            source_path = "C:\\unrelated\\sheet.pdf"
            ost_path = tmp_path / "Project.ost"
            original_xml = _import_workflow__write_osp_page_xml(ost_path, source_path)
            dest_dir = tmp_path / "dest"
            with self.assertLogs(osp_importer_module.logger, level="WARNING") as logs:
                OspImporter(_import_workflow_FakeImporter())._extract_images(
                    tmp_path,
                    ost_path,
                    dest_dir,
                    _image_members(nested_member),
                )
            self.assertIn(
                "could not resolve 1 referenced image", "\n".join(logs.output)
            )
            self.assertEqual(ost_path.read_text(encoding="utf-8"), original_xml)
            self.assertFalse(dest_dir.exists())

    def test_osp_import_preserves_missing_image_reference_and_continues(self):
        source_path = "C:\\old\\folder\\missing.pdf"
        fake_cab = _import_workflow_FakeOspCab(
            ost_xml=_import_workflow__write_osp_page_xml_text(source_path)
        )
        importer = _StagedOstRecorder()
        original_cab = osp_importer_module.ost_cab
        try:
            osp_importer_module.ost_cab = fake_cab
            with self.assertLogs(osp_importer_module.logger, level="WARNING") as logs:
                result = OspImporter(importer).import_osp(
                    "missing-image.osp", "target.mdb", "project-1"
                )
        finally:
            osp_importer_module.ost_cab = original_cab
        self.assertTrue(result)
        self.assertIn("could not resolve 1 referenced image", "\n".join(logs.output))
        self.assertEqual(len(importer.calls), 1)
        self.assertEqual(
            importer.staged[0][2],
            _import_workflow__write_osp_page_xml_text(source_path),
        )
        self.assertFalse(fake_cab.root.exists())

    def test_osp_import_rejects_case_insensitive_duplicate_members(self):
        fake_cab = _import_workflow_FakeOspCab(
            names=[
                "Project.ost",
                "TempImages!.tmp\\sheet.pdf",
                "tempimages!.TMP\\SHEET.PDF",
            ]
        )
        importer = _import_workflow_FakeImporter()
        original_cab = osp_importer_module.ost_cab
        try:
            osp_importer_module.ost_cab = fake_cab
            with self.assertLogs(osp_importer_module.logger, level="ERROR") as logs:
                result = OspImporter(importer).import_osp(
                    "duplicates.osp", "target.mdb", "project-1"
                )
        finally:
            osp_importer_module.ost_cab = original_cab
        self.assertFalse(result)
        self.assertIn("duplicate or conflicting CAB member", "\n".join(logs.output))
        self.assertEqual(fake_cab.extract_calls, [])
        self.assertEqual(importer.calls, [])

    def test_osp_import_rejects_corrupt_embedded_ost_and_cleans_temp_files(self):
        fake_cab = _import_workflow_FakeOspCab(ost_xml="<XML_ROOT>")
        importer = _import_workflow_FakeImporter()
        original_cab = osp_importer_module.ost_cab
        try:
            osp_importer_module.ost_cab = fake_cab
            with self.assertLogs(osp_importer_module.logger, level="ERROR") as logs:
                result = OspImporter(importer).import_osp(
                    "corrupt.osp", "target.mdb", "project-1"
                )
        finally:
            osp_importer_module.ost_cab = original_cab
        self.assertFalse(result)
        self.assertIn("embedded OST data is corrupt", "\n".join(logs.output))
        self.assertEqual(importer.calls, [])
        self.assertFalse(fake_cab.root.exists())
