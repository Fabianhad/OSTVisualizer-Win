import logging
import unittest
from ost_visualizer.application.services.active_bid_write_guard import (
    ActiveBidWriteGuard,
)
from ost_visualizer.domain.entities.identity_refs import BidRef
from tests.application.services.write_permission_support import (
    _ProjectData as _permissions__ProjectData,
)


class BidLockPermissionTests(unittest.TestCase):
    def test_unlocking_the_active_bid_lifts_the_write_block(self):
        project_data = _permissions__ProjectData()
        project_data.locked = True
        guard = ActiveBidWriteGuard(project_data)
        self.assertIs(
            guard.blocks_active_locked_bid_write(project_data.bid_ref.file_path), True
        )
        project_data.locked = False
        self.assertIs(
            guard.blocks_active_locked_bid_write(project_data.bid_ref.file_path), False
        )

    def test_guard_takes_only_the_project_data_service(self):
        # Decision D8: the guard's former logger was dead (it never logged, so a
        # no-logs assertion on it could not fail) and was removed with its parameter.
        project_data = _permissions__ProjectData()
        guard = ActiveBidWriteGuard(project_data)
        self.assertFalse(hasattr(guard, "logger"))
        with self.assertRaises(TypeError):
            ActiveBidWriteGuard(project_data, logging.getLogger("unused"))

    def test_active_lock_is_scoped_to_canonical_database_and_requested_bid(self):
        data = _permissions__ProjectData()
        data.locked = True
        guard = ActiveBidWriteGuard(data)
        self.assertIs(
            guard.active_locked_bid_ref_for(r"c:\JOBS\test.mdb"), data.bid_ref
        )
        for path, bid, expected in (
            ("C:/jobs/test.mdb", None, True),
            ("C:/jobs/test.mdb", "7", True),
            ("C:/jobs/test.mdb", 7, True),
            ("C:/jobs/test.mdb", "8", False),
            ("C:/other/test.mdb", "7", False),
        ):
            with self.subTest(path=path, bid=bid):
                self.assertEqual(
                    guard.is_active_locked_bid_write_blocked(path, bid), expected
                )
                self.assertEqual(
                    guard.blocks_active_locked_bid_write(path, bid), expected
                )
        data.bid_ref = None
        self.assertIsNone(guard.active_locked_bid_ref_for("C:/jobs/test.mdb"))
        self.assertFalse(guard.blocks_active_locked_bid_write("C:/jobs/test.mdb"))

    def test_project_delete_blocks_only_the_active_locked_bids_parent(self):
        data = _permissions__ProjectData()
        data.locked = True
        guard = ActiveBidWriteGuard(data)
        path = data.bid_ref.file_path
        self.assertTrue(
            guard.blocks_active_locked_bid_project_delete(
                path, (uid for uid in ("other", "project-1"))
            )
        )
        self.assertFalse(guard.blocks_active_locked_bid_project_delete(path, []))
        self.assertFalse(guard.blocks_active_locked_bid_project_delete(path, ["other"]))
        self.assertFalse(
            guard.blocks_active_locked_bid_project_delete("other.mdb", ["project-1"])
        )
        data.project_uid = None
        self.assertFalse(
            guard.blocks_active_locked_bid_project_delete(path, ["project-1"])
        )
        data.project_uid = "project-1"
        data.locked = False
        self.assertFalse(
            guard.blocks_active_locked_bid_project_delete(path, ["project-1"])
        )


class _RecordingProjectData(_permissions__ProjectData):
    def __init__(self):
        super().__init__()
        self.hierarchy_lookups = []

    def find_project_uid_for_bid(self, bid_ref):
        self.hierarchy_lookups.append(bid_ref)
        return super().find_project_uid_for_bid(bid_ref)


class ActiveBidWriteGuardDecisionTests(unittest.TestCase):
    def test_every_decision_is_a_strict_boolean(self):
        data = _RecordingProjectData()
        guard = ActiveBidWriteGuard(data)
        path = data.bid_ref.file_path
        for locked in (False, True):
            data.locked = locked
            for answer in (
                guard.is_active_locked_bid_write_blocked(path),
                guard.blocks_active_locked_bid_write(path),
                guard.blocks_active_locked_bid_project_delete(path, ["project-1"]),
                guard.blocks_active_locked_bid_write("other.mdb"),
                guard.blocks_active_locked_bid_project_delete(
                    "other.mdb", ["project-1"]
                ),
                guard.is_active_locked_bid_write_blocked(path, "8"),
                guard.blocks_active_locked_bid_project_delete(path, ["other"]),
            ):
                self.assertIsInstance(answer, bool)
        data.locked = True
        self.assertIs(guard.is_active_locked_bid_write_blocked(path), True)
        self.assertIs(guard.blocks_active_locked_bid_write(path), True)
        self.assertIs(
            guard.blocks_active_locked_bid_project_delete(path, ["project-1"]), True
        )

    def test_hierarchy_is_only_consulted_for_the_locked_bid_of_the_same_file(self):
        data = _RecordingProjectData()
        guard = ActiveBidWriteGuard(data)
        path = data.bid_ref.file_path
        self.assertFalse(
            guard.blocks_active_locked_bid_project_delete(path, ["project-1"])
        )
        data.locked = True
        self.assertFalse(
            guard.blocks_active_locked_bid_project_delete("other.mdb", ["project-1"])
        )
        data.bid_ref = None
        self.assertFalse(
            guard.blocks_active_locked_bid_project_delete(path, ["project-1"])
        )
        self.assertEqual(data.hierarchy_lookups, [])
        data.bid_ref = BidRef(file_path=path, bid_uid="7")
        self.assertTrue(
            guard.blocks_active_locked_bid_project_delete(path, ["project-1"])
        )
        self.assertEqual(data.hierarchy_lookups, [data.bid_ref])

    def test_unknown_parent_project_never_matches_a_literal_none_or_empty_uid(self):
        data = _RecordingProjectData()
        data.locked = True
        guard = ActiveBidWriteGuard(data)
        path = data.bid_ref.file_path
        for missing in (None, ""):
            data.project_uid = missing
            with self.subTest(project_uid=missing):
                self.assertIs(
                    guard.blocks_active_locked_bid_project_delete(
                        path, ["None", "", "0"]
                    ),
                    False,
                )
        data.project_uid = 5
        self.assertIs(guard.blocks_active_locked_bid_project_delete(path, ["5"]), True)
        self.assertIs(guard.blocks_active_locked_bid_project_delete(path, [5]), True)
