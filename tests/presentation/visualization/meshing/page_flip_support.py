import unittest
from ost_visualizer.domain.entities import shape as shapes
from ost_visualizer.domain.entities.condition import Condition
from ost_visualizer.domain.entities.takeoff import Takeoff
from ost_visualizer.domain.services.coordinate_transformation_service import (
    OSTCoordinateSystem,
)
from ost_visualizer.domain.services.uom_service import calculate_polygon_area
from ost_visualizer.infrastructure.visualization_provider import _MeshGeneratorAdapter
from ost_visualizer.presentation.visualization.factories.coordinate_transformer_factory import (
    CoordinateTransformerFactory,
)
from ost_visualizer.presentation.visualization.meshing.mesh_factory import MeshFactory

PAGE_WIDTH_POINTS = 720.0
PAGE_HEIGHT_POINTS = 360.0


def _page_info(*, flip_x: bool = False, flip_y: bool = False) -> dict:
    return {
        "scale_factor1": 1.0,
        "scale_factor2": 1.0,
        "rotation": 0,
        "flip_x": flip_x,
        "flip_y": flip_y,
        "width": PAGE_WIDTH_POINTS,
        "height": PAGE_HEIGHT_POINTS,
        "view_scale": 1.0,
    }


def _area_mesh(*, flip_x: bool = False, flip_y: bool = False):
    condition = Condition(
        uid="area-condition",
        condition_type=Condition.TYPE_AREA,
        thickness=1.0,
    )
    takeoff = Takeoff(
        uid="asymmetric-area",
        condition_uid=condition.uid,
        page_uid="page-1",
        position=[1.0, 1.0, 2.5, 1.0, 2.0, 2.0, 1.0, 2.0],
    )
    original_position = list(takeoff.position)
    mesh = MeshFactory(
        OSTCoordinateSystem(_page_info(flip_x=flip_x, flip_y=flip_y))
    ).create_mesh_for_takeoff(takeoff, condition)
    return takeoff, original_position, mesh


def _xy_bounds(mesh) -> tuple[float, float, float, float]:
    xs = [float(vertex[0]) for vertex in mesh.vertices]
    ys = [float(vertex[1]) for vertex in mesh.vertices]
    return min(xs), max(xs), min(ys), max(ys)


class _ColorService:
    @staticmethod
    def get_color_mapping(_conditions, _takeoffs, _display_mode, _grayscale):
        return {}, {}

    @staticmethod
    def get_color_for_takeoff(*_args, **_kwargs):
        return "#123456", 1.0


class _TakeoffService:
    @staticmethod
    def group_area_takeoffs_with_holes(takeoffs, _conditions):
        return list(takeoffs), {}

    @staticmethod
    def group_takeoffs_by_type(conditions, takeoffs):
        grouped = {}
        for takeoff in takeoffs:
            condition_type = conditions[takeoff.condition_uid].condition_type
            grouped.setdefault(condition_type, []).append(takeoff)
        return grouped
