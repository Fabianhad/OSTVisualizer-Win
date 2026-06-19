import unittest

from ost_visualizer.domain.entities.layer import Layer, LayerSet


class LayerSetTests(unittest.TestCase):
    def test_uid_by_name_matches_case_insensitively(self):
        layers = LayerSet({"10": Layer(uid="10", name="Annotation", visible=True)})

        self.assertEqual(layers.uid_by_name("annotation"), "10")

    def test_unknown_layer_is_visible_by_default(self):
        layers = LayerSet({"10": Layer(uid="10", name="Annotation", visible=False)})

        self.assertTrue(layers.is_visible("99"))

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


if __name__ == "__main__":
    unittest.main()
