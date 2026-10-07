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
        self.assertNotIn("secret", first)

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
