from typing import Iterable, Optional
from .insert_annotation_spec_dto import InsertAnnotationSpec


class AnnotationCreationFactory:
    def __init__(self, annotation_layer_uid: Optional[str]) -> None:
        self._annotation_layer_uid = str(annotation_layer_uid or "")

    def assign_default_layer(self, spec: InsertAnnotationSpec) -> InsertAnnotationSpec:
        if not spec.layer_uid and self._annotation_layer_uid:
            spec.layer_uid = self._annotation_layer_uid
        return spec

    def assign_default_layer_to_specs(
        self, specs: Iterable[InsertAnnotationSpec]
    ) -> None:
        for spec in specs:
            self.assign_default_layer(spec)
