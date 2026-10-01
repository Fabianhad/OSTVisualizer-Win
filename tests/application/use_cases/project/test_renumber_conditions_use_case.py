import logging
import unittest
from unittest.mock import Mock
from ost_visualizer.application.interfaces.i_mdb_writer import IMdbWriter
from ost_visualizer.application.use_cases.project.renumber_conditions_use_case import (
    RenumberConditionsUseCase,
)


class RenumberConditionsUseCaseExecuteTests(unittest.TestCase):
    def test_empty_sequence_is_a_successful_no_op(self):
        writer = Mock(spec=IMdbWriter)
        self.assertTrue(RenumberConditionsUseCase(writer).execute("db", "bid", []))
        writer.renumber_conditions.assert_not_called()

    def test_duplicate_ids_are_rejected_before_any_write(self):
        writer = Mock(spec=IMdbWriter)
        logger = logging.getLogger("test.renumber_conditions")
        logger.addHandler(logging.NullHandler())
        logger.propagate = False
        use_case = RenumberConditionsUseCase(writer, logger)
        with self.assertLogs(logger, level="WARNING") as logs:
            self.assertFalse(use_case.execute("db", "bid", ["1", "2", "1"]))
        self.assertEqual(
            logs.output,
            [
                "WARNING:test.renumber_conditions:"
                "Duplicate condition IDs passed to renumber"
            ],
        )
        writer.renumber_conditions.assert_not_called()

    def test_captured_order_bid_and_failure_are_preserved(self):
        writer = Mock(spec=IMdbWriter)
        writer.renumber_conditions.return_value = False
        self.assertFalse(
            RenumberConditionsUseCase(writer).execute("db", "bid", ["3", "1", "2"])
        )
        writer.renumber_conditions.assert_called_once_with("db", "bid", ["3", "1", "2"])

    def test_successful_writer_result_is_returned(self):
        writer = Mock(spec=IMdbWriter)
        writer.renumber_conditions.return_value = True
        self.assertTrue(
            RenumberConditionsUseCase(writer).execute("db", "bid", ["2", "1"])
        )
        writer.renumber_conditions.assert_called_once_with("db", "bid", ["2", "1"])
