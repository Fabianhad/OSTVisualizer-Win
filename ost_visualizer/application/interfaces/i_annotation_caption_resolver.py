from typing import List, Protocol
from ...domain.entities.condition import Condition
from ...domain.entities.takeoff import Takeoff
from ..dtos.annotation_caption_dto import (
    AnnotationCaptionSettingsDto,
    ResolvedAnnotationCaptionDto,
)


class IAnnotationCaptionResolver(Protocol):
    def resolve(
        self,
        condition: Condition,
        takeoff: Takeoff,
        hole_positions: List[List[float]],
        settings: AnnotationCaptionSettingsDto,
        label: str,
    ) -> ResolvedAnnotationCaptionDto: ...
