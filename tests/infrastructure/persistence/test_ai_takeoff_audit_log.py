import dataclasses
import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from ost_visualizer.infrastructure.persistence.ai_takeoff_audit_log import (
    AUDIT_KEEP_FILES,
    AUDIT_MAX_BYTES,
    AUDIT_RETENTION_DAYS,
    AiTakeoffAuditLog,
    restrict_to_current_user,
)
from ost_visualizer.application.dtos.ai_takeoff_audit_dtos import (
    AuditEntry,
    hash_arguments,
)

KEY = "0123456789abcdef0123456789abcdef"


class AuditLogTestCase(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.directory = Path(directory.name) / "audit"
        self.now = 1_760_000_000.0
        self.secured = []
        self.log = AiTakeoffAuditLog(
            self.directory,
            clock=lambda: self.now,
            secure_directory=self.secured.append,
        )

    def lines(self, name=f"{KEY}.jsonl"):
        return [
            json.loads(line)
            for line in (self.directory / name).read_text(encoding="utf-8").splitlines()
        ]


class AuditEntryTests(AuditLogTestCase):
    def test_lone_surrogates_never_drop_the_entry(self):
        self.log.record(
            KEY,
            AuditEntry(
                event="tool",
                tool="discard_changeset",
                changeset_id="\ud800cs-1",
                outcome="not_found\udc00",
            ),
        )
        (line,) = self.lines()
        self.assertEqual(line["changeset_id"], "\ufffdcs-1")
        self.assertEqual(line["outcome"], "not_found\ufffd")

    def test_entries_are_appended_with_only_the_planned_fields(self):
        self.log.record(
            KEY,
            AuditEntry(
                event="tool",
                tool="propose_element",
                input_hash=hash_arguments({"page_uid": "p1", "thickness_in": 8}),
                changeset_id="cs-1",
                outcome="ok",
            ),
        )
        self.log.record(
            KEY,
            AuditEntry(
                event="applied",
                changeset_id="cs-1",
                summary="One slab",
                approver="estimator",
                outcome="applied",
                assumption_ids=("a1",),
            ),
        )
        first, second = self.lines()
        self.assertEqual(
            set(first),
            {
                "time",
                "event",
                "tool",
                "input_hash",
                "changeset_id",
                "summary",
                "approver",
                "outcome",
                "assumption_ids",
            },
        )
        self.assertEqual(first["time"], "2025-10-09T08:53:20Z")
        self.assertEqual(len(first["input_hash"]), 64)
        self.assertEqual(second["assumption_ids"], ["a1"])
        self.assertEqual(self.secured, [self.directory])

    def test_argument_hashes_are_stable_and_never_contain_the_arguments(self):
        first = hash_arguments({"b": 1, "a": "secret-token-123"})
        self.assertEqual(first, hash_arguments({"a": "secret-token-123", "b": 1}))
        self.assertNotEqual(first, hash_arguments({"b": 1, "a": "secret-token-124"}))
        self.log.record(
            KEY, AuditEntry(event="tool", tool="propose_element", input_hash=first)
        )
        raw = (self.directory / f"{KEY}.jsonl").read_bytes()
        self.assertIn(first.encode("ascii"), raw)
        self.assertNotIn(b"secret-token-123", raw)

    def test_entries_are_immutable(self):
        entry = AuditEntry(event="tool")
        with self.assertRaises(dataclasses.FrozenInstanceError):
            entry.event = "applied"

    def test_non_ascii_text_is_written_as_utf8_not_escaped(self):
        self.log.record(KEY, AuditEntry(event="tool", summary="caf\u00e9 \u2265 8"))
        raw = (self.directory / f"{KEY}.jsonl").read_bytes()
        self.assertIn("caf\u00e9 \u2265 8".encode("utf-8"), raw)
        self.assertNotIn(b"\\u00e9", raw)
        self.assertEqual(self.lines()[0]["summary"], "caf\u00e9 \u2265 8")

    def test_a_missing_nested_directory_is_created_and_secured_once(self):
        nested = self.directory / "a" / "b"
        log = AiTakeoffAuditLog(
            nested, clock=lambda: self.now, secure_directory=self.secured.append
        )
        log.record(KEY, AuditEntry(event="tool"))
        log.record(KEY, AuditEntry(event="tool"))
        lines = (nested / f"{KEY}.jsonl").read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(lines), 2)
        self.assertEqual(self.secured, [nested])

    def test_an_existing_directory_is_never_re_secured(self):
        self.directory.mkdir(parents=True)
        self.log.record(KEY, AuditEntry(event="tool"))
        self.assertEqual(self.secured, [])
        self.assertEqual(len(self.lines()), 1)

    def test_text_fields_are_bounded_and_control_free(self):
        self.log.record(
            KEY,
            AuditEntry(
                event="applied\n",
                summary="ok\u202e\x1b[31m" + "x" * 500,
                approver="a\nb",
            ),
        )
        (entry,) = self.lines()
        self.assertEqual(entry["event"], "applied ")
        self.assertTrue(entry["summary"].startswith("ok[31m"))
        self.assertLessEqual(len(entry["summary"]), 200)
        self.assertEqual(entry["approver"], "a b")

    def test_unkeyed_bids_use_a_shared_file_and_bad_keys_are_refused(self):
        self.log.record(None, AuditEntry(event="tool", tool="list_sheets"))
        self.assertEqual(self.lines("unkeyed.jsonl")[0]["tool"], "list_sheets")
        with self.assertRaises(ValueError):
            self.log.record("../x", AuditEntry(event="tool"))


class AuditRotationTests(AuditLogTestCase):
    def test_limits_match_the_plan(self):
        self.assertEqual(
            (AUDIT_MAX_BYTES, AUDIT_KEEP_FILES, AUDIT_RETENTION_DAYS),
            (10 * 1024 * 1024, 5, 365),
        )

    def test_files_rotate_at_the_size_limit_and_keep_five(self):
        log = AiTakeoffAuditLog(
            self.directory,
            clock=lambda: self.now,
            max_bytes=300,
            secure_directory=lambda _p: None,
        )
        for index in range(40):
            log.record(KEY, AuditEntry(event="tool", tool=f"t{index}"))
        names = sorted(path.name for path in self.directory.iterdir())
        self.assertEqual(
            names,
            [f"{KEY}.{n}.jsonl" for n in range(1, 5)] + [f"{KEY}.jsonl"],
        )
        for path in self.directory.iterdir():
            self.assertLessEqual(path.stat().st_size, 300)
        self.assertEqual(self.lines()[-1]["tool"], "t39")

    def small_log(self, max_bytes, keep_files=AUDIT_KEEP_FILES, retention_days=365):
        return AiTakeoffAuditLog(
            self.directory,
            clock=lambda: self.now,
            max_bytes=max_bytes,
            keep_files=keep_files,
            retention_days=retention_days,
            secure_directory=lambda _p: None,
        )

    def names(self):
        return sorted(path.name for path in self.directory.iterdir())

    def test_a_file_exactly_at_the_size_limit_is_not_rotated(self):
        self.small_log(10_000).record(KEY, AuditEntry(event="tool", tool="t"))
        size = (self.directory / f"{KEY}.jsonl").stat().st_size
        (self.directory / f"{KEY}.jsonl").unlink()
        log = self.small_log(2 * size)
        log.record(KEY, AuditEntry(event="tool", tool="t"))
        log.record(KEY, AuditEntry(event="tool", tool="t"))
        self.assertEqual(self.names(), [f"{KEY}.jsonl"])
        self.assertEqual((self.directory / f"{KEY}.jsonl").stat().st_size, 2 * size)
        log.record(KEY, AuditEntry(event="tool", tool="t"))
        self.assertEqual(self.names(), [f"{KEY}.1.jsonl", f"{KEY}.jsonl"])
        self.assertEqual(len(self.lines(f"{KEY}.1.jsonl")), 2)
        self.assertEqual(len(self.lines()), 1)

    def test_keeping_two_files_leaves_one_rotated_file(self):
        log = self.small_log(300, keep_files=2)
        for index in range(20):
            log.record(KEY, AuditEntry(event="tool", tool=f"t{index}"))
        self.assertEqual(self.names(), [f"{KEY}.1.jsonl", f"{KEY}.jsonl"])
        self.assertEqual(self.lines()[-1]["tool"], "t19")

    def test_a_stale_oldest_file_behind_a_gap_is_removed_on_rotation(self):
        self.directory.mkdir(parents=True)
        (self.directory / f"{KEY}.jsonl").write_text("x" * 400, encoding="utf-8")
        (self.directory / f"{KEY}.4.jsonl").write_text("stale\n", encoding="utf-8")
        self.small_log(300).record(KEY, AuditEntry(event="tool", tool="new"))
        self.assertEqual(self.names(), [f"{KEY}.1.jsonl", f"{KEY}.jsonl"])
        self.assertEqual(
            (self.directory / f"{KEY}.1.jsonl").read_text(encoding="utf-8"), "x" * 400
        )
        self.assertEqual(self.lines()[0]["tool"], "new")

    def test_rotation_leaves_files_beyond_a_reduced_keep_count_alone(self):
        self.directory.mkdir(parents=True)
        (self.directory / f"{KEY}.jsonl").write_text("x" * 400, encoding="utf-8")
        (self.directory / f"{KEY}.3.jsonl").write_text("three\n", encoding="utf-8")
        (self.directory / f"{KEY}.4.jsonl").write_text("four\n", encoding="utf-8")
        self.small_log(300, keep_files=3).record(KEY, AuditEntry(event="tool"))
        self.assertEqual(
            self.names(),
            [f"{KEY}.{n}.jsonl" for n in (1, 3, 4)] + [f"{KEY}.jsonl"],
        )
        self.assertEqual(
            (self.directory / f"{KEY}.3.jsonl").read_text(encoding="utf-8"), "three\n"
        )
        self.assertEqual(
            (self.directory / f"{KEY}.4.jsonl").read_text(encoding="utf-8"), "four\n"
        )

    def test_retention_boundary_is_exclusive_and_covers_the_first_rotated_file(self):
        for age, kept in ((86400.0, True), (86400.5, False), (86401.0, False)):
            with self.subTest(age=age):
                self.directory.mkdir(parents=True, exist_ok=True)
                rotated = self.directory / f"{KEY}.1.jsonl"
                rotated.write_text("{}\n", encoding="utf-8")
                os.utime(rotated, (1_700_000_000, 1_700_000_000))
                self.now = 1_700_000_000 + age
                self.small_log(10_000, retention_days=1).record(
                    KEY, AuditEntry(event="tool")
                )
                self.assertEqual(rotated.exists(), kept)
                self.assertTrue((self.directory / f"{KEY}.jsonl").exists())

    def test_rotated_files_older_than_the_retention_are_removed(self):
        self.directory.mkdir(parents=True)
        old = self.directory / f"{KEY}.3.jsonl"
        old.write_text("{}\n", encoding="utf-8")
        recent = self.directory / f"{KEY}.2.jsonl"
        recent.write_text("{}\n", encoding="utf-8")
        stale = self.now - 366 * 86400
        os.utime(old, (stale, stale))
        os.utime(recent, (self.now, self.now))
        self.log.record(KEY, AuditEntry(event="tool"))
        self.assertFalse(old.exists())
        self.assertTrue(recent.exists())


class AuditAclTests(unittest.TestCase):
    def test_the_directory_access_list_grants_only_the_current_user(self):
        import win32api
        import win32con
        import win32security

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "audit"
            path.mkdir()
            restrict_to_current_user(path)
            token = win32security.OpenProcessToken(
                win32api.GetCurrentProcess(), win32con.TOKEN_QUERY
            )
            user = win32security.GetTokenInformation(token, win32security.TokenUser)[0]
            descriptor = win32security.GetFileSecurity(
                str(path), win32security.DACL_SECURITY_INFORMATION
            )
            dacl = descriptor.GetSecurityDescriptorDacl()
            sids = {
                win32security.ConvertSidToStringSid(dacl.GetAce(index)[2])
                for index in range(dacl.GetAceCount())
            }
            self.assertEqual(sids, {win32security.ConvertSidToStringSid(user)})
            (path / "probe.jsonl").write_text("{}", encoding="utf-8")
            self.assertEqual((path / "probe.jsonl").read_text(encoding="utf-8"), "{}")
        self.assertIsInstance(time.time(), float)


if __name__ == "__main__":
    unittest.main()
