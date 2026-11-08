import os
import tempfile
import unittest
from pathlib import Path, PureWindowsPath
from tests.helpers.import_workflow import FakeOspCab, hostile_cab_member_names


class FakeOspCabExtractionTests(unittest.TestCase):
    """The fake archive extractor never writes outside the extraction folder."""

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name).resolve()
        self.root = self.base / "extract"
        self.root.mkdir()
        self.outside = self.base / "outside"
        self.outside.mkdir()

    def _listing(self, folder):
        return sorted(path.relative_to(folder).as_posix() for path in folder.rglob("*"))

    def test_members_are_written_inside_the_output_folder(self):
        (self.root / "TempImages!.tmp").mkdir()
        (self.root / "level 1").mkdir()
        fake_cab = FakeOspCab(
            names=[
                "Project.ost",
                "TempImages!.tmp\\sheet.pdf",
                "level 1\\plan v2.pdf",
                "folder-only",
            ],
            ost_xml="<Custom />",
        )
        self.assertIs(fake_cab.extract_cab("source.osp", str(self.root)), True)
        self.assertEqual(
            (self.root / "Project.ost").read_text(encoding="utf-8"), "<Custom />"
        )
        self.assertEqual(
            (self.root / "TempImages!.tmp" / "sheet.pdf").read_bytes(), b"packaged"
        )
        self.assertEqual(
            (self.root / "level 1" / "plan v2.pdf").read_bytes(), b"packaged"
        )
        self.assertFalse((self.root / "folder-only").exists())
        self.assertEqual(fake_cab.extract_calls, [str(self.root)])
        self.assertEqual(fake_cab.root, self.root)
        self.assertEqual(self._listing(self.outside), [])

    def test_extended_length_output_prefixes_are_removed_before_extraction(self):
        fake_cab = FakeOspCab()
        self.assertIs(
            fake_cab.extract_cab("source.osp", "\\\\?\\" + str(self.root)), True
        )
        self.assertEqual(fake_cab.root, self.root)
        self.assertTrue((self.root / "Project.ost").is_file())

    def test_a_member_outside_the_output_folder_raises_and_writes_nothing(self):
        for label, name in hostile_cab_member_names(self.outside, self.root).items():
            with self.subTest(form=label, name=name):
                fake_cab = FakeOspCab(names=["Project.ost", name])
                with self.assertRaisesRegex(
                    AssertionError, "outside the extraction folder"
                ) as caught:
                    fake_cab.extract_cab("source.osp", str(self.root))
                self.assertIn(repr(name), str(caught.exception))
                self.assertEqual(self._listing(self.outside), [])
                self.assertEqual(self._listing(self.root), [])
                self.assertEqual(fake_cab.extract_calls, [str(self.root)])

    def test_a_hostile_member_listed_before_the_good_ones_still_writes_nothing(self):
        name = hostile_cab_member_names(self.outside, self.root)["relative"]
        fake_cab = FakeOspCab(names=[name, "Project.ost", "sheet.pdf"])
        with self.assertRaises(AssertionError):
            fake_cab.extract_cab("source.osp", str(self.root))
        self.assertEqual(self._listing(self.base), ["extract", "outside"])

    def test_a_member_that_resolves_to_the_output_folder_itself_is_outside(self):
        for name in ("a\\..", "sub\\..\\.."):
            with self.subTest(name=name):
                fake_cab = FakeOspCab(names=[name])
                with self.assertRaisesRegex(AssertionError, "outside the extraction"):
                    fake_cab.extract_cab("source.osp", str(self.root))
        self.assertEqual(self._listing(self.base), ["extract", "outside"])

    def test_a_member_that_stays_inside_after_dot_dot_is_allowed(self):
        (self.root / "sub").mkdir()
        fake_cab = FakeOspCab(names=["sub\\..\\sub\\plan.pdf"])
        self.assertIs(fake_cab.extract_cab("source.osp", str(self.root)), True)
        self.assertEqual((self.root / "sub" / "plan.pdf").read_bytes(), b"packaged")

    def test_a_sibling_folder_sharing_the_root_name_prefix_is_outside(self):
        sibling = self.base / "extract-sibling"
        sibling.mkdir()
        name = os.path.relpath(sibling / "payload.ost", self.root)
        fake_cab = FakeOspCab(names=[name])
        with self.assertRaisesRegex(AssertionError, "outside the extraction"):
            fake_cab.extract_cab("source.osp", str(self.root))
        self.assertEqual(self._listing(sibling), [])

    def test_the_refusal_names_the_member_the_destination_and_the_folder(self):
        name = hostile_cab_member_names(self.outside, self.root)["relative"]
        destination = self.root.joinpath(*PureWindowsPath(name).parts)
        with self.assertRaises(AssertionError) as caught:
            FakeOspCab(names=[name]).extract_cab("source.osp", str(self.root))
        self.assertEqual(
            str(caught.exception),
            f"CAB member {name!r} would be extracted to {destination}, "
            f"outside the extraction folder {self.root}",
        )

    def test_output_folder_prefixes_are_removed_in_every_form(self):
        normal = FakeOspCab()._normal_windows_path
        self.assertEqual(normal("\\\\?\\C:\\work\\osp"), "C:\\work\\osp")
        self.assertEqual(
            normal("\\\\?\\UNC\\server\\share\\osp"), "\\\\server\\share\\osp"
        )
        self.assertEqual(normal("C:\\work\\osp"), "C:\\work\\osp")
        self.assertEqual(normal("\\\\server\\share"), "\\\\server\\share")

    def test_the_hostile_name_forms_have_the_documented_shapes(self):
        names = hostile_cab_member_names(self.outside, self.root)
        self.assertEqual(
            list(names),
            ["absolute", "rooted", "relative", "relative with forward slashes"],
        )
        target = self.outside / "payload.ost"
        self.assertEqual(names["absolute"], str(target))
        self.assertEqual(names["rooted"], str(target)[len(target.drive) :])
        self.assertTrue(names["rooted"].startswith("\\"))
        self.assertEqual(names["relative"], "..\\outside\\payload.ost")
        self.assertEqual(
            names["relative with forward slashes"], "../outside/payload.ost"
        )

    def test_the_hostile_forms_resolve_to_the_same_target(self):
        names = hostile_cab_member_names(self.outside, self.root)
        targets = {
            (self.root.joinpath(*PureWindowsPath(name).parts)).resolve()
            for name in names.values()
        }
        self.assertEqual(targets, {self.outside / "payload.ost"})


if __name__ == "__main__":
    unittest.main()
