import logging
import unittest
from ost_visualizer.application.services.active_bid_write_guard import (
    ActiveBidWriteGuard,
)
from tests.application.services.write_permission_support import (
    _ProjectData as _permissions__ProjectData,
)


class BidLockPermissionTests(unittest.TestCase):
    def test_locked_bid_expected_block_does_not_warn(self):
        project_data = _permissions__ProjectData()
        project_data.locked = True
        logger = logging.getLogger("tests.locked_bid_expected_block")
        guard = ActiveBidWriteGuard(project_data, logger)
        with self.assertNoLogs(logger, level="WARNING"):
            self.assertTrue(
                guard.blocks_active_locked_bid_write(
                    project_data.bid_ref.file_path,
                )
            )
            project_data.locked = False
            self.assertFalse(
                guard.blocks_active_locked_bid_write(project_data.bid_ref.file_path)
            )

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
