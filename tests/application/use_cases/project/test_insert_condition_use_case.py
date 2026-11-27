import math
import unittest
from ost_visualizer.application.dtos.create_condition_spec_dto import (
    CreateConditionSpec,
    InvalidConditionSpecError,
)
from ost_visualizer.application.use_cases.project.insert_condition_use_case import (
    InsertConditionUseCase,
)
from ost_visualizer.shared.texts import (
    CREATE_CONDITION_SPEC_DTO_MESSAGE_CONDITION_NAME_CANNOT_BE_EMPTY,
    CREATE_CONDITION_SPEC_DTO_MESSAGE_THE_CONDITION_WAS_NOT_CREATED_BECAUSE,
)


class _Writer:
    def __init__(self):
        self.calls = []

    def insert_condition(self, db_path, bid_uid, spec):
        self.calls.append((db_path, bid_uid, spec))
        return "99"


class InsertConditionUseCaseTests(unittest.TestCase):
    def test_a_valid_spec_reaches_the_writer(self):
        writer = _Writer()
        spec = CreateConditionSpec(name="Wall", thickness=4.0)
        self.assertEqual(InsertConditionUseCase(writer).execute("db", "7", spec), "99")
        self.assertEqual(writer.calls, [("db", "7", spec)])

    def test_an_empty_or_blank_name_is_refused_before_the_writer(self):
        for name in ("", "   ", "\t\n"):
            with self.subTest(name=name):
                writer = _Writer()
                with self.assertRaises(InvalidConditionSpecError) as refused:
                    InsertConditionUseCase(writer).execute(
                        "db", "7", CreateConditionSpec(name=name)
                    )
                self.assertEqual(
                    str(refused.exception),
                    CREATE_CONDITION_SPEC_DTO_MESSAGE_CONDITION_NAME_CANNOT_BE_EMPTY,
                )
                self.assertEqual(writer.calls, [])

    def test_a_number_that_is_not_finite_is_refused_before_the_writer(self):
        for field_name in ("thickness", "spacing", "width", "rise", "gap"):
            for value in (math.nan, math.inf, -math.inf):
                with self.subTest(field=field_name, value=value):
                    writer = _Writer()
                    spec = CreateConditionSpec(name="Wall", **{field_name: value})
                    with self.assertRaises(InvalidConditionSpecError) as refused:
                        InsertConditionUseCase(writer).execute("db", "7", spec)
                    self.assertEqual(
                        str(refused.exception),
                        CREATE_CONDITION_SPEC_DTO_MESSAGE_THE_CONDITION_WAS_NOT_CREATED_BECAUSE,
                    )
                    self.assertEqual(writer.calls, [])

    def test_the_refusal_is_a_value_error(self):
        self.assertTrue(issubclass(InvalidConditionSpecError, ValueError))


if __name__ == "__main__":
    unittest.main()
