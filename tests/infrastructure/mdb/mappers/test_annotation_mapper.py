import unittest
from ost_visualizer.domain.entities.layer import Layer
from ost_visualizer.infrastructure.mdb.mappers.annotation_mapper import (
    MdbAnnotationLayerMapper,
)


class MdbAnnotationLayerMapperTests(unittest.TestCase):
    def test_missing_row_layer_uses_annotation_layer(self):
        mapper = MdbAnnotationLayerMapper(
            {
                "10": Layer(uid="10", name="Image", visible=True),
                "20": Layer(uid="20", name="Annotation", visible=False),
            }
        )
        self.assertEqual(mapper.resolve_layer(), ("20", False))

    def test_row_layer_uid_uses_row_layer_visibility(self):
        mapper = MdbAnnotationLayerMapper(
            {
                "20": Layer(uid="20", name="Annotation", visible=True),
                "30": Layer(uid="30", name="Custom", visible=False),
            }
        )
        self.assertEqual(mapper.resolve_layer(30), ("30", False))
        self.assertEqual(mapper.resolve_layer("30"), ("30", False))
        self.assertEqual(mapper.resolve_layer(20), ("20", True))

    def test_unknown_row_layer_uid_is_kept_and_visible(self):
        mapper = MdbAnnotationLayerMapper(
            {"20": Layer(uid="20", name="Annotation", visible=False)}
        )
        self.assertEqual(mapper.resolve_layer(99), ("99", True))

    def test_zero_and_blank_row_layer_uids_are_kept_not_replaced_by_the_default(self):
        mapper = MdbAnnotationLayerMapper(
            {
                "20": Layer(uid="20", name="Annotation", visible=False),
                "0": Layer(uid="0", name="Zero", visible=False),
            }
        )
        self.assertEqual(mapper.resolve_layer(0), ("0", False))
        self.assertEqual(mapper.resolve_layer(""), ("", True))
        self.assertEqual(mapper.resolve_layer(None), ("20", False))

    def test_missing_annotation_layer_matches_existing_reader_default(self):
        mapper = MdbAnnotationLayerMapper(
            {"30": Layer(uid="30", name="Custom", visible=False)}
        )
        self.assertEqual(mapper.resolve_layer(), (None, True))


if __name__ == "__main__":
    unittest.main()
