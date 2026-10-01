import unittest
from ost_visualizer.application.dtos.annotation_creation_factory import (
    AnnotationCreationFactory,
)
from ost_visualizer.application.dtos.insert_annotation_spec_dto import (
    InsertAnnotationSpec,
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
        result = AnnotationCreationFactory("annotation-layer").assign_default_layer(
            spec
        )
        self.assertIs(result, spec)
        self.assertEqual(spec, _spec("annotation-layer"))

    def test_assign_default_layer_preserves_existing_layer_uid(self):
        spec = _spec("custom-layer")
        result = AnnotationCreationFactory("annotation-layer").assign_default_layer(
            spec
        )
        self.assertIs(result, spec)
        self.assertEqual(spec, _spec("custom-layer"))

    def test_assign_default_layer_without_annotation_layer_is_noop(self):
        spec = _spec()
        result = AnnotationCreationFactory(None).assign_default_layer(spec)
        self.assertIs(result, spec)
        self.assertEqual(spec, _spec())

    def test_assign_default_layer_to_specs_updates_each_missing_layer(self):
        first = _spec()
        second = _spec("custom-layer")
        third = _spec()
        factory = AnnotationCreationFactory("annotation-layer")
        for _ in range(2):
            factory.assign_default_layer_to_specs(iter([first, second, third]))
            self.assertEqual(first, _spec("annotation-layer"))
            self.assertEqual(second, _spec("custom-layer"))
            self.assertEqual(third, _spec("annotation-layer"))


if __name__ == "__main__":
    unittest.main()
