import unittest
from ost_visualizer.application.dtos.insert_annotation_spec_dto import (
    InsertAnnotationSpec,
)
from ost_visualizer.application.dtos.annotation_creation_factory import (
    AnnotationCreationFactory,
)


def _spec(layer_uid: str = "") -> InsertAnnotationSpec:
    return InsertAnnotationSpec(
        page_uid="page-1",
        annotation_type="rect",
        position=[1.0, 2.0, 3.0, 4.0],
        color="#ff0000",
        width=2.0,
        layer_uid=layer_uid,
    )


class AnnotationCreationFactoryTests(unittest.TestCase):
    def test_assign_default_layer_adds_annotation_layer_uid(self):
        spec = _spec()
        AnnotationCreationFactory("annotation-layer").assign_default_layer(spec)
        self.assertEqual(spec.layer_uid, "annotation-layer")

    def test_assign_default_layer_preserves_existing_layer_uid(self):
        spec = _spec("custom-layer")
        AnnotationCreationFactory("annotation-layer").assign_default_layer(spec)
        self.assertEqual(spec.layer_uid, "custom-layer")

    def test_assign_default_layer_without_annotation_layer_is_noop(self):
        spec = _spec()
        AnnotationCreationFactory(None).assign_default_layer(spec)
        self.assertEqual(spec.layer_uid, "")

    def test_assign_default_layer_to_specs_updates_each_missing_layer(self):
        first = _spec()
        second = _spec("custom-layer")
        AnnotationCreationFactory("annotation-layer").assign_default_layer_to_specs(
            [first, second]
        )
        self.assertEqual(first.layer_uid, "annotation-layer")
        self.assertEqual(second.layer_uid, "custom-layer")


if __name__ == "__main__":
    unittest.main()
