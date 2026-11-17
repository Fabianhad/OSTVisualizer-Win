import json
from pathlib import Path
from ost_visualizer.domain.entities import shape as shapes
from ost_visualizer.domain.entities.condition import Condition
from ost_visualizer.domain.entities.config import Config
from ost_visualizer.domain.entities.takeoff import Takeoff
from ost_visualizer.domain.services.takeoff_service_impl import TakeoffDomainService
from ost_visualizer.presentation.visualization.exporters.dxf_exporter import DXFExporter
from ost_visualizer.presentation.visualization.exporters.obj_exporter import OBJExporter
from ost_visualizer.presentation.visualization.renderers.threejs.threejs_renderer import (
    visualize_with_threejs,
)
from ost_visualizer.presentation.visualization.services.color_service import (
    ColorService,
)
from tests.presentation.visualization.renderers.threejs.export_support import (
    _IdentityMeshCoordinateSystem,
)

POSITIVE_SPAN = (-10.0, 10.0)
SAME_TYPE_CUT_SPAN = (-10.0, 0.0)
SURVIVOR_SPAN = (190.0, 210.0)


def _box_condition(uid, condition_type, size=20.0, height=10.0, z_value=0.0):
    condition = Condition(
        uid=uid,
        name=uid,
        condition_type=condition_type,
        shape=shapes.SQUARE,
        width=size,
        depth=size,
        height=height,
        display_size=100.0,
    )
    condition.z_value = z_value
    return condition


def boolean_rule_conditions():
    return {
        "count": _box_condition("count", Condition.TYPE_COUNT),
        "attachment": _box_condition("attachment", Condition.TYPE_ATTACHMENT),
        "count_block": _box_condition(
            "count_block", Condition.TYPE_COUNT, size=60.0, height=30.0, z_value=-10.0
        ),
    }


def _takeoff(uid, condition_uid, x, is_negative=False):
    return Takeoff(
        uid=uid,
        condition_uid=condition_uid,
        position=[x, 0.0],
        is_negative=is_negative,
    )


def other_type_negative_takeoffs():
    return [
        _takeoff("positive", "count", 0.0),
        _takeoff("negative", "attachment", 10.0, is_negative=True),
    ]


def same_type_negative_takeoffs():
    return [
        _takeoff("positive", "count", 0.0),
        _takeoff("negative", "count", 10.0, is_negative=True),
    ]


def consumed_positive_takeoffs():
    return [
        _takeoff("consumed", "count", 0.0),
        _takeoff("survivor", "count", 200.0),
        _takeoff("negative", "count_block", 0.0, is_negative=True),
    ]


def negative_only_takeoffs():
    return [_takeoff("negative", "count", 0.0, is_negative=True)]


def export_obj(takeoffs, output_path):
    return OBJExporter(
        _IdentityMeshCoordinateSystem(), ColorService(), TakeoffDomainService()
    ).export(
        boolean_rule_conditions(),
        takeoffs,
        str(output_path),
        inactive_object_color=Config.DEFAULT_INACTIVE_OBJECT_COLOR,
    )


def export_dxf(takeoffs, output_path):
    return DXFExporter(
        _IdentityMeshCoordinateSystem(), ColorService(), TakeoffDomainService()
    ).export(
        boolean_rule_conditions(),
        takeoffs,
        str(output_path),
        inactive_object_color=Config.DEFAULT_INACTIVE_OBJECT_COLOR,
    )


def export_html(takeoffs, output_path):
    return visualize_with_threejs(
        boolean_rule_conditions(),
        takeoffs,
        _IdentityMeshCoordinateSystem(),
        ColorService(),
        TakeoffDomainService(),
        output_path=str(output_path),
        auto_open=False,
        pages=[],
        inactive_object_color=Config.DEFAULT_INACTIVE_OBJECT_COLOR,
        include_elevation_callouts=False,
    )


def obj_x_span(path):
    xs = [
        float(line.split()[1])
        for line in Path(path).read_text().splitlines()
        if line.startswith("v ")
    ]
    return (min(xs), max(xs))


def dxf_x_span(path):
    lines = [line.strip() for line in Path(path).read_text().splitlines()]
    xs = []
    in_line = False
    for code, value in zip(lines[0::2], lines[1::2]):
        if code == "0":
            in_line = value == "LINE"
        elif in_line and code in ("10", "11"):
            xs.append(float(value))
    return (min(xs), max(xs))


def html_x_spans(path):
    text = Path(path).read_text(encoding="utf-8")
    scene = json.loads(
        text.split('<script type="application/json" id="scene-data">', 1)[1].split(
            "</script>", 1
        )[0]
    )
    spans = {}
    for geometry in scene["geometries"]:
        xs = geometry["vertices"][0::3]
        spans[geometry["takeoff_uid"]] = (min(xs), max(xs))
    return spans
