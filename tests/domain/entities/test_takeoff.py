import unittest
from ost_visualizer.domain.entities.takeoff import Takeoff
from ost_visualizer.domain.entities.takeoff import (
    Takeoff,
    find_takeoff_parent_cycle_uids,
)


class TakeoffParentTests(unittest.TestCase):
    def test_takeoff_root_parent_sentinels_are_canonical(self):
        self.assertFalse(Takeoff(uid="1", condition_uid="c1", parent_uid="0").is_hole)
        self.assertFalse(Takeoff(uid="1", condition_uid="c1", parent_uid="").is_hole)
        self.assertTrue(Takeoff(uid="1", condition_uid="c1", parent_uid="None").is_hole)
        self.assertTrue(Takeoff(uid="2", condition_uid="c1", parent_uid="1").is_hole)


class TakeoffHydrationContractTests(unittest.TestCase):
    def test_takeoff_contract_rejects_missing_declared_field(self):
        takeoff = Takeoff(uid="4485", condition_uid="10", page_uid="20")
        del takeoff.uid
        self.assertFalse(takeoff.has_valid_contract())

    def test_takeoff_contract_rejects_bool_as_numeric_storage(self):
        takeoff = Takeoff(
            uid="4485",
            condition_uid="10",
            page_uid="20",
            rotation=True,
        )
        self.assertFalse(takeoff.has_valid_contract())

    def test_takeoff_contract_rejects_non_finite_numeric_storage(self):
        for field_name, value in (
            ("position", [1.0, float("nan"), 3.0, 4.0]),
            ("position", [1.0, float("inf"), 3.0, 4.0]),
            ("rotation", float("-inf")),
            ("rotation", 10**1000),
        ):
            with self.subTest(field_name=field_name, value=value):
                takeoff = Takeoff(
                    uid="4485",
                    condition_uid="10",
                    page_uid="20",
                )
                setattr(takeoff, field_name, value)
                self.assertFalse(takeoff.has_valid_contract())

    def test_takeoff_parent_cycle_detection_is_order_independent(self):
        self.assertEqual(
            find_takeoff_parent_cycle_uids(
                {"32": "31", "30": "0", "31": "32", "33": "32"}
            ),
            {"31", "32"},
        )
