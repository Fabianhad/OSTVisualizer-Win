import unittest
from ost_visualizer.domain.entities.layer import (
    BidLayer,
    Layer,
    LayerSet,
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


if __name__ == "__main__":
    unittest.main()
