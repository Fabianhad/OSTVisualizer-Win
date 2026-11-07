import dataclasses
import hashlib
import os
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path, PurePosixPath, PureWindowsPath
from types import SimpleNamespace
from unittest.mock import patch
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


class OspImporterHelperTests(unittest.TestCase):
    def test_extract_output_dir_uses_the_extended_windows_prefix_once(self):
        def output(resolved):
            return osp_importer_module._cab_extract_output_dir(
                SimpleNamespace(resolve=lambda: resolved)
            )

        cases = {
            "C:\\work\\osp": "\\\\?\\C:\\work\\osp",
            "\\\\?\\C:\\work\\osp": "\\\\?\\C:\\work\\osp",
            "\\\\server\\share\\osp": "\\\\?\\UNC\\server\\share\\osp",
        }
        with patch.object(osp_importer_module.os, "name", "nt"):
            for resolved, expected in cases.items():
                with self.subTest(path=resolved):
                    self.assertEqual(output(resolved), expected)
        with patch.object(osp_importer_module.os, "name", "posix"):
            self.assertEqual(output("/tmp/osp"), "/tmp/osp")

    def test_only_non_empty_relative_cab_member_names_are_safe(self):
        safe = osp_importer_module._is_safe_cab_member_name
        for unsafe in (None, 5, b"plan.png", "", "/abs.png", "C:\\x.png", "..\\x"):
            with self.subTest(name=unsafe):
                self.assertFalse(safe(unsafe))
        self.assertTrue(safe("TempImages!.tmp/plan.png"))

    def test_extract_roots_must_stay_under_the_windows_path_limit(self):
        root = Path("C:\\t")
        member = "m" * (239 - len(str(root)) - 1)
        self.assertEqual(len(str(root / member)), 239)
        safe = osp_importer_module._is_safe_extract_root
        with patch.object(osp_importer_module.os, "name", "nt"):
            self.assertTrue(safe(root, ("short", member)))
            self.assertFalse(safe(root, ("short", member + "m")))
            self.assertFalse(safe(root, (member + "m", "short")))
        with patch.object(osp_importer_module.os, "name", "posix"):
            self.assertTrue(safe(root, (member + "m" * 500,)))

    def test_temp_parent_candidates_add_a_short_root_on_the_same_drive(self):
        candidates = osp_importer_module._extract_temp_parent_candidates

        def parents(temp, name="nt", environment=None):
            with patch.object(osp_importer_module.os, "name", name), patch.object(
                osp_importer_module.tempfile, "gettempdir", return_value=temp
            ), patch.dict(os.environ, environment or {}):
                return candidates()

        self.assertEqual(
            parents("D:\\Users\\me\\Temp"),
            [Path("D:\\Users\\me\\Temp"), Path("D:\\OSTVTemp")],
        )
        self.assertEqual(parents("D:\\OSTVTemp"), [Path("D:\\OSTVTemp")])
        self.assertEqual(
            parents("relative\\temp", environment={"SystemDrive": "E:"}),
            [Path("relative\\temp"), Path("E:\\OSTVTemp")],
        )

    def test_an_unsafe_default_temp_root_is_removed_before_the_short_root_is_used(self):
        create = osp_importer_module._create_extract_temp_dir
        with tempfile.TemporaryDirectory() as folder:
            default = Path(folder, "deep", "er", "default")
            short = Path(folder, "short")

            def candidates():
                return [default, short]

            with patch.object(
                osp_importer_module, "_extract_temp_parent_candidates", candidates
            ):
                with patch.object(
                    osp_importer_module, "_is_safe_extract_root", lambda *_a: False
                ):
                    created = create(("plan.ost",))
                self.assertEqual(created.parent, short)
                self.assertEqual(list(default.iterdir()), [])
                with patch.object(
                    osp_importer_module, "_is_safe_extract_root", lambda *_a: True
                ):
                    kept = create(("plan.ost",))
                self.assertEqual(kept.parent, default)
                self.assertEqual(len(list(short.iterdir())), 1)

    def test_a_temp_parent_that_cannot_be_created_is_skipped(self):
        with tempfile.TemporaryDirectory() as folder:
            blocked = Path(folder, "blocked")
            blocked.write_bytes(b"a file, not a folder")
            short = Path(folder, "short")
            with patch.object(
                osp_importer_module,
                "_extract_temp_parent_candidates",
                lambda: [blocked, short],
            ):
                created = osp_importer_module._create_extract_temp_dir(("plan.ost",))
            self.assertEqual(created.parent, short)

    def test_image_references_match_the_deepest_member_suffix(self):
        members = _image_members(
            "TempImages!.tmp\\b.pdf",
            "TempImages!.tmp\\a\\b.pdf",
            "TempImages!.tmp\\x\\y\\z.pdf",
        )
        resolve = osp_importer_module._resolve_image_member
        cases = {
            "a\\b.pdf": "TempImages!.tmp\\a\\b.pdf",
            "C:\\plans\\a\\b.pdf": "TempImages!.tmp\\a\\b.pdf",
            "C:/plans/other/b.pdf": "TempImages!.tmp\\b.pdf",
            "z.pdf": None,
            "y\\z.pdf": None,
            "x\\y\\z.pdf": "TempImages!.tmp\\x\\y\\z.pdf",
            "TempImages!.tmp\\A\\B.PDF": "TempImages!.tmp\\a\\b.pdf",
            "TempImages!.tmp\\missing.pdf": None,
        }
        for reference, expected in cases.items():
            with self.subTest(reference=reference):
                self.assertEqual(resolve(reference, members), expected)

    def test_image_paths_are_rewritten_only_for_copied_references(self):
        original = (
            "<Root><BidPage ImagePath='C:\\a.png' OverlayImagePath='C:\\b.png'/>"
            "<BidPage ImagePath=''/><BidPage/><BidPage ImagePath='C:\\other.png'/></Root>"
        )
        with tempfile.TemporaryDirectory() as folder:
            ost_path = Path(folder, "Project.ost")
            ost_path.write_text(original, encoding="utf-8")
            tree = ET.parse(ost_path)
            importer = OspImporter(_import_workflow_FakeImporter())
            importer._rewrite_image_paths(tree, ost_path, {"C:\\zzz.png": "D:\\x.png"})
            self.assertEqual(ost_path.read_text(encoding="utf-8"), original)
            importer._rewrite_image_paths(
                tree,
                ost_path,
                {
                    "C:\\a.png": "D:\\one.png",
                    "C:\\b.png": "D:\\two.png",
                    "": "D:\\blank.png",
                },
            )
            pages = ET.parse(ost_path).getroot().findall("BidPage")
            self.assertEqual(
                [
                    (page.get("ImagePath"), page.get("OverlayImagePath"))
                    for page in pages
                ],
                [
                    ("D:\\one.png", "D:\\two.png"),
                    ("", None),
                    (None, None),
                    ("C:\\other.png", None),
                ],
            )
            self.assertTrue(ost_path.read_text(encoding="utf-8").startswith("<Root>"))

    def test_a_failed_temp_folder_removal_is_logged_with_its_cause(self):
        with tempfile.TemporaryDirectory() as folder:
            with patch.object(
                osp_importer_module.shutil,
                "rmtree",
                side_effect=PermissionError("locked"),
            ):
                with self.assertLogs(
                    osp_importer_module.logger, level="WARNING"
                ) as logs:
                    osp_importer_module._remove_temp_tree(Path(folder))
            self.assertEqual(len(logs.records), 1)
            self.assertIs(logs.records[0].exc_info[0], PermissionError)
            self.assertIn(folder, logs.records[0].getMessage())
            with patch.object(
                osp_importer_module.shutil, "rmtree", side_effect=FileNotFoundError()
            ):
                with self.assertNoLogs(osp_importer_module.logger, level="WARNING"):
                    osp_importer_module._remove_temp_tree(Path(folder))

    def test_member_parent_folders_are_created_once_and_nested(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            member = "TempImages!.tmp\\sheets\\level 1\\plan.pdf"
            for _attempt in range(2):
                osp_importer_module._create_cab_member_parent_dir(root, member)
            self.assertTrue((root / "TempImages!.tmp" / "sheets" / "level 1").is_dir())
            self.assertEqual(
                osp_importer_module._cab_member_path(root, member),
                root / "TempImages!.tmp" / "sheets" / "level 1" / "plan.pdf",
            )

    def test_staged_image_locations_are_flat_or_addressed_by_member_name(self):
        relative = osp_importer_module._image_destination_relative_path
        self.assertEqual(relative("TempImages!.tmp\\plan.pdf"), Path("plan.pdf"))
        deep = "TempImages!.tmp\\Sheets\\Plan.pdf"
        digest = hashlib.sha1(deep.casefold().encode("utf-8")).hexdigest()[:16]
        self.assertEqual(relative(deep), Path("Images") / digest / "Plan.pdf")
        self.assertEqual(len(digest), 16)

    def test_conflicting_image_names_get_a_content_digest_suffix_that_grows(self):
        resolve = osp_importer_module._non_conflicting_image_destination
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "source.png"
            source.write_bytes(b"new image")
            digest = hashlib.sha256(b"new image").hexdigest()
            destination = root / "plan.png"
            self.assertEqual(resolve(source, destination), destination)
            destination.write_bytes(b"old")
            names = []
            for length in (16, 32, len(digest)):
                candidate = resolve(source, destination)
                names.append(candidate.name)
                self.assertEqual(candidate.name, f"plan-{digest[:length]}.png")
                candidate.write_bytes(b"different %d" % length)
            with self.assertRaises(osp_importer_module._OspFormatError):
                resolve(source, destination)
            reusable = root / names[1]
            reusable.write_bytes(b"new image")
            self.assertEqual(resolve(source, destination), reusable)
            destination.write_bytes(b"new image")
            self.assertEqual(resolve(source, destination), destination)

    def test_large_files_are_compared_and_hashed_across_chunk_boundaries(self):
        chunk = 1024 * 1024
        same = osp_importer_module._files_have_same_content
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)

            def write(name, content):
                path = root / name
                path.write_bytes(content)
                return path

            base = b"\x01" * (2 * chunk + 10)
            first = write("first.bin", base)
            self.assertTrue(same(first, write("copy.bin", base)))
            self.assertFalse(same(first, write("last.bin", base[:-1] + b"\x02")))
            self.assertFalse(
                same(
                    first,
                    write("mid.bin", base[: chunk + 5] + b"\x02" + base[chunk + 6 :]),
                )
            )
            self.assertFalse(same(first, write("short.bin", base[:-1])))
            exact = write("exact.bin", b"\x03" * chunk)
            self.assertTrue(same(exact, write("exact2.bin", b"\x03" * chunk)))
            self.assertTrue(same(write("empty.bin", b""), write("empty2.bin", b"")))
            self.assertEqual(
                osp_importer_module._file_content_digest(first),
                hashlib.sha256(base).hexdigest(),
            )


class OspImporterImageAndPackageTests(unittest.TestCase):
    def test_osp_import_extracts_cab_with_windows_extended_output_path(self):
        fake_cab = _import_workflow_FakeOspCab()
        importer = _StagedOstRecorder()
        original_cab = osp_importer_module.ost_cab
        try:
            osp_importer_module.ost_cab = fake_cab
            self.assertIs(
                OspImporter(importer).import_osp(
                    "source.osp", "target.mdb", "project-1"
                ),
                True,
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
        self.assertIs(result, False)
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
        self.assertIs(result, False)
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
                    self.assertIs(result, False)
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
                    self.assertIs(result, False)
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
                self.assertIs(
                    OspImporter(importer).import_osp(
                        "source.osp", "target.mdb", "project-1"
                    ),
                    True,
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
            self.assertIs(
                OspImporter(importer).import_osp(
                    "source.osp", "target.mdb", "project-1"
                ),
                True,
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
        self.assertIs(result, True)
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
                    self.assertIs(result, False)
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
        self.assertIs(result, True)
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
        self.assertIs(result, False)
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
        self.assertIs(result, False)
        self.assertIn("embedded OST data is corrupt", "\n".join(logs.output))
        self.assertEqual(importer.calls, [])
        self.assertFalse(fake_cab.root.exists())


class _NoOstExtractCab(_import_workflow_FakeOspCab):
    """Reports a successful extraction that leaves no files behind."""

    def extract_cab(self, source_path, output_dir):
        self.extract_calls.append(output_dir)
        self.root = Path(self._normal_windows_path(output_dir))
        return True


class _MissingImageExtractCab(_import_workflow_FakeOspCab):
    """Extracts the OST but silently drops every packaged image."""

    def extract_cab(self, source_path, output_dir):
        super().extract_cab(source_path, output_dir)
        for member_path in self.root.rglob("*.pdf"):
            member_path.unlink()
        return True


class _UnreadableListingCab(_import_workflow_FakeOspCab):
    def list_cab(self, _source_path):
        raise OSError("cab listing unreadable")


class _ReturningImporter(_import_workflow_FakeImporter):
    def __init__(self, result):
        super().__init__()
        self.result = result

    def import_ost(self, source_path, target_path, project_uid=None):
        super().import_ost(source_path, target_path, project_uid)
        return self.result


def _page_xml(*attributes):
    return "<XML_ROOT><Bid><BidPages><BidPage {}/></BidPages></Bid></XML_ROOT>".format(
        " ".join(f'{name}="{value}"' for name, value in attributes)
    )


class OspImporterFailureAndRollbackTests(unittest.TestCase):
    def _folder(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        return Path(folder.name)

    def _use_cab(self, fake_cab):
        original = osp_importer_module.ost_cab
        osp_importer_module.ost_cab = fake_cab
        self.addCleanup(setattr, osp_importer_module, "ost_cab", original)

    def _use_working_dir(self, folder):
        patcher = patch.object(
            osp_importer_module, "get_default_working_dir", return_value=folder
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def _import(self, importer):
        with self.assertLogs(osp_importer_module.logger, level="WARNING") as logs:
            result = OspImporter(importer).import_osp(
                "source.osp", "target.mdb", "project-1"
            )
        return result, [record.getMessage() for record in logs.records], logs

    def test_import_osp_returns_the_importer_verdict_and_always_cleans_up(self):
        for verdict in (True, False):
            with self.subTest(verdict=verdict):
                fake_cab = _import_workflow_FakeOspCab()
                importer = _ReturningImporter(verdict)
                self._use_cab(fake_cab)
                result = OspImporter(importer).import_osp(
                    "source.osp", "target.mdb", "project-1"
                )
                self.assertIs(result, verdict)
                self.assertEqual(len(importer.calls), 1)
                self.assertFalse(fake_cab.root.exists())

    def test_unreadable_archive_listing_fails_before_any_extraction(self):
        fake_cab = _UnreadableListingCab()
        importer = _import_workflow_FakeImporter()
        self._use_cab(fake_cab)
        with patch.object(osp_importer_module, "_create_extract_temp_dir") as create:
            result, messages, logs = self._import(importer)
        self.assertIs(result, False)
        self.assertEqual(messages, ["Unexpected OSP import failure: source.osp"])
        self.assertIs(logs.records[0].exc_info[0], OSError)
        create.assert_not_called()
        self.assertEqual(fake_cab.extract_calls, [])
        self.assertEqual(importer.calls, [])

    def test_extraction_failure_message_names_the_cause_and_archive(self):
        fake_cab = _FailingExtractCab()
        self._use_cab(fake_cab)
        result, messages, _logs = self._import(_import_workflow_FakeImporter())
        self.assertIs(result, False)
        self.assertEqual(
            messages,
            ["Cannot import OSP source.osp: the OSP archive could not be extracted"],
        )

    def test_missing_embedded_ost_after_extraction_fails_and_cleans_up(self):
        fake_cab = _NoOstExtractCab()
        importer = _import_workflow_FakeImporter()
        self._use_cab(fake_cab)
        result, messages, _logs = self._import(importer)
        self.assertIs(result, False)
        self.assertEqual(
            messages,
            [
                "Cannot import OSP source.osp: embedded OST member was not "
                "extracted: Project.ost"
            ],
        )
        self.assertEqual(importer.calls, [])
        self.assertFalse(fake_cab.root.exists())

    def test_packaged_image_missing_after_extraction_fails_before_the_importer(self):
        member = "TempImages!.tmp\\plan.pdf"
        fake_cab = _MissingImageExtractCab(
            names=["Project.ost", member],
            ost_xml=_page_xml(("ImagePath", "C:\\plans\\plan.pdf")),
        )
        importer = _import_workflow_FakeImporter()
        work = self._folder()
        self._use_cab(fake_cab)
        self._use_working_dir(work)
        result, messages, _logs = self._import(importer)
        self.assertIs(result, False)
        self.assertEqual(
            messages,
            [
                "Cannot import OSP source.osp: image member was not extracted: "
                "TempImages!.tmp\\plan.pdf"
            ],
        )
        self.assertEqual(importer.calls, [])
        self.assertFalse(fake_cab.root.exists())
        self.assertEqual(list(work.rglob("*.pdf")), [])

    def test_missing_image_member_is_detected_before_any_image_is_copied(self):
        tmp_path = self._folder()
        dest_dir = self._folder() / "dest"
        _import_workflow__write_packaged_image(
            tmp_path, "TempImages!.tmp\\first.pdf", b"first"
        )
        refs = [
            osp_importer_module._ImageReference("a.pdf", "TempImages!.tmp\\first.pdf"),
            osp_importer_module._ImageReference("b.pdf", "TempImages!.tmp\\second.pdf"),
        ]
        with self.assertRaisesRegex(
            osp_importer_module._OspFormatError,
            r"^image member was not extracted: TempImages!\.tmp\\second\.pdf$",
        ):
            OspImporter(_import_workflow_FakeImporter())._copy_referenced_images(
                tmp_path, dest_dir, refs
            )
        self.assertFalse(dest_dir.exists())

    def test_a_copy_failure_leaves_the_ost_untouched_and_skips_the_import(self):
        names = [
            "Project.ost",
            "TempImages!.tmp\\one.pdf",
            "TempImages!.tmp\\two.pdf",
        ]
        xml = _page_xml(
            ("ImagePath", "C:\\plans\\one.pdf"),
            ("OverlayImagePath", "C:\\plans\\two.pdf"),
        )
        fake_cab = _import_workflow_FakeOspCab(names=names, ost_xml=xml)
        importer = _StagedOstRecorder()
        work = self._folder()
        self._use_cab(fake_cab)
        self._use_working_dir(work)
        real_copy = osp_importer_module.shutil.copy2
        copied = []

        def flaky_copy(source, destination):
            if copied:
                raise OSError("disk full")
            copied.append(destination)
            return real_copy(source, destination)

        with patch.object(osp_importer_module.shutil, "copy2", flaky_copy):
            result, messages, logs = self._import(importer)
        self.assertIs(result, False)
        self.assertEqual(messages, ["Unexpected OSP import failure: source.osp"])
        self.assertIs(logs.records[0].exc_info[0], OSError)
        self.assertEqual(len(copied), 1)
        self.assertEqual(importer.calls, [])
        self.assertFalse(fake_cab.root.exists())

    def test_a_copy_failure_does_not_rewrite_the_embedded_ost(self):
        tmp_path = self._folder()
        member_one = "TempImages!.tmp\\one.pdf"
        member_two = "TempImages!.tmp\\two.pdf"
        _import_workflow__write_packaged_image(tmp_path, member_one, b"one")
        _import_workflow__write_packaged_image(tmp_path, member_two, b"two")
        ost_path = tmp_path / "Project.ost"
        original = _page_xml(
            ("ImagePath", "C:\\plans\\one.pdf"),
            ("OverlayImagePath", "C:\\plans\\two.pdf"),
        )
        ost_path.write_text(original, encoding="utf-8")
        calls = []

        def flaky_copy(source, destination):
            calls.append(destination)
            if len(calls) == 2:
                raise OSError("disk full")

        with patch.object(osp_importer_module.shutil, "copy2", flaky_copy):
            with self.assertRaisesRegex(OSError, "^disk full$"):
                OspImporter(_import_workflow_FakeImporter())._extract_images(
                    tmp_path,
                    ost_path,
                    tmp_path / "dest",
                    _image_members(member_one, member_two),
                )
        self.assertEqual(len(calls), 2)
        self.assertEqual(ost_path.read_text(encoding="utf-8"), original)

    def test_one_packaged_member_referenced_twice_is_copied_once_for_both_paths(self):
        tmp_path = self._folder()
        member = "TempImages!.tmp\\plan.pdf"
        _import_workflow__write_packaged_image(tmp_path, member, b"plan")
        ost_path = tmp_path / "Project.ost"
        ost_path.write_text(
            _page_xml(
                ("ImagePath", "C:\\plans\\plan.pdf"),
                ("OverlayImagePath", "D:\\other\\plan.pdf"),
            ),
            encoding="utf-8",
        )
        dest_dir = tmp_path / "dest"
        real_copy = osp_importer_module.shutil.copy2
        with patch.object(
            osp_importer_module.shutil, "copy2", side_effect=real_copy
        ) as copy:
            OspImporter(_import_workflow_FakeImporter())._extract_images(
                tmp_path, ost_path, dest_dir, _image_members(member)
            )
        self.assertEqual(copy.call_count, 1)
        page = ET.parse(ost_path).getroot().find(".//BidPage")
        self.assertEqual(page.get("ImagePath"), str(dest_dir / "plan.pdf"))
        self.assertEqual(page.get("OverlayImagePath"), str(dest_dir / "plan.pdf"))
        self.assertEqual([path.name for path in dest_dir.iterdir()], ["plan.pdf"])

    def test_distinct_members_sharing_a_staging_name_are_never_merged(self):
        first = "TempImages!.tmp\\a.pdf"
        second = "TempImages!.tmp\\b.pdf"
        for same_content in (True, False):
            with self.subTest(same_content=same_content):
                tmp_path = self._folder()
                dest_dir = tmp_path / "dest"
                _import_workflow__write_packaged_image(tmp_path, first, b"alpha")
                _import_workflow__write_packaged_image(
                    tmp_path, second, b"alpha" if same_content else b"bravo"
                )
                refs = [
                    osp_importer_module._ImageReference("a.pdf", first),
                    osp_importer_module._ImageReference("b.pdf", second),
                ]
                importer = OspImporter(_import_workflow_FakeImporter())
                with patch.object(
                    osp_importer_module,
                    "_image_destination_relative_path",
                    return_value=Path("shared.pdf"),
                ):
                    if same_content:
                        with self.assertRaisesRegex(
                            osp_importer_module._OspFormatError,
                            r"^image staging destination collision between "
                            r"'TempImages!\.tmp\\\\b\.pdf' and "
                            r"'tempimages!\.tmp\\\\a\.pdf'$",
                        ):
                            importer._copy_referenced_images(tmp_path, dest_dir, refs)
                    else:
                        copied = importer._copy_referenced_images(
                            tmp_path, dest_dir, refs
                        )
                        digest = hashlib.sha256(b"bravo").hexdigest()[:16]
                        self.assertEqual(
                            copied,
                            {
                                "a.pdf": str(dest_dir / "shared.pdf"),
                                "b.pdf": str(dest_dir / f"shared-{digest}.pdf"),
                            },
                        )
                        self.assertEqual(
                            (dest_dir / "shared.pdf").read_bytes(), b"alpha"
                        )
                        self.assertEqual(
                            (dest_dir / f"shared-{digest}.pdf").read_bytes(), b"bravo"
                        )

    def test_image_reference_collection_checks_each_attribute_independently(self):
        members = _image_members(
            "TempImages!.tmp\\over.pdf", "TempImages!.tmp\\img.pdf"
        )
        collect = OspImporter(_import_workflow_FakeImporter())._collect_image_references
        resolved_overlay = ET.fromstring(
            _page_xml(("ImagePath", ""), ("OverlayImagePath", "C:\\x\\over.pdf"))
        )
        refs = collect(resolved_overlay, members)
        self.assertEqual(
            [(ref.original_path, ref.member_name) for ref in refs],
            [("C:\\x\\over.pdf", "TempImages!.tmp\\over.pdf")],
        )
        unsupported_first = ET.fromstring(
            _page_xml(
                ("ImagePath", "C:\\x\\notes.txt"),
                ("OverlayImagePath", "C:\\x\\over.pdf"),
            )
        )
        with self.assertNoLogs(osp_importer_module.logger, level="WARNING"):
            refs = collect(unsupported_first, members)
        self.assertEqual([ref.original_path for ref in refs], ["C:\\x\\over.pdf"])
        missing_first = ET.fromstring(
            _page_xml(
                ("ImagePath", "C:\\x\\gone.pdf"),
                ("OverlayImagePath", "C:\\x\\over.pdf"),
            )
        )
        with self.assertLogs(osp_importer_module.logger, level="WARNING") as logs:
            refs = collect(missing_first, members)
        self.assertEqual([ref.original_path for ref in refs], ["C:\\x\\over.pdf"])
        self.assertEqual(
            [record.getMessage() for record in logs.records],
            [
                "OSP import could not resolve 1 referenced image(s) in the package. "
                "Import will continue and preserve those original paths. "
                "First missing source path: C:\\x\\gone.pdf"
            ],
        )

    def test_extraction_directory_is_a_prefixed_fresh_folder_under_the_system_temp(
        self,
    ):
        folder = self._folder()
        with patch.object(
            osp_importer_module.tempfile, "gettempdir", return_value=str(folder)
        ):
            created = osp_importer_module._create_extract_temp_dir(("plan.ost",))
        self.addCleanup(osp_importer_module._remove_temp_tree, created)
        self.assertTrue(created.is_dir())
        self.assertEqual(created.parent, folder)
        self.assertRegex(created.name, r"^ostv_osp_[a-z0-9_]{8}$")
        self.assertEqual(list(created.iterdir()), [])

    def test_extraction_directory_falls_back_to_the_system_default_location(self):
        folder = self._folder()
        real_mkdtemp = osp_importer_module.tempfile.mkdtemp
        seen = []

        def mkdtemp(prefix=None, dir=None):
            seen.append(dir)
            if dir is not None:
                raise OSError("parent unusable")
            return real_mkdtemp(prefix=prefix, dir=str(folder))

        with patch.object(
            osp_importer_module, "_extract_temp_parent_candidates", lambda: [folder]
        ), patch.object(osp_importer_module.tempfile, "mkdtemp", mkdtemp):
            created = osp_importer_module._create_extract_temp_dir(("plan.ost",))
        self.addCleanup(osp_importer_module._remove_temp_tree, created)
        self.assertEqual(seen, [str(folder), None])
        self.assertEqual(created.parent, folder)
        self.assertRegex(created.name, r"^ostv_osp_[a-z0-9_]{8}$")

    def test_extraction_directory_failures_raise_the_first_parent_error(self):
        folder = self._folder()
        errors = [OSError("parent unusable"), OSError("default unusable")]
        with patch.object(
            osp_importer_module, "_extract_temp_parent_candidates", lambda: [folder]
        ), patch.object(osp_importer_module.tempfile, "mkdtemp", side_effect=errors):
            with self.assertRaises(OSError) as caught:
                osp_importer_module._create_extract_temp_dir(("plan.ost",))
        self.assertIs(caught.exception, errors[0])

    def test_extraction_directory_failure_without_a_parent_error_reraises_it(self):
        folder = self._folder()
        real_mkdtemp = osp_importer_module.tempfile.mkdtemp
        final_error = OSError("default unusable")

        def mkdtemp(prefix=None, dir=None):
            if dir is None:
                raise final_error
            return real_mkdtemp(prefix=prefix, dir=dir)

        with patch.object(
            osp_importer_module, "_extract_temp_parent_candidates", lambda: [folder]
        ), patch.object(
            osp_importer_module, "_is_safe_extract_root", lambda *_a: False
        ), patch.object(
            osp_importer_module.tempfile, "mkdtemp", mkdtemp
        ):
            with self.assertRaises(OSError) as caught:
                osp_importer_module._create_extract_temp_dir(("plan.ost",))
        self.assertIs(caught.exception, final_error)
        self.assertEqual(list(folder.iterdir()), [])

    def test_posix_hosts_use_only_the_system_temp_without_a_short_root(self):
        # A POSIX path class stands in for pathlib.Path so the branch can run on
        # any host operating system.
        with patch.object(osp_importer_module.os, "name", "posix"), patch.object(
            osp_importer_module, "Path", PurePosixPath
        ), patch.object(
            osp_importer_module.tempfile, "gettempdir", return_value="/var/tmp"
        ):
            self.assertEqual(
                osp_importer_module._extract_temp_parent_candidates(),
                [PurePosixPath("/var/tmp")],
            )

    def test_package_inspection_normalizes_member_names_and_indexes_images(self):
        package = osp_importer_module._inspect_package(
            [
                "Plan.OST",
                "TempImages!.tmp/Sub/Sheet.PDF",
                "notes\\readme.txt",
                "Other.tif",
            ]
        )
        self.assertEqual(
            package.member_names,
            (
                "Plan.OST",
                "TempImages!.tmp\\Sub\\Sheet.PDF",
                "notes\\readme.txt",
                "Other.tif",
            ),
        )
        self.assertEqual(package.ost_member_name, "Plan.OST")
        self.assertEqual(
            package.image_members_by_path,
            {"tempimages!.tmp\\sub\\sheet.pdf": "TempImages!.tmp\\Sub\\Sheet.PDF"},
        )
        for field, value in (
            ("ost_member_name", "x.ost"),
            ("member_names", ()),
        ):
            with self.subTest(field=field):
                with self.assertRaises(dataclasses.FrozenInstanceError):
                    setattr(package, field, value)
        reference = osp_importer_module._ImageReference(
            "a.pdf", "TempImages!.tmp\\a.pdf"
        )
        with self.assertRaises(dataclasses.FrozenInstanceError):
            reference.member_name = "other"

    def test_cab_member_name_safety_rules_return_exact_booleans(self):
        safe = osp_importer_module._is_safe_cab_member_name
        for unsafe in (
            None,
            5,
            "",
            "/abs.png",
            "\\abs.png",
            "C:\\x.png",
            "C:x.png",
            "..\\x",
            "../x",
            "ok/../x.pdf",
            "ok\\..\\x.pdf",
            "a.ost:stream",
            ".",
            "\\\\server\\share\\x.pdf",
        ):
            with self.subTest(unsafe=unsafe):
                self.assertIs(safe(unsafe), False)
        for allowed in (
            "Project.ost",
            "TempImages!.tmp\\sheet.pdf",
            "TempImages!.tmp/sheet.pdf",
            "ok/./file.pdf",
            "name with spaces.pdf",
        ):
            with self.subTest(allowed=allowed):
                self.assertIs(safe(allowed), True)
        self.assertEqual(
            osp_importer_module._windows_path_parts("a/./b\\c"), ("a", "b", "c")
        )

    def test_supported_image_paths_depend_on_the_final_component_suffix(self):
        supported = osp_importer_module._is_supported_image_path
        for path, expected in (
            ("C:\\plans\\a.pdf", True),
            ("C:/plans/a.PDF", True),
            ("a.tif", True),
            ("a.TIFF", True),
            ("a.png", False),
            ("a", False),
            ("C:\\plans\\.pdf", False),
            ("C:/plans/.pdf", False),
            ("dir.pdf\\a", False),
            ("dir.pdf/a", False),
        ):
            with self.subTest(path=path):
                self.assertIs(supported(path), expected)

    def test_windows_path_limit_boundary_is_exclusive_at_240_characters(self):
        root = Path("C:\\t")
        safe = osp_importer_module._is_safe_extract_root
        at_limit = "m" * (240 - len(str(root)) - 1)
        self.assertEqual(len(str(root / at_limit)), 240)
        under_limit = at_limit[:-1]
        self.assertEqual(len(str(root / under_limit)), 239)
        with patch.object(osp_importer_module.os, "name", "nt"):
            self.assertIs(safe(root, (under_limit,)), True)
            self.assertIs(safe(root, (at_limit,)), False)
            self.assertIs(safe(root, ()), True)

    def test_value_comparisons_return_exact_booleans(self):
        folder = self._folder()
        base = folder / "base.bin"
        base.write_bytes(b"abcdef")
        for name, content, expected in (
            ("same.bin", b"abcdef", True),
            ("other_size.bin", b"abcde", False),
            ("other_bytes.bin", b"abcdeX", False),
        ):
            with self.subTest(name=name):
                other = folder / name
                other.write_bytes(content)
                self.assertIs(
                    osp_importer_module._files_have_same_content(base, other), expected
                )


class OspImporterRealArchiveTests(unittest.TestCase):
    def _folder(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        return Path(folder.name)

    def _write_osp(self, folder, members):
        sources, names = [], []
        for index, (name, content) in enumerate(members.items()):
            source = folder / f"source-{index}.bin"
            source.write_bytes(
                content if isinstance(content, bytes) else content.encode("utf-8")
            )
            sources.append(str(source))
            names.append(name)
        archive = folder / "package.osp"
        self.assertTrue(
            osp_importer_module.ost_cab.create_cab_with_names(
                sources, names, str(archive)
            )
        )
        return archive

    def test_garbage_empty_and_missing_archives_are_rejected_as_having_no_ost(self):
        folder = self._folder()
        garbage = folder / "garbage.osp"
        garbage.write_bytes(b"this is not a cabinet file" * 8)
        empty = folder / "empty.osp"
        empty.write_bytes(b"")
        missing = folder / "missing.osp"
        for label, archive in (
            ("garbage", garbage),
            ("empty", empty),
            ("missing", missing),
        ):
            with self.subTest(archive=label):
                importer = _import_workflow_FakeImporter()
                with self.assertLogs(osp_importer_module.logger, level="ERROR") as logs:
                    result = OspImporter(importer).import_osp(
                        str(archive), "target.mdb", "project-1"
                    )
                self.assertIs(result, False)
                self.assertEqual(
                    [record.getMessage() for record in logs.records],
                    [
                        f"Cannot import OSP {archive}: archive must contain exactly "
                        "one top-level .ost file; found 0"
                    ],
                )
                self.assertEqual(importer.calls, [])

    def test_real_archive_with_a_traversal_member_is_rejected_before_extraction(self):
        folder = self._folder()
        probe = "ostv_traversal_probe.pdf"
        archive = self._write_osp(
            folder, {"Project.ost": "<XML_ROOT />", f"..\\{probe}": b"payload"}
        )
        importer = _import_workflow_FakeImporter()
        with patch.object(osp_importer_module, "_create_extract_temp_dir") as create:
            with self.assertLogs(osp_importer_module.logger, level="ERROR") as logs:
                result = OspImporter(importer).import_osp(
                    str(archive), "target.mdb", "project-1"
                )
        self.assertIs(result, False)
        self.assertEqual(
            [record.getMessage() for record in logs.records],
            [f"Cannot import OSP {archive}: unsafe CAB member path: '..\\\\{probe}'"],
        )
        create.assert_not_called()
        self.assertEqual(importer.calls, [])
        self.assertFalse((Path(tempfile.gettempdir()) / probe).exists())

    def test_real_archive_stages_images_rewrites_paths_and_removes_the_extraction(self):
        folder = self._folder()
        work = folder / "work"
        xml = _page_xml(("ImagePath", "C:\\plans\\plan.pdf"))
        archive = self._write_osp(
            folder,
            {
                "Project.ost": xml,
                "TempImages!.tmp\\plan.pdf": b"%PDF packaged drawing",
            },
        )
        importer = _StagedOstRecorder()
        with patch.object(
            osp_importer_module, "get_default_working_dir", return_value=work
        ):
            result = OspImporter(importer).import_osp(
                str(archive), "target.mdb", "project-1"
            )
        self.assertIs(result, True)
        staged_path, staged_existed, staged_text = importer.staged[0]
        self.assertIs(staged_existed, True)
        self.assertEqual(staged_path.name, "Project.ost")
        staged_image = work / "Project" / "plan.pdf"
        self.assertEqual(staged_image.read_bytes(), b"%PDF packaged drawing")
        self.assertEqual(
            ET.fromstring(staged_text).find(".//BidPage").get("ImagePath"),
            str(staged_image),
        )
        self.assertFalse(staged_path.parent.exists())
        self.assertEqual([path.name for path in work.iterdir()], ["Project"])
