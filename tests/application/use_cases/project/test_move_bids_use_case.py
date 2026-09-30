import unittest
from unittest.mock import Mock
from ost_visualizer.application.use_cases.project.move_bids_use_case import (
    MoveBidsUseCase,
)


class MoveBidsUseCaseExecuteTests(unittest.TestCase):
    def test_no_target_orphans_only_the_requested_bids(self):
        writer = Mock()
        writer.orphan_bids.return_value = False
        self.assertFalse(MoveBidsUseCase(writer).execute("db", ["1", "2"], None))
        writer.orphan_bids.assert_called_once_with("db", ["1", "2"])
        writer.move_bids_to_project.assert_not_called()

    def test_target_move_retains_original_project_validation(self):
        writer = Mock()
        writer.move_bids_to_project.return_value = True
        self.assertTrue(
            MoveBidsUseCase(writer).execute("db", ["1"], "target", "source")
        )
        writer.move_bids_to_project.assert_called_once_with(
            "db", ["1"], "target", "source"
        )
        writer.orphan_bids.assert_not_called()
