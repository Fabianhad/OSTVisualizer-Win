"""Stray-folder check: snapshot/compare of a drive root and the temp folder.
Every root, temp folder, repo root and state file used here lives inside a
folder made by ``tempfile.mkdtemp``. The real drive root and the real temp
folder are never scanned: each test passes ``--root`` and ``--temp`` and
``_sandboxed`` asserts that they are inside the sandbox.
"""

import contextlib
import io
import json
import ntpath
import os
import shutil
import stat
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from tools import check_stray_folders as stray

_NS = 1_000_000_000


class _Case(unittest.TestCase):
    def setUp(self):
        self.base = os.path.realpath(tempfile.mkdtemp(prefix="ostv_stray_test_"))
        self.addCleanup(shutil.rmtree, self.base, ignore_errors=True)
        self.root = self._sandboxed(os.path.join(self.base, "drive"))
        self.temp = self._sandboxed(os.path.join(self.base, "temp"))
        self.repo = self._sandboxed(os.path.join(self.base, "repo"))
        self.states = self._sandboxed(os.path.join(self.base, "states"))
        for folder in (self.root, self.temp, self.repo, self.states):
            os.makedirs(folder)
        self.state = os.path.join(self.states, "state.json")

    def _sandboxed(self, path):
        real = os.path.realpath(path)
        self.assertEqual(os.path.commonpath([real, self.base]), self.base)
        self.assertNotEqual(real, self.base)
        self.assertTrue(
            os.path.basename(self.base).startswith("ostv_stray_test_"),
            "the sandbox must come from tempfile.mkdtemp",
        )
        return real

    def _file(self, name, size=3, mtime=1_700_000_000):
        path = os.path.join(self.root, name)
        with open(path, "wb") as handle:
            handle.write(b"x" * size)
        os.utime(path, ns=(mtime * _NS, mtime * _NS))
        return path

    def _folder(self, name, mtime=1_700_000_000):
        path = os.path.join(self.root, name)
        os.makedirs(path, exist_ok=True)
        os.utime(path, ns=(mtime * _NS, mtime * _NS))
        return path

    def _run(self, command, *extra, windows=False, repo=None, state=None):
        argv = [
            command,
            "--state",
            self.state if state is None else state,
            "--root",
            self.root,
            "--temp",
            self.temp,
            *extra,
        ]
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = stray.main(
                argv, windows=windows, repo_root=self.repo if repo is None else repo
            )
        return code, out.getvalue(), err.getvalue()


class DefaultsTests(unittest.TestCase):
    def test_system_drive_root_uses_the_system_drive_on_windows(self):
        self.assertEqual(stray.system_drive_root({"SystemDrive": "D:"}, True), "D:\\")
        self.assertEqual(stray.system_drive_root({"SystemDrive": "c:\\"}, True), "c:\\")
        self.assertEqual(stray.system_drive_root({}, True), "C:\\")
        self.assertEqual(stray.system_drive_root({"SystemDrive": ""}, True), "C:\\")

    def test_system_drive_root_is_slash_off_windows(self):
        self.assertEqual(stray.system_drive_root({"SystemDrive": "D:"}, False), "/")

    def test_system_drive_root_without_arguments_reads_the_environment(self):
        with patch.dict(os.environ, {"SystemDrive": "E:"}):
            with patch.object(stray.os, "name", "nt"):
                self.assertEqual(stray.system_drive_root(), "E:\\")
            with patch.object(stray.os, "name", "posix"):
                self.assertEqual(stray.system_drive_root(), "/")

    def test_documented_ignore_list_is_explicit(self):
        expected = {
            "system volume information",
            "$recycle.bin",
            "windows",
            "users",
            "programdata",
            "onedrivetemp",
            "pagefile.sys",
            "hiberfil.sys",
            "swapfile.sys",
            "dumpstack.log.tmp",
            "recovery",
            "$av_asw",
        }
        self.assertEqual(
            {name.casefold() for name in stray.WINDOWS_IGNORED_NAMES}, expected
        )
        self.assertEqual(len(stray.WINDOWS_IGNORED_NAMES), 12)

    def test_default_ignored_names_are_windows_only_and_casefolded(self):
        self.assertEqual(stray.ignored_names((), False), frozenset())
        windows = stray.ignored_names((), True)
        self.assertEqual(
            windows, frozenset(n.casefold() for n in stray.WINDOWS_IGNORED_NAMES)
        )
        self.assertIn("$recycle.bin", windows)

    def test_extra_ignored_names_are_added_casefolded(self):
        self.assertEqual(stray.ignored_names(("MyFolder",), False), {"myfolder"})
        self.assertEqual(
            stray.ignored_names(("MyFolder",), True),
            stray.ignored_names((), True) | {"myfolder"},
        )

    def test_the_three_known_stray_names_name_their_likely_cause(self):
        self.assertEqual(set(stray.STRAY_NAMES), {"t", "outside", "ostvtemp"})
        for name, cause in stray.STRAY_NAMES.items():
            with self.subTest(name=name):
                self.assertIn("osp_importer.py", cause)
                self.assertIn("outside its temp dir", cause)
        self.assertIn(
            "ost_visualizer/infrastructure/mdb/importers/osp_importer.py",
            stray.STRAY_NAMES["t"],
        )
        self.assertEqual(stray.TEMP_FOLDER_PREFIX, "ostv_osp_")


class ScanTests(_Case):
    def test_scan_root_records_kind_mtime_and_file_size(self):
        self._file("a.bin", size=5, mtime=1_700_000_005)
        self._folder("Folder", mtime=1_700_000_010)
        entries = stray.scan_root(self.root)
        self.assertEqual(
            entries,
            {
                "a.bin": {
                    "is_dir": False,
                    "mtime_ns": 1_700_000_005 * _NS,
                    "size": 5,
                },
                "Folder": {
                    "is_dir": True,
                    "mtime_ns": 1_700_000_010 * _NS,
                    "size": 0,
                },
            },
        )

    def test_scan_root_does_not_descend_into_folders(self):
        os.makedirs(os.path.join(self.root, "Folder", "inner"))
        self.assertEqual(list(stray.scan_root(self.root)), ["Folder"])

    def test_scan_root_marks_an_entry_that_cannot_be_read(self):
        class _Entry:
            name = "locked.sys"

            def stat(self, follow_symlinks=True):
                raise PermissionError("denied")

        with patch.object(stray.os, "scandir", return_value=[_Entry()]):
            entries = stray.scan_root(self.root)
        self.assertEqual(
            entries, {"locked.sys": {"is_dir": None, "mtime_ns": 0, "size": 0}}
        )

    def test_scan_root_does_not_follow_links(self):
        calls = []

        class _Entry:
            name = "link"

            def stat(self, follow_symlinks=True):
                calls.append(("stat", follow_symlinks))
                return os.stat(self_root)

            def is_dir(self, follow_symlinks=True):
                calls.append(("is_dir", follow_symlinks))
                return False

        self_root = self.root
        with patch.object(stray.os, "scandir", return_value=[_Entry()]):
            stray.scan_root(self.root)
        self.assertEqual(sorted(calls), [("is_dir", False), ("stat", False)])

    def test_count_counts_only_folders_with_the_prefix(self):
        for name in ("ostv_osp_a", "ostv_osp_b", "other", "xostv_osp_c"):
            os.makedirs(os.path.join(self.temp, name))
        with open(os.path.join(self.temp, "ostv_osp_file"), "w") as handle:
            handle.write("x")
        os.makedirs(os.path.join(self.temp, "ostv_osp_a", "ostv_osp_nested"))
        self.assertEqual(stray.count_osp_folders(self.temp), 2)

    def test_count_of_an_unreadable_temp_folder_is_none_not_zero(self):
        self.assertIsNone(stray.count_osp_folders(os.path.join(self.temp, "missing")))
        self.assertEqual(stray.count_osp_folders(self.temp), 0)

    def test_count_is_none_when_the_scan_fails_midway(self):
        class _Entry:
            name = "ostv_osp_x"

            def is_dir(self):
                raise PermissionError("denied")

        with patch.object(stray.os, "scandir", return_value=[_Entry()]):
            self.assertIsNone(stray.count_osp_folders(self.temp))

    def test_take_snapshot_combines_root_temp_and_count(self):
        self._file("a.bin")
        os.makedirs(os.path.join(self.temp, "ostv_osp_1"))
        snap = stray.take_snapshot(self.root, self.temp)
        self.assertEqual(snap["version"], 1)
        self.assertEqual(snap["root"], self.root)
        self.assertEqual(snap["temp"], self.temp)
        self.assertEqual(snap["osp_folder_count"], 1)
        self.assertEqual(list(snap["entries"]), ["a.bin"])
        self.assertEqual(snap["suspects"], {})

    def test_take_snapshot_records_an_unreadable_temp_count_as_none(self):
        snap = stray.take_snapshot(self.root, os.path.join(self.temp, "missing"))
        self.assertIsNone(snap["osp_folder_count"])

    def test_take_snapshot_fingerprints_only_the_known_stray_names(self):
        for name in ("T", "outside", "OSTVTemp", "Other"):
            os.makedirs(os.path.join(self.root, name, "inner"))
        self._file("t.txt")
        snap = stray.take_snapshot(self.root, self.temp)
        self.assertEqual(sorted(snap["suspects"]), ["OSTVTemp", "T", "outside"])
        for name in ("T", "outside", "OSTVTemp"):
            self.assertEqual(
                snap["suspects"][name],
                stray.fingerprint_tree(os.path.join(self.root, name)),
            )
            self.assertEqual(snap["suspects"][name]["entries"], 2)

    def test_take_snapshot_matches_stray_names_case_insensitively(self):
        os.makedirs(os.path.join(self.root, "ostvTEMP"))
        snap = stray.take_snapshot(self.root, self.temp)
        self.assertEqual(list(snap["suspects"]), ["ostvTEMP"])


class FingerprintTests(_Case):
    def _tree(self):
        top = os.path.join(self.root, "T")
        os.makedirs(os.path.join(top, "a", "b"))
        for rel, size in (("f.txt", 3), (os.path.join("a", "g.txt"), 4)):
            with open(os.path.join(top, rel), "wb") as handle:
                handle.write(b"x" * size)
        deep = os.path.join(top, "a", "b", "h.bin")
        with open(deep, "wb") as handle:
            handle.write(b"hh")
        self._set_times(top, 1_700_000_000)
        return top, deep

    @staticmethod
    def _set_times(top, mtime):
        for folder, names, files in os.walk(top, topdown=False):
            for name in (*files, *names):
                path = os.path.join(folder, name)
                os.utime(path, ns=(mtime * _NS, mtime * _NS))
            os.utime(folder, ns=(mtime * _NS, mtime * _NS))

    def test_the_fingerprint_counts_every_entry_and_is_repeatable(self):
        top, _deep = self._tree()
        first = stray.fingerprint_tree(top)
        self.assertEqual(first, stray.fingerprint_tree(top))
        self.assertEqual(first["entries"], 6)
        self.assertIs(first["truncated"], False)
        self.assertEqual(len(first["digest"]), 64)

    def test_the_fingerprint_changes_when_a_nested_file_is_added(self):
        top, _deep = self._tree()
        before = stray.fingerprint_tree(top)
        with open(os.path.join(top, "a", "b", "new.txt"), "wb") as handle:
            handle.write(b"")
        after = stray.fingerprint_tree(top)
        self.assertEqual(after["entries"], before["entries"] + 1)
        self.assertNotEqual(after["digest"], before["digest"])

    def test_the_fingerprint_changes_when_a_nested_file_changes_size(self):
        top, deep = self._tree()
        before = stray.fingerprint_tree(top)
        mtime = os.stat(deep).st_mtime_ns
        with open(deep, "wb") as handle:
            handle.write(b"hhhhh")
        os.utime(deep, ns=(mtime, mtime))
        after = stray.fingerprint_tree(top)
        self.assertEqual(after["entries"], before["entries"])
        self.assertNotEqual(after["digest"], before["digest"])

    def test_the_fingerprint_changes_when_a_nested_mtime_changes(self):
        top, deep = self._tree()
        before = stray.fingerprint_tree(top)
        os.utime(deep, ns=(1_800_000_000 * _NS, 1_800_000_000 * _NS))
        self.assertNotEqual(stray.fingerprint_tree(top)["digest"], before["digest"])

    def test_the_fingerprint_changes_when_the_top_folder_mtime_changes(self):
        top, _deep = self._tree()
        before = stray.fingerprint_tree(top)
        os.utime(top, ns=(1_800_000_000 * _NS, 1_800_000_000 * _NS))
        self.assertNotEqual(stray.fingerprint_tree(top)["digest"], before["digest"])

    def test_the_fingerprint_changes_when_an_entry_is_renamed(self):
        top, _deep = self._tree()
        before = stray.fingerprint_tree(top)
        os.rename(os.path.join(top, "f.txt"), os.path.join(top, "renamed.txt"))
        self._set_times(top, 1_700_000_000)
        self.assertNotEqual(stray.fingerprint_tree(top)["digest"], before["digest"])

    def test_the_fingerprint_tells_a_file_from_a_folder_of_the_same_name(self):
        file_path = self._file("y", size=0)
        folder_path = self._folder("y2")
        self.assertEqual(
            os.stat(file_path).st_mtime_ns, os.stat(folder_path).st_mtime_ns
        )
        folder = stray.fingerprint_tree(folder_path)
        file = stray.fingerprint_tree(file_path)
        self.assertEqual((folder["entries"], file["entries"]), (1, 1))
        self.assertNotEqual(folder["digest"], file["digest"])

    def test_a_folder_that_is_empty_has_one_entry(self):
        folder = os.path.join(self.root, "OSTVTemp")
        os.makedirs(folder)
        result = stray.fingerprint_tree(folder)
        self.assertEqual((result["entries"], result["truncated"]), (1, False))
        self.assertEqual(result, stray.fingerprint_tree(folder))

    def test_the_walk_is_bounded_and_says_so(self):
        top, _deep = self._tree()
        full = stray.fingerprint_tree(top)
        self.assertEqual(stray.fingerprint_tree(top, limit=6), full)
        capped = stray.fingerprint_tree(top, limit=5)
        self.assertEqual((capped["entries"], capped["truncated"]), (5, True))
        self.assertNotEqual(capped["digest"], full["digest"])
        self.assertEqual(capped, stray.fingerprint_tree(top, limit=5))
        one = stray.fingerprint_tree(top, limit=1)
        self.assertEqual((one["entries"], one["truncated"]), (1, True))

    def test_the_default_bound_is_large_but_finite(self):
        self.assertEqual(stray.MAX_FINGERPRINT_ENTRIES, 20000)

    def test_a_missing_path_has_a_distinct_fingerprint(self):
        missing = stray.fingerprint_tree(os.path.join(self.root, "nothing"))
        self.assertEqual((missing["entries"], missing["truncated"]), (1, False))
        empty = os.path.join(self.root, "empty")
        os.makedirs(empty)
        self.assertNotEqual(missing["digest"], stray.fingerprint_tree(empty)["digest"])

    def test_an_unreadable_subfolder_is_part_of_the_fingerprint(self):
        top, _deep = self._tree()
        real_scandir = os.scandir
        blocked = os.path.join(top, "a")

        def scandir(path):
            if os.path.normcase(str(path)).endswith(os.path.normcase(blocked)):
                raise PermissionError("denied")
            return real_scandir(path)

        full = stray.fingerprint_tree(top)
        with patch.object(stray.os, "scandir", scandir):
            partial = stray.fingerprint_tree(top)
        self.assertNotEqual(partial["digest"], full["digest"])
        self.assertIs(partial["truncated"], False)

    def test_an_entry_that_cannot_be_read_is_part_of_the_fingerprint(self):
        top, _deep = self._tree()
        full = stray.fingerprint_tree(top)
        real_lstat = os.lstat

        def lstat(path):
            if str(path).endswith("f.txt"):
                raise PermissionError("denied")
            return real_lstat(path)

        with patch.object(stray.os, "lstat", lstat):
            partial = stray.fingerprint_tree(top)
        self.assertEqual(partial["entries"], full["entries"])
        self.assertNotEqual(partial["digest"], full["digest"])

    def test_the_fingerprint_reads_the_live_metadata_not_the_listing_cache(self):
        top, _deep = self._tree()
        seen = []
        real_lstat = os.lstat

        def lstat(path):
            seen.append(str(path))
            return real_lstat(path)

        with patch.object(stray.os, "lstat", lstat):
            stray.fingerprint_tree(top)
        self.assertEqual(len(seen), 6)
        self.assertTrue(any(path.endswith("h.bin") for path in seen))

    def _scandir_failing_for(self, folder):
        real_scandir = os.scandir
        blocked = os.path.normcase(folder)

        def scandir(path):
            if os.path.normcase(str(path)).endswith(blocked):
                raise PermissionError("denied")
            return real_scandir(path)

        return patch.object(stray.os, "scandir", scandir)

    def test_an_unreadable_folder_adds_one_record_to_the_fingerprint(self):
        top = os.path.join(self.root, "T")
        os.makedirs(os.path.join(top, "a"))
        self._set_times(top, 1_700_000_000)
        empty = stray.fingerprint_tree(top)
        with self._scandir_failing_for(os.path.join(top, "a")):
            blocked = stray.fingerprint_tree(top)
        self.assertEqual(blocked["entries"], empty["entries"] + 1)
        self.assertNotEqual(blocked["digest"], empty["digest"])

    def test_nothing_is_scanned_after_the_bound_was_hit(self):
        top = os.path.join(self.root, "T")
        for name in ("a", "b", "c"):
            os.makedirs(os.path.join(top, name))
        self._set_times(top, 1_700_000_000)
        with self._scandir_failing_for(os.path.join(top, "a")):
            capped = stray.fingerprint_tree(top, limit=3)
        self.assertEqual((capped["entries"], capped["truncated"]), (3, True))

    def test_links_are_recorded_and_not_followed_without_real_links(self):
        top, _deep = self._tree()
        full = stray.fingerprint_tree(top)
        real_scandir = os.scandir

        class _Entry:
            def __init__(self, real):
                self._real = real
                self.name = real.name
                self.path = real.path

            def is_symlink(self):
                return self.name == "a"

            def is_dir(self, follow_symlinks=True):
                return self._real.is_dir(follow_symlinks=follow_symlinks)

        class _Scan:
            def __init__(self, path):
                self._scan = real_scandir(path)

            def __enter__(self):
                return [_Entry(entry) for entry in self._scan]

            def __exit__(self, *exc):
                self._scan.close()
                return False

        with patch.object(stray.os, "scandir", _Scan):
            linked = stray.fingerprint_tree(top)
        # "a" is recorded as a link: its three descendants are not walked.
        self.assertEqual(linked["entries"], full["entries"] - 3)
        self.assertNotEqual(linked["digest"], full["digest"])

    def _digest_of_a_file(self, size, mtime_ns):
        info = SimpleNamespace(st_mode=stat.S_IFREG, st_size=size, st_mtime_ns=mtime_ns)
        with patch.object(stray.os, "lstat", return_value=info):
            return stray.fingerprint_tree(os.path.join(self.root, "f"), windows=False)

    def test_the_digest_keeps_size_and_mtime_digits_apart(self):
        digests = {
            (1, 23): self._digest_of_a_file(1, 23)["digest"],
            (12, 3): self._digest_of_a_file(12, 3)["digest"],
            (123, 0): self._digest_of_a_file(123, 0)["digest"],
            (0, 123): self._digest_of_a_file(0, 123)["digest"],
        }
        self.assertEqual(len(set(digests.values())), 4)
        self.assertEqual(self._digest_of_a_file(1, 23), self._digest_of_a_file(1, 23))

    def test_the_digest_keeps_names_kinds_and_records_apart(self):
        top, _deep = self._tree()
        full = stray.fingerprint_tree(top)
        real_scandir = os.scandir

        def renamed(old, new):
            class _Entry:
                def __init__(self, real):
                    self._real = real
                    self.name = new if real.name == old else real.name
                    self.path = real.path

                def is_symlink(self):
                    return self._real.is_symlink()

                def is_dir(self, follow_symlinks=True):
                    return self._real.is_dir(follow_symlinks=follow_symlinks)

            class _Scan:
                def __init__(self, path):
                    self._scan = real_scandir(path)

                def __enter__(self):
                    return [_Entry(entry) for entry in self._scan]

                def __exit__(self, *exc):
                    self._scan.close()
                    return False

            return _Scan

        digests = set()
        for old, new in (
            ("f.txt", "f.txt"),
            ("f.txt", "f.tx"),
            ("f.txt", "f.txt\tfile\t3"),
            ("f.txt", "f.txt\n./x"),
        ):
            with patch.object(stray.os, "scandir", renamed(old, new)):
                digests.add(stray.fingerprint_tree(top)["digest"])
        self.assertEqual(len(digests), 4)
        self.assertIn(full["digest"], digests)

    def test_a_name_that_cannot_be_encoded_does_not_stop_the_fingerprint(self):
        top, _deep = self._tree()
        real_scandir = os.scandir

        class _Entry:
            def __init__(self, real):
                self._real = real
                self.name = "bad\udc80" if real.name == "f.txt" else real.name
                self.path = real.path

            def is_symlink(self):
                return self._real.is_symlink()

            def is_dir(self, follow_symlinks=True):
                return self._real.is_dir(follow_symlinks=follow_symlinks)

        class _Scan:
            def __init__(self, path):
                self._scan = real_scandir(path)

            def __enter__(self):
                return [_Entry(entry) for entry in self._scan]

            def __exit__(self, *exc):
                self._scan.close()
                return False

        with patch.object(stray.os, "scandir", _Scan):
            first = stray.fingerprint_tree(top)
            second = stray.fingerprint_tree(top)
        self.assertEqual(first, second)
        self.assertEqual(first["entries"], 6)
        self.assertNotEqual(first["digest"], stray.fingerprint_tree(top)["digest"])

    def test_the_operating_system_decides_the_long_path_form_by_default(self):
        top, _deep = self._tree()
        for os_name, expected in (("nt", True), ("posix", False)):
            with self.subTest(os_name=os_name):
                seen = []

                def spy(path, windows):
                    seen.append(windows)
                    return path

                with patch.object(stray, "_long_path", spy):
                    with patch.object(stray.os, "name", os_name):
                        stray.fingerprint_tree(top)
                self.assertEqual(seen, [expected])
        with patch.object(stray, "_long_path", spy):
            stray.fingerprint_tree(top, windows=True)
            stray.fingerprint_tree(top, windows=False)
        self.assertEqual(seen[-2:], [True, False])

    def test_a_relative_path_gets_the_long_form_of_its_absolute_path(self):
        self.assertEqual(
            stray._long_path("rel\\folder", True),
            "\\\\?\\" + ntpath.abspath("rel\\folder"),
        )

    def test_links_are_recorded_and_not_followed(self):
        top, _deep = self._tree()
        target = os.path.join(self.base, "link_target")
        os.makedirs(os.path.join(target, "inner"))
        link = os.path.join(top, "link")
        try:
            os.symlink(target, link, target_is_directory=True)
        except (OSError, NotImplementedError):
            self.skipTest("symbolic links are not available")
        result = stray.fingerprint_tree(top)
        self.assertEqual(result["entries"], 7)

    def test_the_long_path_form_is_only_used_on_windows(self):
        self.assertEqual(
            stray._long_path("C:\\a\\b", True),
            "\\\\?\\C:\\a\\b",
        )
        self.assertEqual(stray._long_path("\\\\?\\C:\\a", True), "\\\\?\\C:\\a")
        self.assertEqual(
            stray._long_path("\\\\srv\\share\\a", True),
            "\\\\?\\UNC\\srv\\share\\a",
        )
        self.assertEqual(stray._long_path("/a/b", False), "/a/b")

    @unittest.skipUnless(os.name == "nt", "the long path form is a Windows feature")
    def test_a_path_longer_than_the_classic_limit_is_walked(self):
        top = os.path.join(self.root, "T")
        deep = top
        while len(deep) < 320:
            deep = os.path.join(deep, "a_rather_long_folder_name_to_pass_260")
        os.makedirs(stray._long_path(deep, True))
        with open(os.path.join(stray._long_path(deep, True), "f.txt"), "wb"):
            pass
        result = stray.fingerprint_tree(top)
        depth = len(os.path.relpath(deep, top).split(os.sep))
        self.assertEqual(result["entries"], depth + 2)
        self.assertEqual(result, stray.fingerprint_tree(top))


class CompareSnapshotTests(unittest.TestCase):
    @staticmethod
    def _snap(entries=None, count=0, suspects=None):
        return {
            "root": "R",
            "temp": "T",
            "osp_folder_count": count,
            "entries": entries or {},
            "suspects": suspects or {},
        }

    @staticmethod
    def _print(entries=1, digest="d1", truncated=False):
        return {"entries": entries, "truncated": truncated, "digest": digest}

    @staticmethod
    def _file(size=1, mtime=1):
        return {"is_dir": False, "mtime_ns": mtime, "size": size}

    @staticmethod
    def _dir(mtime=1):
        return {"is_dir": True, "mtime_ns": mtime, "size": 0}

    def test_identical_snapshots_have_no_findings(self):
        snap = self._snap({"a": self._file(), "d": self._dir()})
        self.assertEqual(stray.compare_snapshots(snap, snap, frozenset()), [])

    def test_new_entry_is_reported_with_its_kind(self):
        before = self._snap({"a": self._file()})
        after = self._snap({"a": self._file(), "b": self._file(), "c": self._dir()})
        self.assertEqual(
            stray.compare_snapshots(before, after, frozenset()),
            [
                "NEW top-level file: b",
                "NEW top-level folder: c",
            ],
        )

    def test_changed_file_size_mtime_and_kind_are_reported(self):
        before = self._snap(
            {"s": self._file(1, 1), "m": self._file(1, 1), "k": self._file(1, 1)}
        )
        after = self._snap(
            {"s": self._file(2, 1), "m": self._file(1, 2), "k": self._dir(1)}
        )
        findings = stray.compare_snapshots(before, after, frozenset())
        self.assertEqual(
            findings,
            [
                "CHANGED top-level entry: k (kind file -> folder)",
                "CHANGED top-level entry: m (mtime_ns 1 -> 2)",
                "CHANGED top-level entry: s (size 1 -> 2)",
            ],
        )

    def test_folder_mtime_changes_are_reported_but_size_is_not_compared(self):
        before = self._snap({"d": {"is_dir": True, "mtime_ns": 1, "size": 0}})
        same_mtime = self._snap({"d": {"is_dir": True, "mtime_ns": 1, "size": 99}})
        newer = self._snap({"d": {"is_dir": True, "mtime_ns": 2, "size": 0}})
        self.assertEqual(stray.compare_snapshots(before, same_mtime, frozenset()), [])
        self.assertEqual(
            stray.compare_snapshots(before, newer, frozenset()),
            ["CHANGED top-level entry: d (mtime_ns 1 -> 2)"],
        )

    def test_a_file_that_changes_in_size_and_mtime_is_one_finding(self):
        before = self._snap({"f": self._file(1, 1)})
        after = self._snap({"f": self._file(2, 2)})
        self.assertEqual(
            stray.compare_snapshots(before, after, frozenset()),
            ["CHANGED top-level entry: f (size 1 -> 2; mtime_ns 1 -> 2)"],
        )

    def test_removed_entries_are_not_findings(self):
        before = self._snap({"gone": self._file()})
        self.assertEqual(stray.compare_snapshots(before, self._snap(), frozenset()), [])

    def test_ignored_names_hide_changed_existing_entries_case_insensitively(self):
        before = self._snap(
            {
                "Windows": self._dir(1),
                "pagefile.sys": self._file(1, 1),
                "$Recycle.Bin": self._dir(1),
            }
        )
        after = self._snap(
            {
                "Windows": self._dir(2),
                "pagefile.sys": self._file(9, 9),
                "$Recycle.Bin": self._dir(2),
            }
        )
        self.assertEqual(
            stray.compare_snapshots(
                before, after, frozenset({"windows", "pagefile.sys", "$recycle.bin"})
            ),
            [],
        )
        self.assertEqual(len(stray.compare_snapshots(before, after, frozenset())), 3)

    def test_a_new_known_stray_name_is_reported_with_the_cause(self):
        after = self._snap(
            {"T": self._dir(), "outside": self._dir()},
            suspects={"T": self._print(), "outside": self._print()},
        )
        findings = stray.compare_snapshots(self._snap(), after, frozenset())
        self.assertEqual(len(findings), 2)
        self.assertTrue(findings[0].startswith("STRAY top-level entry: T ("))
        self.assertTrue(findings[1].startswith("STRAY top-level entry: outside ("))
        self.assertIn(stray.STRAY_NAMES["t"], findings[0])
        self.assertIn("osp_importer.py", findings[1])
        self.assertTrue(findings[0].endswith(", new since the snapshot)"))

    def test_known_stray_names_match_case_insensitively(self):
        after = self._snap(
            {"ostvtemp": self._dir()}, suspects={"ostvtemp": self._print()}
        )
        findings = stray.compare_snapshots(self._snap(), after, frozenset())
        self.assertEqual(len(findings), 1)
        self.assertTrue(findings[0].startswith("STRAY top-level entry: ostvtemp ("))

    def test_a_new_stray_name_is_marked_new_and_reported_once(self):
        after = self._snap(
            {"OSTVTemp": self._dir()}, suspects={"OSTVTemp": self._print()}
        )
        findings = stray.compare_snapshots(self._snap(), after, frozenset())
        self.assertEqual(
            findings,
            [
                f"STRAY top-level entry: OSTVTemp ({stray.STRAY_NAMES['ostvtemp']}"
                ", new since the snapshot)"
            ],
        )

    def test_a_known_stray_folder_with_an_equal_fingerprint_is_not_a_finding(self):
        snap = self._snap(
            {"T": self._dir(), "OSTVTemp": self._dir(5)},
            suspects={"T": self._print(3, "x"), "OSTVTemp": self._print(1, "y")},
        )
        self.assertEqual(stray.compare_snapshots(snap, snap, frozenset()), [])

    def test_a_known_stray_folder_whose_fingerprint_changed_is_reported(self):
        cause = stray.STRAY_NAMES["outside"]
        before = self._snap(
            {"outside": self._dir()}, suspects={"outside": self._print(2, "a")}
        )
        for after_print, expected_entries in (
            (self._print(3, "b"), "2 -> 3"),
            (self._print(2, "b"), "2 -> 2"),
            (self._print(2, "a", truncated=True), "2 -> 2"),
        ):
            with self.subTest(after_print=after_print):
                after = self._snap(
                    {"outside": self._dir(9)}, suspects={"outside": after_print}
                )
                self.assertEqual(
                    stray.compare_snapshots(before, after, frozenset()),
                    [
                        f"STRAY top-level entry: outside ({cause}, content "
                        "changed since the snapshot (entries counted: "
                        f"{expected_entries}))"
                    ],
                )

    def test_a_known_stray_folder_is_not_compared_by_its_top_level_mtime_alone(self):
        suspects = {"T": self._print(1, "same")}
        before = self._snap({"T": self._dir(1)}, suspects=suspects)
        after = self._snap({"T": self._dir(2)}, suspects=dict(suspects))
        self.assertEqual(stray.compare_snapshots(before, after, frozenset()), [])

    def test_a_removed_known_stray_folder_is_not_a_finding(self):
        before = self._snap({"T": self._dir()}, suspects={"T": self._print()})
        self.assertEqual(stray.compare_snapshots(before, self._snap(), frozenset()), [])

    def test_a_known_stray_name_without_a_before_fingerprint_counts_as_new(self):
        before = self._snap({"T": self._dir()})
        after = self._snap({"T": self._dir()}, suspects={"T": self._print()})
        findings = stray.compare_snapshots(before, after, frozenset())
        self.assertEqual(len(findings), 1)
        self.assertTrue(findings[0].endswith(", new since the snapshot)"))

    def test_ignoring_a_stray_name_does_not_hide_it(self):
        after = self._snap({"T": self._dir()}, suspects={"T": self._print()})
        ignore = frozenset({"t", "outside", "ostvtemp"})
        findings = stray.compare_snapshots(self._snap(), after, ignore, ignore)
        self.assertEqual(len(findings), 1)
        changed = self._snap({"T": self._dir()}, suspects={"T": self._print(2, "z")})
        findings = stray.compare_snapshots(after, changed, ignore, ignore)
        self.assertEqual(len(findings), 1)

    def test_a_new_entry_with_a_built_in_ignored_name_is_reported(self):
        after = self._snap({"pagefile.sys": self._file(), "Recovery": self._dir()})
        findings = stray.compare_snapshots(
            self._snap(), after, frozenset({"pagefile.sys", "recovery"})
        )
        self.assertEqual(
            findings,
            ["NEW top-level folder: Recovery", "NEW top-level file: pagefile.sys"],
        )

    def test_an_explicitly_ignored_name_hides_a_new_entry_too(self):
        after = self._snap({"Alpha": self._dir(), "Beta": self._dir()})
        findings = stray.compare_snapshots(
            self._snap(), after, frozenset({"alpha"}), frozenset({"alpha"})
        )
        self.assertEqual(findings, ["NEW top-level folder: Beta"])

    def test_an_ignored_name_that_existed_hides_its_kind_change(self):
        before = self._snap({"Windows": self._file()})
        after = self._snap({"Windows": self._dir()})
        self.assertEqual(
            stray.compare_snapshots(before, after, frozenset({"windows"})), []
        )

    def test_an_unreadable_temp_count_is_not_compared(self):
        for before_count, after_count in ((None, 3), (3, None)):
            with self.subTest(before=before_count, after=after_count):
                self.assertEqual(
                    stray.compare_snapshots(
                        self._snap(count=before_count),
                        self._snap(count=after_count),
                        frozenset(),
                    ),
                    [],
                )

    def test_osp_folder_count_increase_is_reported(self):
        self.assertEqual(
            stray.compare_snapshots(
                self._snap(count=2), self._snap(count=5), frozenset()
            ),
            ["ostv_osp_* folders in the temp folder increased from 2 to 5"],
        )

    def test_osp_folder_count_unchanged_or_lower_is_fine(self):
        for after in (2, 1):
            with self.subTest(after=after):
                self.assertEqual(
                    stray.compare_snapshots(
                        self._snap(count=2), self._snap(count=after), frozenset()
                    ),
                    [],
                )

    def test_findings_are_sorted_by_name_then_the_count(self):
        after = self._snap({"zeta": self._file(), "alpha": self._file()}, count=1)
        self.assertEqual(
            stray.compare_snapshots(self._snap(), after, frozenset()),
            [
                "NEW top-level file: alpha",
                "NEW top-level file: zeta",
                "ostv_osp_* folders in the temp folder increased from 0 to 1",
            ],
        )


class StatePathTests(_Case):
    def test_state_directly_in_the_root_is_refused_even_with_allow_repo(self):
        for allow in (False, True):
            with self.subTest(allow_repo=allow):
                path = os.path.join(self.root, "s.json")
                self.assertEqual(
                    stray.state_path_problem(path, self.root, self.repo, allow),
                    "the state file must not be written at the top level of the "
                    f"scanned root: {path}",
                )

    def test_state_inside_the_repo_is_refused_unless_allowed(self):
        os.makedirs(os.path.join(self.repo, "sub"))
        for path in (
            os.path.join(self.repo, "s.json"),
            os.path.join(self.repo, "sub", "s.json"),
        ):
            with self.subTest(path=path):
                self.assertEqual(
                    stray.state_path_problem(path, self.root, self.repo, False),
                    "the state file must not be inside the repository "
                    f"(use --allow-repo): {path}",
                )
                self.assertIsNone(
                    stray.state_path_problem(path, self.root, self.repo, True)
                )

    def test_the_repo_root_is_compared_in_its_resolved_form(self):
        indirect = os.path.join(self.states, os.pardir, "repo")
        self.assertIsNone(
            stray.state_path_problem(self.state, self.root, indirect, False)
        )
        inside = os.path.join(self.repo, "s.json")
        self.assertIsNotNone(
            stray.state_path_problem(inside, self.root, indirect, False)
        )

    def test_state_at_the_top_of_any_drive_root_is_refused(self):
        # Only read-only checks: the path is never opened for writing.
        anchor = os.path.splitdrive(self.base)[0] + os.sep
        path = os.path.join(anchor, "s.json")
        for allow in (False, True):
            with self.subTest(allow_repo=allow):
                self.assertEqual(
                    stray.state_path_problem(path, self.root, self.repo, allow),
                    "the state file must not be written at the top level of a "
                    f"drive root: {path}",
                )

    @unittest.skipUnless(os.name == "nt", "drive letters are a Windows feature")
    def test_a_state_at_the_top_of_another_drive_is_never_accepted(self):
        # The drive may or may not exist: either way the answer is a problem.
        problem = stray.state_path_problem("Z:\\x", self.root, self.repo, True)
        self.assertIsNotNone(problem)

    def _problem_with_real_form(self, typed, real):
        """state_path_problem for ``typed`` whose realpath is ``real``."""
        real_realpath = os.path.realpath

        def realpath(path, *args, **kwargs):
            if path == typed:
                return real
            return real_realpath(path, *args, **kwargs)

        with patch.object(stray.os.path, "realpath", realpath):
            return stray.state_path_problem(typed, self.root, self.repo, True)

    def test_a_drive_root_is_refused_when_either_the_typed_or_real_form_is_one(self):
        anchor = os.path.splitdrive(self.base)[0] + os.sep
        at_root = os.path.join(anchor, "s.json")
        normal = os.path.join(self.states, "s.json")
        expected = (
            "the state file must not be written at the top level of a drive root: "
        )
        # typed at a drive root, resolves to a normal folder
        self.assertEqual(
            self._problem_with_real_form(at_root, normal), expected + at_root
        )
        # typed as a normal folder, resolves to a drive root (link or mapped drive)
        self.assertEqual(
            self._problem_with_real_form(normal, at_root), expected + normal
        )
        # neither form is a drive root
        self.assertIsNone(self._problem_with_real_form(normal, normal))

    def test_state_elsewhere_is_accepted(self):
        self.assertIsNone(
            stray.state_path_problem(self.state, self.root, self.repo, False)
        )

    def test_a_sibling_with_the_repo_name_as_prefix_is_not_inside_the_repo(self):
        sibling = os.path.join(self.base, "repo_other")
        os.makedirs(sibling)
        self.assertIsNone(
            stray.state_path_problem(
                os.path.join(sibling, "s.json"), self.root, self.repo, False
            )
        )

    def test_a_missing_state_folder_is_refused(self):
        problem = stray.state_path_problem(
            os.path.join(self.states, "missing", "s.json"),
            self.root,
            self.repo,
            False,
        )
        self.assertEqual(
            problem,
            "the folder of the state file does not exist: "
            f"{os.path.join(self.states, 'missing')}",
        )

    def test_state_on_another_drive_than_the_repo_is_not_inside_it(self):
        with patch.object(stray.os.path, "commonpath", side_effect=ValueError):
            self.assertIsNone(
                stray.state_path_problem(self.state, self.root, self.repo, False)
            )


class MainTests(_Case):
    def test_snapshot_writes_the_state_file_and_reports_counts(self):
        self._file("a.bin", size=4, mtime=1_700_000_001)
        os.makedirs(os.path.join(self.temp, "ostv_osp_1"))
        code, out, err = self._run("snapshot")
        self.assertEqual((code, err), (0, ""))
        self.assertEqual(
            out,
            f"snapshot written to {self.state}: 1 top-level entries, "
            "1 ostv_osp_* folders\n",
        )
        with open(self.state, encoding="utf-8") as handle:
            data = json.load(handle)
        self.assertEqual(data["root"], self.root)
        self.assertEqual(data["temp"], self.temp)
        self.assertEqual(data["osp_folder_count"], 1)
        self.assertEqual(
            data["entries"],
            {
                "a.bin": {
                    "is_dir": False,
                    "mtime_ns": 1_700_000_001 * _NS,
                    "size": 4,
                }
            },
        )

    def test_compare_of_an_unchanged_root_is_clean(self):
        self._file("a.bin")
        self._folder("Folder")
        self.assertEqual(self._run("snapshot")[0], 0)
        code, out, err = self._run("compare")
        self.assertEqual((code, out, err), (0, "no stray folders\n", ""))

    def test_compare_fails_on_a_new_top_level_entry_and_prints_each_finding(self):
        self.assertEqual(self._run("snapshot")[0], 0)
        self._folder("Surprise")
        self._file("new.txt")
        code, out, err = self._run("compare")
        self.assertEqual(code, 1)
        self.assertEqual(
            out.splitlines(),
            [
                "NEW top-level folder: Surprise",
                "NEW top-level file: new.txt",
                "2 stray finding(s)",
            ],
        )
        self.assertNotIn("no stray folders", out)
        self.assertEqual(err, "")

    def test_compare_fails_when_an_entry_is_removed_from_the_state_by_hand(self):
        self._file("a.bin")
        self._file("b.bin")
        self.assertEqual(self._run("snapshot")[0], 0)
        with open(self.state, encoding="utf-8") as handle:
            data = json.load(handle)
        del data["entries"]["b.bin"]
        with open(self.state, "w", encoding="utf-8") as handle:
            json.dump(data, handle)
        code, out, _err = self._run("compare")
        self.assertEqual(code, 1)
        self.assertIn("NEW top-level file: b.bin", out)

    def test_compare_fails_on_a_changed_file_and_a_changed_folder(self):
        path = self._file("a.bin", size=1)
        folder = self._folder("Folder")
        self.assertEqual(self._run("snapshot")[0], 0)
        with open(path, "ab") as handle:
            handle.write(b"more")
        os.utime(folder, ns=(1_800_000_000 * _NS, 1_800_000_000 * _NS))
        code, out, _err = self._run("compare")
        self.assertEqual(code, 1)
        self.assertIn("CHANGED top-level entry: Folder (mtime_ns", out)
        self.assertIn("CHANGED top-level entry: a.bin (size 1 -> 5", out)

    def test_ignored_system_names_are_skipped_only_on_windows(self):
        self._folder("Windows")
        self._folder("$Recycle.Bin")
        self.assertEqual(self._run("snapshot", windows=True)[0], 0)
        self._folder("Windows", mtime=1_800_000_000)
        self._folder("$Recycle.Bin", mtime=1_800_000_000)
        self.assertEqual(
            self._run("compare", windows=True),
            (0, "no stray folders\n", ""),
        )
        code, out, _err = self._run("compare", windows=False)
        self.assertEqual(code, 1)
        self.assertIn("CHANGED top-level entry: $Recycle.Bin", out)
        self.assertIn("CHANGED top-level entry: Windows", out)

    def test_a_system_name_that_appears_after_the_snapshot_is_reported(self):
        self.assertEqual(self._run("snapshot", windows=True)[0], 0)
        self._file("pagefile.sys")
        self._folder("Recovery")
        code, out, _err = self._run("compare", windows=True)
        self.assertEqual(code, 1)
        self.assertEqual(
            out.splitlines(),
            [
                "NEW top-level folder: Recovery",
                "NEW top-level file: pagefile.sys",
                "2 stray finding(s)",
            ],
        )

    def test_ignore_option_also_hides_a_new_entry_of_that_name(self):
        self.assertEqual(self._run("snapshot", windows=True)[0], 0)
        self._folder("Recovery")
        self.assertEqual(
            self._run("compare", "--ignore", "RECOVERY", windows=True),
            (0, "no stray folders\n", ""),
        )

    def test_ignore_option_adds_names_case_insensitively_and_repeats(self):
        self.assertEqual(self._run("snapshot")[0], 0)
        self._folder("Alpha")
        self._folder("Beta")
        self._folder("Gamma")
        code, out, _err = self._run("compare", "--ignore", "ALPHA", "--ignore", "beta")
        self.assertEqual(code, 1)
        self.assertEqual(
            out.splitlines(), ["NEW top-level folder: Gamma", "1 stray finding(s)"]
        )

    def _fill_known_strays(self):
        for name in ("T", "outside", "OSTVTemp"):
            folder = self._folder(name)
            deep = os.path.join(folder, "deep", "er")
            os.makedirs(deep)
            path = os.path.join(deep, "f.txt")
            with open(path, "wb") as handle:
                handle.write(b"abc")
            for item in (path, deep, os.path.dirname(deep), folder):
                os.utime(item, ns=(1_700_000_000 * _NS,) * 2)

    def test_known_stray_folders_that_existed_and_did_not_change_are_not_strays(self):
        self._fill_known_strays()
        self.assertEqual(self._run("snapshot")[0], 0)
        self.assertEqual(self._run("compare"), (0, "no stray folders\n", ""))

    def test_an_empty_known_stray_folder_that_existed_before_is_not_a_stray(self):
        for name in ("T", "outside", "OSTVTemp"):
            self._folder(name)
        self.assertEqual(self._run("snapshot")[0], 0)
        self.assertEqual(self._run("compare"), (0, "no stray folders\n", ""))

    def test_known_stray_folders_that_appear_after_the_snapshot_fail(self):
        self.assertEqual(self._run("snapshot")[0], 0)
        self._fill_known_strays()
        code, out, _err = self._run("compare")
        self.assertEqual(code, 1)
        lines = out.splitlines()
        self.assertEqual(len(lines), 4)
        self.assertEqual(
            sorted(line.split(" (")[0] for line in lines[:3]),
            [
                "STRAY top-level entry: OSTVTemp",
                "STRAY top-level entry: T",
                "STRAY top-level entry: outside",
            ],
        )
        for line in lines[:3]:
            self.assertTrue(line.endswith(", new since the snapshot)"))
        self.assertIn("osp_importer.py", out)
        self.assertEqual(lines[3], "3 stray finding(s)")

    def test_a_known_stray_folder_that_changed_after_the_snapshot_fails(self):
        self._fill_known_strays()
        self.assertEqual(self._run("snapshot")[0], 0)
        cause = stray.STRAY_NAMES["outside"]
        changed = os.path.join(self.root, "outside", "deep", "er", "f.txt")
        with open(changed, "ab") as handle:
            handle.write(b"more")
        code, out, _err = self._run("compare")
        self.assertEqual(code, 1)
        self.assertEqual(
            out.splitlines(),
            [
                f"STRAY top-level entry: outside ({cause}, content changed since "
                "the snapshot (entries counted: 4 -> 4))",
                "1 stray finding(s)",
            ],
        )

    def test_new_content_in_an_empty_known_stray_folder_fails(self):
        for name in ("T", "outside", "OSTVTemp"):
            with self.subTest(name=name):
                folder = self._folder(name)
                self.assertEqual(self._run("snapshot")[0], 0)
                with open(os.path.join(folder, "late.txt"), "wb") as handle:
                    handle.write(b"x")
                code, out, _err = self._run("compare")
                self.assertEqual(code, 1)
                self.assertIn(f"STRAY top-level entry: {name} (", out)
                self.assertIn("(entries counted: 1 -> 2)", out)
                shutil.rmtree(folder)

    def test_a_removed_known_stray_folder_is_not_a_finding(self):
        self._fill_known_strays()
        self.assertEqual(self._run("snapshot")[0], 0)
        for name in ("T", "outside", "OSTVTemp"):
            shutil.rmtree(os.path.join(self.root, name))
        self.assertEqual(self._run("compare"), (0, "no stray folders\n", ""))

    def test_ignoring_a_known_stray_name_does_not_hide_a_change(self):
        self._folder("T")
        self.assertEqual(self._run("snapshot")[0], 0)
        os.makedirs(os.path.join(self.root, "T", "sub"))
        code, out, _err = self._run("compare", "--ignore", "t")
        self.assertEqual(code, 1)
        self.assertIn("STRAY top-level entry: T (", out)

    def test_compare_fails_on_more_osp_folders_in_the_temp_folder(self):
        os.makedirs(os.path.join(self.temp, "ostv_osp_old"))
        self.assertEqual(self._run("snapshot")[0], 0)
        os.makedirs(os.path.join(self.temp, "ostv_osp_leaked"))
        code, out, _err = self._run("compare")
        self.assertEqual(code, 1)
        self.assertIn("increased from 1 to 2", out)
        shutil.rmtree(os.path.join(self.temp, "ostv_osp_old"))
        shutil.rmtree(os.path.join(self.temp, "ostv_osp_leaked"))
        self.assertEqual(self._run("compare")[0], 0)

    def test_compare_never_modifies_the_state_file(self):
        self._file("a.bin")
        self.assertEqual(self._run("snapshot")[0], 0)
        with open(self.state, "rb") as handle:
            before = handle.read()
        self._folder("New")
        self.assertEqual(self._run("compare")[0], 1)
        with open(self.state, "rb") as handle:
            self.assertEqual(handle.read(), before)

    def test_snapshot_refuses_a_state_inside_the_root_and_writes_nothing(self):
        inside = os.path.join(self.root, "state.json")
        code, out, err = self._run("snapshot", state=inside)
        self.assertEqual((code, out), (2, ""))
        self.assertEqual(
            err,
            "check_stray_folders: the state file must not be written at the top "
            f"level of the scanned root: {inside}\n",
        )
        self.assertEqual(os.listdir(self.root), [])

    def test_snapshot_refuses_a_state_at_the_top_of_a_drive_root(self):
        anchor = os.path.splitdrive(self.base)[0] + os.sep
        path = os.path.join(anchor, "ostv_stray_probe_state.json")
        # Guard: a tool that does not refuse must not be able to create the file.
        with patch.object(stray, "open", create=True, side_effect=AssertionError):
            code, out, err = self._run("snapshot", "--allow-repo", state=path)
        self.assertEqual((code, out), (2, ""))
        self.assertEqual(
            err,
            "check_stray_folders: the state file must not be written at the top "
            f"level of a drive root: {path}\n",
        )
        self.assertFalse(os.path.exists(path))

    def test_snapshot_refuses_a_state_inside_the_repo_unless_allowed(self):
        inside = os.path.join(self.repo, "state.json")
        code, out, err = self._run("snapshot", state=inside)
        self.assertEqual((code, out), (2, ""))
        self.assertEqual(
            err,
            "check_stray_folders: the state file must not be inside the "
            f"repository (use --allow-repo): {inside}\n",
        )
        self.assertFalse(os.path.exists(inside))
        code, _out, err = self._run("snapshot", "--allow-repo", state=inside)
        self.assertEqual((code, err), (0, ""))
        self.assertTrue(os.path.isfile(inside))

    def test_snapshot_never_creates_the_state_folder(self):
        missing = os.path.join(self.states, "new_top", "state.json")
        code, _out, err = self._run("snapshot", state=missing)
        self.assertEqual(code, 2)
        self.assertEqual(
            err,
            "check_stray_folders: the folder of the state file does not exist: "
            f"{os.path.dirname(missing)}\n",
        )
        self.assertEqual(os.listdir(self.states), [])

    def test_compare_without_a_state_file_is_an_error(self):
        code, out, err = self._run("compare")
        self.assertEqual((code, out), (2, ""))
        self.assertEqual(
            err,
            f"check_stray_folders: cannot read the state file {self.state}: "
            f"{self._open_error(self.state, 'r')}\n",
        )

    def test_compare_with_an_invalid_state_file_is_an_error(self):
        for text, reason in (
            ("not json", "Expecting value: line 1 column 1 (char 0)"),
            ("[]", "unexpected structure"),
            ('{"entries": {}}', "unexpected structure"),
        ):
            with self.subTest(text=text):
                with open(self.state, "w", encoding="utf-8") as handle:
                    handle.write(text)
                code, out, err = self._run("compare")
                self.assertEqual((code, out), (2, ""))
                self.assertEqual(
                    err,
                    f"check_stray_folders: {self.state} is not a valid "
                    f"snapshot: {reason}\n",
                )

    def test_compare_with_a_state_of_the_wrong_shape_is_exit_code_two(self):
        self._file("a.bin")
        self._folder("T")
        self.assertEqual(self._run("snapshot")[0], 0)
        with open(self.state, encoding="utf-8") as handle:
            good = json.load(handle)
        file_entry = {"is_dir": False, "mtime_ns": 1, "size": 1}
        suspect = {"entries": 1, "truncated": False, "digest": "d"}
        broken = {
            "entry is a number": ("entries", "a.bin", 5),
            "entry is a list": ("entries", "a.bin", []),
            "entry is null": ("entries", "a.bin", None),
            "entry misses is_dir": ("entries", "a.bin", {"mtime_ns": 1, "size": 1}),
            "entry misses mtime_ns": ("entries", "a.bin", {"is_dir": False, "size": 1}),
            "entry misses size": ("entries", "a.bin", {"is_dir": False, "mtime_ns": 1}),
            "is_dir is a string": ("entries", "a.bin", {**file_entry, "is_dir": "no"}),
            "is_dir is a number": ("entries", "a.bin", {**file_entry, "is_dir": 1}),
            "mtime is a float": ("entries", "a.bin", {**file_entry, "mtime_ns": 1.5}),
            "mtime is a bool": ("entries", "a.bin", {**file_entry, "mtime_ns": True}),
            "size is a string": ("entries", "a.bin", {**file_entry, "size": "3"}),
            "size is a bool": ("entries", "a.bin", {**file_entry, "size": False}),
            "suspects is a list": ("suspects", None, []),
            "suspect is a number": ("suspects", "T", 5),
            "suspect misses digest": (
                "suspects",
                "T",
                {"entries": 1, "truncated": False},
            ),
            "suspect digest is a number": ("suspects", "T", {**suspect, "digest": 5}),
            "suspect entries is a string": (
                "suspects",
                "T",
                {**suspect, "entries": "1"},
            ),
            "suspect entries is a bool": (
                "suspects",
                "T",
                {**suspect, "entries": True},
            ),
            "suspect truncated is a number": (
                "suspects",
                "T",
                {**suspect, "truncated": 0},
            ),
            "suspect misses entries": (
                "suspects",
                "T",
                {"truncated": False, "digest": "d"},
            ),
            "suspect misses truncated": (
                "suspects",
                "T",
                {"entries": 1, "digest": "d"},
            ),
            "suspects missing": ("suspects", None, "delete"),
            "entries missing": ("entries", None, "delete"),
            "count is a string": ("osp_folder_count", None, "3"),
            "count is a bool": ("osp_folder_count", None, True),
            "count is a float": ("osp_folder_count", None, 1.5),
            "count missing": ("osp_folder_count", None, "delete"),
            "temp is a number": ("temp", None, 5),
            "root is a number": ("root", None, 5),
            "version is another": ("version", None, 2),
        }
        for label, (field, key, value) in broken.items():
            with self.subTest(label):
                data = json.loads(json.dumps(good))
                if isinstance(value, str) and value == "delete":
                    del data[field]
                elif key is None:
                    data[field] = value
                else:
                    data[field][key] = value
                with open(self.state, "w", encoding="utf-8") as handle:
                    json.dump(data, handle)
                code, out, err = self._run("compare")
                self.assertEqual((code, out), (2, ""))
                self.assertEqual(
                    err,
                    f"check_stray_folders: {self.state} is not a valid "
                    "snapshot: unexpected structure\n",
                )

    def test_compare_accepts_an_unreadable_entry_and_a_missing_count_in_the_state(self):
        self._file("a.bin")
        self.assertEqual(self._run("snapshot")[0], 0)
        with open(self.state, encoding="utf-8") as handle:
            data = json.load(handle)
        data["entries"]["locked.sys"] = {"is_dir": None, "mtime_ns": 0, "size": 0}
        data["osp_folder_count"] = None
        with open(self.state, "w", encoding="utf-8") as handle:
            json.dump(data, handle)
        code, out, _err = self._run("compare")
        self.assertEqual((code, out), (0, "no stray folders\n"))

    def test_compare_with_a_state_for_another_root_or_temp_is_an_error(self):
        self.assertEqual(self._run("snapshot")[0], 0)
        other = os.path.join(self.base, "other")
        os.makedirs(other)
        for option, value in (("--root", other), ("--temp", other)):
            with self.subTest(option=option):
                argv = [
                    "compare",
                    "--state",
                    self.state,
                    "--root",
                    self.root,
                    "--temp",
                    self.temp,
                ]
                argv[argv.index(option) + 1] = value
                err = io.StringIO()
                with contextlib.redirect_stderr(err), contextlib.redirect_stdout(
                    io.StringIO()
                ):
                    code = stray.main(argv, windows=False, repo_root=self.repo)
                self.assertEqual(code, 2)
                now_root = other if option == "--root" else self.root
                now_temp = other if option == "--temp" else self.temp
                self.assertEqual(
                    err.getvalue(),
                    "check_stray_folders: the state file was taken for root "
                    f"{self.root} and temp {self.temp}, not for root {now_root} "
                    f"and temp {now_temp}\n",
                )

    def test_an_unreadable_root_is_an_error(self):
        missing = os.path.join(self.base, "no_such_root")
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = stray.main(
                [
                    "snapshot",
                    "--state",
                    self.state,
                    "--root",
                    missing,
                    "--temp",
                    self.temp,
                ],
                windows=False,
                repo_root=self.repo,
            )
        self.assertEqual((code, out.getvalue()), (2, ""))
        self.assertEqual(
            err.getvalue(),
            f"check_stray_folders: cannot scan {missing}: "
            f"{self._scan_error(missing)}\n",
        )
        self.assertFalse(os.path.exists(self.state))

    @staticmethod
    def _scan_error(folder):
        try:
            os.scandir(folder)
        except OSError as exc:
            return str(exc)
        raise AssertionError("expected an OSError")

    @staticmethod
    def _open_error(path, mode):
        try:
            open(path, mode)
        except OSError as exc:
            return str(exc)
        raise AssertionError("expected an OSError")

    def _run_with_fingerprint_limit(self, command, limit):
        real = stray.fingerprint_tree

        def limited(path):
            return real(path, limit=limit)

        with patch.object(stray, "fingerprint_tree", limited):
            return self._run(command)

    def _stray_folder_with_files(self, count):
        folder = self._folder("T")
        for number in range(count):
            self._file_in(folder, f"f{number}.txt")
        os.utime(folder, ns=(1_700_000_000 * _NS,) * 2)

    @staticmethod
    def _file_in(folder, name):
        path = os.path.join(folder, name)
        with open(path, "wb") as handle:
            handle.write(b"x")
        os.utime(path, ns=(1_700_000_000 * _NS,) * 2)

    def test_compare_warns_once_when_a_fingerprint_was_truncated(self):
        warning = (
            "check_stray_folders: fingerprint truncated at 3 entries: changes "
            "beyond are not detected\n"
        )
        self._stray_folder_with_files(5)
        self.assertEqual(self._run_with_fingerprint_limit("snapshot", 3)[0], 0)
        # unchanged: same exit code as without the warning
        code, out, err = self._run_with_fingerprint_limit("compare", 3)
        self.assertEqual((code, out, err), (0, "no stray folders\n", warning))
        # truncated only in the snapshot
        code, out, err = self._run("compare")
        self.assertEqual((code, err), (1, warning))
        self.assertIn("STRAY top-level entry: T (", out)
        # truncated only at compare time
        self.assertEqual(self._run("snapshot")[0], 0)
        code, out, err = self._run_with_fingerprint_limit("compare", 3)
        self.assertEqual((code, err), (1, warning))

    def test_compare_does_not_warn_without_a_truncated_fingerprint(self):
        self._stray_folder_with_files(2)
        self.assertEqual(self._run("snapshot")[0], 0)
        self.assertEqual(self._run("compare"), (0, "no stray folders\n", ""))
        self.assertEqual(self._run_with_fingerprint_limit("snapshot", 3)[0], 0)
        self.assertEqual(
            self._run_with_fingerprint_limit("compare", 3),
            (0, "no stray folders\n", ""),
        )

    def test_the_truncation_warning_names_the_largest_bound_and_prints_once(self):
        for name in ("T", "outside"):
            folder = self._folder(name)
            for number in range(5):
                self._file_in(folder, f"f{number}.txt")
            os.utime(folder, ns=(1_700_000_000 * _NS,) * 2)
        self.assertEqual(self._run_with_fingerprint_limit("snapshot", 4)[0], 0)
        code, _out, err = self._run_with_fingerprint_limit("compare", 3)
        self.assertEqual(code, 1)
        self.assertEqual(
            err,
            "check_stray_folders: fingerprint truncated at 4 entries: changes "
            "beyond are not detected\n",
        )

    def test_compare_fails_when_the_temp_folder_can_no_longer_be_read(self):
        os.makedirs(os.path.join(self.temp, "ostv_osp_old"))
        self.assertEqual(self._run("snapshot")[0], 0)
        shutil.rmtree(self.temp)
        code, out, err = self._run("compare")
        self.assertEqual((code, out), (2, ""))
        self.assertEqual(
            err,
            f"check_stray_folders: cannot read the temp folder {self.temp}: the "
            "snapshot counted 1 ostv_osp_* folders\n",
        )

    def test_an_empty_temp_folder_that_cannot_be_read_later_is_still_an_error(self):
        self.assertEqual(self._run("snapshot")[0], 0)
        shutil.rmtree(self.temp)
        self.assertEqual(self._run("compare")[0], 2)

    def test_a_temp_folder_unreadable_in_both_snapshots_is_not_an_error(self):
        shutil.rmtree(self.temp)
        code, out, err = self._run("snapshot")
        self.assertEqual((code, err), (0, ""))
        self.assertEqual(
            out,
            f"snapshot written to {self.state}: 0 top-level entries, "
            "ostv_osp_* folders unreadable\n",
        )
        self.assertEqual(self._run("compare"), (0, "no stray folders\n", ""))

    def test_compare_reports_a_root_that_can_no_longer_be_scanned(self):
        self.assertEqual(self._run("snapshot")[0], 0)
        shutil.rmtree(self.root)
        code, out, err = self._run("compare")
        self.assertEqual((code, out), (2, ""))
        self.assertEqual(
            err,
            "check_stray_folders: cannot scan "
            f"{self.root}: {self._scan_error(self.root)}\n",
        )

    def test_snapshot_reports_a_state_file_that_cannot_be_written(self):
        target = os.path.join(self.states, "a_folder")
        os.makedirs(target)
        code, out, err = self._run("snapshot", state=target)
        self.assertEqual((code, out), (2, ""))
        self.assertEqual(
            err,
            f"check_stray_folders: cannot write the state file {target}: "
            f"{self._open_error(target, 'w')}\n",
        )

    def test_a_snapshot_that_cannot_be_serialised_leaves_no_state_file(self):
        bad = {"entries": {}, "osp_folder_count": 0, "bad": object()}
        with patch.object(stray, "take_snapshot", return_value=bad):
            with self.assertRaises(TypeError):
                self._run("snapshot")
        self.assertFalse(os.path.exists(self.state))

    def test_without_an_explicit_windows_flag_the_operating_system_decides(self):
        self._folder("Windows")
        self.assertEqual(self._run("snapshot")[0], 0)
        self._folder("Windows", mtime=1_800_000_000)
        argv = ["compare", "--state", self.state, "--root", self.root]
        argv += ["--temp", self.temp]
        for os_name, expected in (("nt", 0), ("posix", 1)):
            with self.subTest(os_name=os_name):
                with patch.object(stray.os, "name", os_name):
                    with contextlib.redirect_stdout(io.StringIO()):
                        self.assertEqual(stray.main(argv), expected)

    def test_the_state_option_is_required_and_a_command_is_required(self):
        for argv in (["snapshot"], ["compare"], []):
            with self.subTest(argv=argv):
                with contextlib.redirect_stderr(io.StringIO()):
                    with self.assertRaises(SystemExit) as caught:
                        stray.main(argv)
                self.assertEqual(caught.exception.code, 2)

    def test_defaults_resolve_the_real_root_and_temp_without_scanning_them(self):
        seen = {}

        def fake_snapshot(root, temp):
            seen["args"] = (root, temp)
            return {
                "version": 1,
                "root": root,
                "temp": temp,
                "osp_folder_count": 0,
                "entries": {},
            }

        with patch.object(stray, "take_snapshot", fake_snapshot):
            with patch.object(stray, "system_drive_root", return_value="<root>"):
                with patch.object(stray.tempfile, "gettempdir", return_value="<tmp>"):
                    with contextlib.redirect_stdout(io.StringIO()):
                        code = stray.main(
                            ["snapshot", "--state", self.state],
                            windows=False,
                            repo_root=self.repo,
                        )
        self.assertEqual(code, 0)
        self.assertEqual(seen["args"], ("<root>", "<tmp>"))

    def test_default_repo_root_is_the_repository_of_the_tool(self):
        self.assertEqual(
            os.path.realpath(stray.REPO_ROOT),
            os.path.realpath(os.path.join(os.path.dirname(stray.__file__), os.pardir)),
        )

    def test_the_default_repo_root_is_the_one_guarded(self):
        # REPO_ROOT is replaced by a sandbox folder: the real repository is
        # never used as a state location, not even by a failing mutant.
        inside = os.path.join(self.repo, "state.json")
        argv = ["snapshot", "--state", inside, "--root", self.root]
        argv += ["--temp", self.temp]
        with patch.object(stray, "REPO_ROOT", self.repo):
            with contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(stray.main(argv, windows=False), 2)
        self.assertFalse(os.path.exists(inside))


if __name__ == "__main__":
    unittest.main()
