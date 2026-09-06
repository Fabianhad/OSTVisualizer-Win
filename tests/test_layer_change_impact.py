import unittest
from dataclasses import replace
from ost_visualizer.application.layer_change_impact import (
    layer_rename_preserves_rendering,
)
from ost_visualizer.domain.entities.layer import BidLayer, merge_layers_for_bid


class LayerChangeImpactTests(unittest.TestCase):
    def test_only_ordinary_names_preserve_rendering(self):
        old = BidLayer("1", "8", "Walls", True, 1)
        for changes, expected in (
            ({"name": "Partitions"}, True),
            ({"name": "Image"}, False),
            ({"name": " ANNOTATION "}, False),
            ({"name": "comments"}, False),
            ({"name": "Partitions", "show": False}, False),
            ({"name": "Partitions", "sequence": 2}, False),
            ({"name": "Partitions", "is_locked": True}, False),
            ({"name": "Partitions", "is_template": True}, False),
            ({"name": "Partitions", "uid": "2"}, False),
        ):
            with self.subTest(changes=changes):
                new = replace(old, **changes)
                self.assertEqual(
                    layer_rename_preserves_rendering([old], [new]), expected
                )
                self.assertEqual(
                    layer_rename_preserves_rendering([new], [old]), expected
                )
        self.assertFalse(layer_rename_preserves_rendering([], [old]))
        self.assertFalse(layer_rename_preserves_rendering([old], []))

    def test_rename_collision_changing_effective_membership_is_conservative(self):
        old = BidLayer("1", "8", "Walls", True, 1)
        sibling = BidLayer("2", "8", "Floors", False, 2)
        before = merge_layers_for_bid([old, sibling])
        after = merge_layers_for_bid([replace(old, name="Floors"), sibling])
        self.assertFalse(layer_rename_preserves_rendering(before, after))
