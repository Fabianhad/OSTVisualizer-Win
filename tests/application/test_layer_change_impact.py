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
            ({"name": "Partitions", "bid_uid": "other-bid"}, False),
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

    def test_no_rename_empty_or_duplicate_identity_cannot_claim_narrow_impact(self):
        old = BidLayer("1", "8", "Walls", True, 1)
        renamed = replace(old, name="Partitions")
        for before, after in (
            ([], []),
            ([old], [replace(old)]),
            ([old, old], [renamed]),
            ([old], [renamed, renamed]),
        ):
            with self.subTest(before=before, after=after):
                self.assertFalse(layer_rename_preserves_rendering(before, after))
        self.assertTrue(layer_rename_preserves_rendering([old], [renamed]))

    def test_rename_collision_changing_effective_membership_is_conservative(self):
        old = BidLayer("1", "8", "Walls", True, 1)
        sibling = BidLayer("2", "8", "Floors", False, 2)
        before = merge_layers_for_bid([old, sibling])
        after = merge_layers_for_bid([replace(old, name="Floors"), sibling])
        self.assertFalse(layer_rename_preserves_rendering(before, after))

    def test_every_retained_layer_must_preserve_non_name_state(self):
        first = BidLayer("1", "8", "Walls", True, 1)
        second = BidLayer("2", "8", "Floors", False, 2)
        renamed = replace(first, name="Partitions")
        for before in ([first, second], [second, first]):
            with self.subTest(before=before):
                self.assertTrue(
                    layer_rename_preserves_rendering(before, [second, renamed])
                )
                self.assertFalse(
                    layer_rename_preserves_rendering(
                        before, [renamed, replace(second, show=True)]
                    )
                )
                self.assertFalse(
                    layer_rename_preserves_rendering(
                        before, [renamed, replace(second, name="Image")]
                    )
                )
