import unittest
from unittest.mock import Mock
from ost_visualizer.application.interfaces.i_mdb_writer import IMdbWriter
from ost_visualizer.application.use_cases.project.move_bids_use_case import (
    MoveBidsUseCase,
)


class MoveBidsUseCaseExecuteTests(unittest.TestCase):
    def test_no_target_orphans_only_the_requested_bids(self):
        for writer_result in (False, True):
            with self.subTest(writer_result=writer_result):
                writer = Mock(spec=IMdbWriter)
                writer.orphan_bids.return_value = writer_result
                self.assertIs(
                    MoveBidsUseCase(writer).execute("db", ["1", "2"], None),
                    writer_result,
                )
                writer.orphan_bids.assert_called_once_with("db", ["1", "2"])
                writer.move_bids_to_project.assert_not_called()

    def test_no_target_ignores_original_project_when_orphaning(self):
        writer = Mock(spec=IMdbWriter)
        writer.orphan_bids.return_value = True
        self.assertTrue(MoveBidsUseCase(writer).execute("db", ["1"], None, "source"))
        writer.orphan_bids.assert_called_once_with("db", ["1"])
        writer.move_bids_to_project.assert_not_called()

    def test_target_move_retains_original_project_validation(self):
        writer = Mock(spec=IMdbWriter)
        writer.move_bids_to_project.return_value = True
        self.assertTrue(
            MoveBidsUseCase(writer).execute("db", ["1"], "target", "source")
        )
        writer.move_bids_to_project.assert_called_once_with(
            "db", ["1"], "target", "source"
        )
        writer.orphan_bids.assert_not_called()

    def test_target_move_without_original_project_and_writer_failure(self):
        writer = Mock(spec=IMdbWriter)
        writer.move_bids_to_project.return_value = False
        self.assertIs(
            MoveBidsUseCase(writer).execute("db", ["1", "2"], "target"), False
        )
        writer.move_bids_to_project.assert_called_once_with(
            "db", ["1", "2"], "target", None
        )
        writer.orphan_bids.assert_not_called()
