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


class AnnotationCreationFactoryEmptyDefaultTests(unittest.TestCase):
    def test_without_an_annotation_layer_the_spec_layer_stays_unset(self):
        for factory_layer in (None, ""):
            spec = _spec()
            spec.layer_uid = None
            AnnotationCreationFactory(factory_layer).assign_default_layer(spec)
            self.assertIsNone(spec.layer_uid)
        spec = _spec()
        AnnotationCreationFactory(None).assign_default_layer(spec)
        self.assertEqual(spec.layer_uid, "")

    def test_a_numeric_layer_uid_is_stored_as_text(self):
        spec = _spec()
        AnnotationCreationFactory(12).assign_default_layer(spec)
        self.assertEqual(spec.layer_uid, "12")


class AnnotationCreationFactoryContractTests(unittest.TestCase):
    def test_bulk_assignment_updates_in_place_and_returns_nothing(self):
        factory = AnnotationCreationFactory("annotation-layer")
        specs = [_spec(), _spec("custom")]
        self.assertIsNone(factory.assign_default_layer_to_specs(specs))
        self.assertEqual(
            [spec.layer_uid for spec in specs], ["annotation-layer", "custom"]
        )
        empty = []
        self.assertIsNone(factory.assign_default_layer_to_specs(empty))
        self.assertEqual(empty, [])

    def test_insert_annotation_spec_defaults_and_required_fields(self):
        from dataclasses import fields

        spec = InsertAnnotationSpec("p", "rect", [1.0], "#000", 1.5)
        self.assertEqual(spec.properties, {})
        self.assertIs(type(spec.properties), dict)
        self.assertIsNot(
            spec.properties,
            InsertAnnotationSpec("p", "rect", [1.0], "#000", 1.5).properties,
        )
        self.assertEqual(spec.layer_uid, "")
        self.assertEqual(
            (
                spec.page_uid,
                spec.annotation_type,
                spec.position,
                spec.color,
                spec.width,
            ),
            ("p", "rect", [1.0], "#000", 1.5),
        )
        self.assertEqual(
            [field.name for field in fields(InsertAnnotationSpec)],
            [
                "page_uid",
                "annotation_type",
                "position",
                "color",
                "width",
                "properties",
                "layer_uid",
            ],
        )
        with self.assertRaises(TypeError):
            InsertAnnotationSpec("p", "rect", [1.0], "#000")


if __name__ == "__main__":
    unittest.main()
