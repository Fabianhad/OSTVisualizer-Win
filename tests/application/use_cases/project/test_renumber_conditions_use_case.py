import unittest
from unittest.mock import Mock
from ost_visualizer.application.use_cases.project.renumber_conditions_use_case import (
    RenumberConditionsUseCase,
)


class RenumberConditionsUseCaseExecuteTests(unittest.TestCase):
    def test_empty_sequence_is_a_successful_no_op(self):
        writer = Mock()
        self.assertTrue(RenumberConditionsUseCase(writer).execute("db", "bid", []))
        writer.renumber_conditions.assert_not_called()

    def test_duplicate_ids_are_rejected_before_any_write(self):
        writer = Mock()
        self.assertFalse(
            RenumberConditionsUseCase(writer, Mock()).execute("db", "bid", ["1", "1"])
        )
        writer.renumber_conditions.assert_not_called()

    def test_captured_order_bid_and_failure_are_preserved(self):
        writer = Mock()
        writer.renumber_conditions.return_value = False
        self.assertFalse(
            RenumberConditionsUseCase(writer).execute("db", "bid", ["3", "1", "2"])
        )
        writer.renumber_conditions.assert_called_once_with("db", "bid", ["3", "1", "2"])
