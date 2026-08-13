from typing import List, Optional
from ....application.interfaces.i_coordinate_transformer import ICoordinateTransformer
from ....domain.entities import shape as shapes
from ....domain.entities.condition import Condition
from ....domain.entities.takeoff import Takeoff
from ..core.boolean_operations import boolean_union
from ..core.geometry.takeoff_geometry import resolve_point_takeoff_shape
from ..core.mesh_generator import MeshData, MeshGenerator


class MeshFactory:
    def __init__(self, coord_system: ICoordinateTransformer) -> None:
        self.mesh_generator = MeshGenerator(coord_system)

    def create_mesh_for_takeoff(
        self,
        takeoff: Takeoff,
        condition: Condition,
        holes: Optional[List[List[tuple]]] = None,
    ) -> Optional[MeshData]:
        position = takeoff.position
        if not position:
            return None
        if condition.is_linear:
            return self._create_linear_mesh(takeoff, condition, position)
        if condition.is_area:
            return self._create_area_mesh(takeoff, condition, position, holes)
        if condition.is_count or condition.is_attachment:
            return self._create_count_mesh(takeoff, condition, position)
        return None

    def _create_linear_mesh(
        self,
        takeoff: Takeoff,
        condition: Condition,
        position: List[float],
    ) -> Optional[MeshData]:
        curve = takeoff.curve
        if curve >= 0 and len(position) >= 6:
            return self._create_curved_linear_mesh(takeoff, condition, position)
        if takeoff.has_valid_position:
            return self._create_straight_linear_mesh(takeoff, condition, position)
        return None

    def _create_straight_linear_mesh(
        self,
        takeoff,
        condition,
        position: List[float],
    ) -> Optional[MeshData]:
        x1, y1, x2, y2 = position[:4]
        height = max(condition.height if condition.height else 1, 1)
        thickness = max(condition.thickness if condition.thickness else 1, 1)
        z_offset = condition.z_value if condition.z_value else 0
        is_top = condition.is_top if condition.is_top else False
        if is_top:
            z_offset = z_offset - height
        rise = condition.rise if condition.rise else 0
        run = condition.run if condition.run else 0
        mesh = self.mesh_generator.generate_linear_mesh(
            x1,
            y1,
            x2,
            y2,
            height,
            thickness,
            z_offset,
            rise=rise if rise and run else None,
            run=run if rise and run else None,
        )
        if mesh and condition.drop_run and condition.drop_value:
            stub = self.mesh_generator.generate_drop_stub_mesh(
                x1,
                y1,
                x2,
                y2,
                thickness,
                condition.drop_value,
                z_offset,
                height,
                rise=rise if rise and run else None,
                run=run if rise and run else None,
            )
            if stub:
                return boolean_union(mesh, stub, mesh.metadata)
        return mesh

    def _create_curved_linear_mesh(
        self,
        takeoff,
        condition,
        position: List[float],
    ) -> Optional[MeshData]:
        if len(position) < 6:
            return None
        x1, y1, x2, y2, cx, cy = position[:6]
        height = max(condition.height if condition.height else 1, 1)
        thickness = max(condition.thickness if condition.thickness else 1, 1)
        z_offset = condition.z_value if condition.z_value else 0
        is_top = condition.is_top if condition.is_top else False
        if is_top:
            z_offset = z_offset - height
        rise = condition.rise if condition.rise else 0
        run = condition.run if condition.run else 0
        mesh = self.mesh_generator.generate_curved_mesh(
            x1,
            y1,
            x2,
            y2,
            cx,
            cy,
            height,
            thickness,
            z_offset,
            rise=rise if rise and run else None,
            run=run if rise and run else None,
            position=position,
        )
        if mesh and condition.drop_run and condition.drop_value:
            stub = self.mesh_generator.generate_curved_drop_stub_mesh(
                x1,
                y1,
                x2,
                y2,
                cx,
                cy,
                thickness,
                condition.drop_value,
                z_offset,
                height,
                rise=rise if rise and run else None,
                run=run if rise and run else None,
                position=takeoff.position,
            )
            if stub:
                return boolean_union(mesh, stub, mesh.metadata)
        return mesh

    def _create_area_mesh(
        self,
        takeoff: Takeoff,
        condition: Condition,
        position: List[float],
        holes: Optional[List[List[tuple]]] = None,
    ) -> Optional[MeshData]:
        thickness = max(condition.thickness if condition.thickness else 1, 1)
        if len(position) < 6:
            return None
        z_offset = condition.z_value if condition.z_value else 0
        is_top = condition.is_top if condition.is_top else False
        if is_top:
            z_offset = z_offset - thickness
        rise = condition.rise if condition.rise else 0
        run = condition.run if condition.run else 0
        rotation = takeoff.rotation
        vertices = [
            (position[j], position[j + 1])
            for j in range(0, len(position), 2)
            if j + 1 < len(position)
        ]
        if len(vertices) < 3:
            return None
        return self.mesh_generator.generate_area_mesh(
            vertices,
            thickness,
            z_offset,
            holes=holes,
            rise=rise if rise and run else None,
            run=run if rise and run else None,
            rotation=rotation,
        )

    def _create_count_mesh(
        self,
        takeoff: Takeoff,
        condition: Condition,
        position: List[float],
    ) -> Optional[MeshData]:
        if len(position) < 2:
            return None
        x, y = position[:2]
        shape_id, width, depth = resolve_point_takeoff_shape(condition)
        height = max(condition.height if condition.height else 1, 1)
        if condition.is_count:
            scale = max(condition.display_size, 0.1) / 100.0
            height *= scale
        z_offset = condition.z_value if condition.z_value else 0
        is_top = condition.is_top if condition.is_top else False
        if is_top:
            z_offset = z_offset - height
        rotation = takeoff.rotation
        spec = shapes.ShapeSpec(shape_id, width, depth, rotation)
        return self._generate_count_mesh_from_spec(x, y, height, z_offset, spec)

    def _generate_count_mesh_from_spec(
        self,
        x: float,
        y: float,
        height: float,
        z_offset: float,
        spec: shapes.ShapeSpec,
    ) -> Optional[MeshData]:
        if spec.shape_id == shapes.CIRCLE:
            return self.mesh_generator.generate_cylinder_mesh(
                x, y, spec.width, height, z_offset, spec.rotation
            )
        if spec.shape_id == shapes.ELLIPSE:
            return self.mesh_generator.generate_elliptical_cylinder_mesh(
                x, y, spec.width, spec.depth, height, z_offset, spec.rotation
            )
        if spec.shape_id == shapes.RHOMBUS:
            return self.mesh_generator.generate_rhombus_prism_mesh(
                x, y, spec.width, height, z_offset, spec.rotation
            )
        if spec.shape_id == shapes.TRIANGLE:
            return self.mesh_generator.generate_isosceles_triangle_prism_mesh(
                x, y, spec.width, spec.depth, height, z_offset, spec.rotation
            )
        if spec.is_polygon:
            sides, angle_offset = spec.polygon_params
            return self.mesh_generator.generate_polygon_prism_mesh(
                x, y, spec.width, height, sides, z_offset, spec.rotation, angle_offset
            )
        return self.mesh_generator.generate_count_mesh(
            x, y, spec.width, spec.depth, height, z_offset, spec.rotation
        )
