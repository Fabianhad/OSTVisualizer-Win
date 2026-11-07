import unittest
from ost_visualizer.domain.entities.layer import (
    BUILT_IN_DEFAULT_LAYER_UIDS,
    BidLayer,
    Layer,
    LayerSet,
    is_locked_built_in_default_layer,
    merge_layers_for_bid,
)


class LayerSetTests(unittest.TestCase):
    def test_uid_by_name_matches_case_insensitively(self):
        layers = LayerSet({"10": Layer(uid="10", name="Annotation", visible=True)})
        self.assertEqual(layers.uid_by_name("annotation"), "10")
        self.assertEqual(layers.uid_by_name(" ANNOTATION "), "10")
        self.assertIsNone(layers.uid_by_name("missing"))

    def test_unknown_layer_is_visible_by_default(self):
        layers = LayerSet({"10": Layer(uid="10", name="Annotation", visible=False)})
        self.assertTrue(layers.is_visible("99"))
        self.assertFalse(layers.is_visible("10"))

    def test_resolve_layer_or_default_uses_explicit_layer_identity(self):
        layers = LayerSet(
            {
                "10": Layer(uid="10", name="Annotation", visible=True),
                "20": Layer(uid="20", name="Custom", visible=False),
            }
        )
        self.assertEqual(
            layers.resolve_layer_or_default("20", "Annotation").as_tuple(),
            ("20", False),
        )

    def test_resolve_layer_or_default_uses_default_layer_when_missing(self):
        layers = LayerSet({"10": Layer(uid="10", name="Annotation", visible=False)})
        self.assertEqual(
            layers.resolve_layer_or_default(None, "Annotation").as_tuple(),
            ("10", False),
        )

    def test_annotation_layer_helpers_use_reserved_annotation_layer(self):
        layers = LayerSet({"10": Layer(uid="10", name="Annotation", visible=False)})
        self.assertEqual(layers.annotation_layer_uid(), "10")
        self.assertFalse(layers.annotation_layer_visible())

    def test_missing_default_does_not_hide_unassigned_entities(self):
        layers = LayerSet({})
        self.assertEqual(
            layers.resolve_layer_or_default(None, "Annotation").as_tuple(), (None, True)
        )
        self.assertEqual(
            layers.resolve_layer_or_default("deleted", "Annotation").as_tuple(),
            ("deleted", True),
        )


class MergeLayersForBidTests(unittest.TestCase):
    def test_bid_override_wins_over_template_and_retains_original_object(self):
        template = BidLayer("template", "0", "Annotation", True, 1, is_template=True)
        own = BidLayer("own", "bid", "annotation", False, 3)
        image = BidLayer("image", "0", "Image", True, 2, is_template=True)
        inputs = [own, template, image]
        merged = merge_layers_for_bid(inputs)
        self.assertEqual(merged, [image, own])
        self.assertIs(merged[1], own)
        self.assertEqual(inputs, [own, template, image])
        self.assertTrue(template.show)
        self.assertFalse(own.show)

    def test_empty_layers_produce_empty_result(self):
        self.assertEqual(merge_layers_for_bid([]), [])


class LayerNameHelpersTests(unittest.TestCase):
    def test_reserved_layer_names_are_the_stored_lowercase_values(self):
        from ost_visualizer.domain.entities import layer

        self.assertEqual(
            (
                layer.ANNOTATION_LAYER_NAME,
                layer.IMAGE_LAYER_NAME,
                layer.COMMENTS_LAYER_NAME,
            ),
            ("annotation", "image", "comments"),
        )

    def test_normalize_layer_name_trims_lowercases_and_tolerates_none(self):
        from ost_visualizer.domain.entities.layer import normalize_layer_name

        self.assertEqual(normalize_layer_name("  Mixed CASE "), "mixed case")
        self.assertEqual(normalize_layer_name(None), "")
        self.assertEqual(normalize_layer_name(""), "")
        self.assertEqual(normalize_layer_name(0), "")
        self.assertEqual(normalize_layer_name(12), "12")

    def test_comments_layer_detection_ignores_case_and_padding_only(self):
        from ost_visualizer.domain.entities.layer import is_comments_layer_name

        for name in ("comments", " Comments ", "COMMENTS"):
            with self.subTest(name=name):
                self.assertIs(is_comments_layer_name(name), True)
        for name in ("comment", "comments2", "my comments", "", None, "image"):
            with self.subTest(name=name):
                self.assertIs(is_comments_layer_name(name), False)


class LayerEntityContractTests(unittest.TestCase):
    def test_layer_defaults_to_visible_and_empty_name(self):
        layer = Layer(uid="1")
        self.assertEqual((layer.name, layer.visible), ("", True))

    def test_bid_layer_flags_default_to_a_plain_unlocked_bid_layer(self):
        layer = BidLayer("u", "b", "n", True, 4)
        self.assertEqual((layer.is_template, layer.is_locked), (False, False))
        self.assertEqual((layer.uid, layer.bid_uid, layer.sequence), ("u", "b", 4))

    def test_layer_visibility_is_a_frozen_value_pair(self):
        from dataclasses import FrozenInstanceError
        from ost_visualizer.domain.entities.layer import LayerVisibility

        visibility = LayerVisibility("7", False)
        self.assertEqual(visibility.as_tuple(), ("7", False))
        with self.assertRaises(FrozenInstanceError):
            visibility.visible = True
        self.assertEqual(LayerVisibility("7", False), LayerVisibility("7", False))

    def test_resolve_layer_without_uid_is_unassigned_and_visible_but_known_uid_is_exact(
        self,
    ):
        layers = LayerSet({"5": Layer(uid="5", name="Custom", visible=False)})
        unassigned = layers.resolve_layer(None)
        self.assertEqual(unassigned.as_tuple(), (None, True))
        self.assertEqual(layers.resolve_layer("5").as_tuple(), ("5", False))
        self.assertEqual(layers.resolve_layer(5).as_tuple(), ("5", False))
        self.assertEqual(layers.resolve_layer("6").as_tuple(), ("6", True))

    def test_annotation_layer_visibility_is_visible_when_the_layer_is_absent(self):
        self.assertIs(LayerSet({}).annotation_layer_visible(), True)
        self.assertIs(
            LayerSet({"1": Layer("1", "annotation", True)}).annotation_layer_visible(),
            True,
        )

    def test_is_layer_visible_treats_blank_uid_as_visible_even_if_a_layer_is_keyed_that_way(
        self,
    ):
        from ost_visualizer.domain.entities.layer import is_layer_visible

        layers = {"": Layer("", "x", False), "0": Layer("0", "y", False)}
        self.assertIs(is_layer_visible(layers, None), True)
        self.assertIs(is_layer_visible(layers, ""), True)
        # A uid of 0 is a real key: it is only a blank/None uid that bypasses lookup.
        self.assertIs(is_layer_visible(layers, "0"), False)

    def test_get_layer_uid_by_name_returns_the_first_matching_layer_in_mapping_order(
        self,
    ):
        from ost_visualizer.domain.entities.layer import get_layer_uid_by_name

        layers = {
            "2": Layer("2", "Dup", True),
            "1": Layer("1", " dup ", False),
        }
        self.assertEqual(get_layer_uid_by_name(layers, "DUP"), "2")
        self.assertIsNone(get_layer_uid_by_name(layers, ""))
        self.assertEqual(get_layer_uid_by_name({"3": Layer("3", "", True)}, ""), "3")

    def test_merge_prefers_the_later_sequence_for_equal_non_template_names(self):
        first = BidLayer("a", "bid", "Same", True, 1)
        second = BidLayer("b", "bid", "same", False, 2)
        template = BidLayer("t", "0", "SAME", True, 0, is_template=True)
        merged = merge_layers_for_bid([second, template, first])
        self.assertEqual([layer.uid for layer in merged], ["b"])
        sorted_output = merge_layers_for_bid(
            [
                BidLayer("x", "bid", "X", True, 9),
                BidLayer("y", "bid", "Y", True, 3),
                BidLayer("z", "0", "Z", True, 5, is_template=True),
            ]
        )
        self.assertEqual([layer.uid for layer in sorted_output], ["y", "z", "x"])


class LockedBuiltInDefaultLayerTests(unittest.TestCase):
    @staticmethod
    def _layer(uid, *, template=True, locked=True):
        return BidLayer(uid, "", "L", True, 1, is_template=template, is_locked=locked)

    def test_built_in_uids_are_the_four_template_layers_of_a_new_database(self):
        self.assertEqual(BUILT_IN_DEFAULT_LAYER_UIDS, frozenset({"1", "2", "3", "4"}))

    def test_only_a_locked_template_with_a_built_in_uid_is_a_locked_built_in(self):
        cases = (
            (self._layer("1"), True),
            (self._layer("4"), True),
            (self._layer(2), True),
            (self._layer("0"), False),
            (self._layer("5"), False),
            (self._layer("d-1"), False),
            (self._layer(""), False),
            (self._layer("1", locked=False), False),
            (self._layer("1", template=False), False),
            (self._layer("1", template=False, locked=False), False),
        )
        for layer, expected in cases:
            with self.subTest(
                uid=layer.uid, template=layer.is_template, locked=layer.is_locked
            ):
                self.assertIs(is_locked_built_in_default_layer(layer), expected)


if __name__ == "__main__":
    unittest.main()
