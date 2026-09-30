import logging
import unittest
from types import SimpleNamespace
from ost_visualizer.application.services.active_bid_write_guard import (
    ActiveBidWriteGuard,
)
from ost_visualizer.domain.entities.hierarchy_data import (
    HierarchyBidInfo,
    HierarchyData,
    HierarchyFileEntry,
    HierarchyProjectInfo,
)
from ost_visualizer.domain.entities.identity_refs import BidRef
from tests.application.services.write_permission_support import (
    _ProjectData as _permissions__ProjectData,
    _hierarchy_with_bids as _permissions__hierarchy_with_bids,
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
