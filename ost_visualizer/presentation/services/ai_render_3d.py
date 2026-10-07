import base64
from typing import List, Sequence
from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QBrush, QColor, QImage, QPainter, QPen, QPolygonF
from .ai_takeoff_crop_renderer import encode_png

TOP_VIEW_MAX_SIDE_PX = 1200
_LOW_COLOR = (70, 110, 200)
_HIGH_COLOR = (240, 120, 40)


def _color(z: float, z_min: float, z_max: float) -> QColor:
    t = 0.0 if z_max <= z_min else (z - z_min) / (z_max - z_min)
    return QColor(
        *(round(low + (high - low) * t) for low, high in zip(_LOW_COLOR, _HIGH_COLOR))
    )


def render_top_view(meshes: Sequence) -> dict:
    triangles: List[tuple] = []
    used = 0
    for mesh in meshes:
        if not mesh:
            continue
        used += 1
        vertices = mesh.vertices
        for a, b, c in mesh.faces:
            points = (vertices[a], vertices[b], vertices[c])
            triangles.append((max(point[2] for point in points), points))
    if not triangles:
        return {"image": None, "mesh_count": 0, "bbox_model": None, "z_range": None}
    xs = [point[0] for _z, points in triangles for point in points]
    ys = [point[1] for _z, points in triangles for point in points]
    zs = [z for z, _points in triangles]
    x_min, x_max, y_min, y_max = min(xs), max(xs), min(ys), max(ys)
    z_min, z_max = min(zs), max(zs)
    span = max(x_max - x_min, y_max - y_min, 1e-9)
    scale = TOP_VIEW_MAX_SIDE_PX / span
    width = max(1, round((x_max - x_min) * scale))
    height = max(1, round((y_max - y_min) * scale))
    stride = width * 4
    buffer = bytearray(b"\xff" * (stride * height))
    image = QImage(buffer, width, height, stride, QImage.Format.Format_ARGB32)
    painter = QPainter(image)
    painter.setPen(QPen(Qt.PenStyle.NoPen))
    triangles.sort(key=lambda item: item[0])
    for z, points in triangles:
        painter.setBrush(QBrush(_color(z, z_min, z_max)))
        painter.drawPolygon(
            QPolygonF(
                [
                    QPointF((x - x_min) * scale, (y_max - y) * scale)
                    for x, y, _z in points
                ]
            )
        )
    painter.end()
    png = encode_png(image)
    return {
        "image": {
            "png_base64": base64.b64encode(png).decode("ascii"),
            "width_px": width,
            "height_px": height,
        },
        "mesh_count": used,
        "bbox_model": [x_min, y_min, x_max, y_max],
        "z_range": [z_min, z_max],
        "px_to_model": [1.0 / scale, 0.0, 0.0, -1.0 / scale, x_min, y_max],
    }


class AiTopViewSource:
    def __init__(self, project_data, mesh_generator, inactive_object_color):
        self._project_data = project_data
        self._mesh_generator = mesh_generator
        self._inactive_object_color = inactive_object_color

    def snapshot(self) -> tuple:
        takeoffs = list(self._project_data.get_all_takeoffs())
        page_infos = {}
        for page_uid in {str(takeoff.page_uid) for takeoff in takeoffs}:
            page = self._project_data.get_page(page_uid)
            if page is None:
                continue
            page_infos[page_uid] = {
                "scale_factor1": float(page.scale_factor1 or 1.0),
                "scale_factor2": float(page.scale_factor2 or 1.0),
                "rotation": int(page.rotation or 0),
                "flip_x": bool(page.flip_x),
                "flip_y": bool(page.flip_y),
                "width": float(page.width_pts or 0.0),
                "height": float(page.height_pts or 0.0),
                "view_scale": 1.0,
            }
        return (
            takeoffs,
            dict(self._project_data.get_bid_conditions()),
            dict(self._project_data.get_page_area_selections()),
            page_infos,
            str(self._inactive_object_color()),
        )

    def render(self, snapshot: tuple) -> dict:
        takeoffs, conditions, page_areas, page_infos, inactive_color = snapshot
        if not takeoffs:
            return render_top_view([])
        meshes, _colors, _bounds = self._mesh_generator.generate_meshes(
            conditions,
            takeoffs,
            page_area_selections=page_areas,
            inactive_object_color=inactive_color,
            page_infos=page_infos,
        )
        return render_top_view(meshes)
