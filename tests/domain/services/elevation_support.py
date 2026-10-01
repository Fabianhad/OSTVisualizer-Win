from ost_visualizer.domain.entities.condition import Condition
from ost_visualizer.domain.entities.takeoff import Takeoff

_EXPECTED_PDF_CALLOUT_LINES = ["F9", "10' - 0\"", "8' - 0\"", "5.14 CY"]


def _outer_ring(outer_ring=None):
    if outer_ring is None:
        outer_ring = (
            (10.0, 20.0),
            (50.0, 20.0),
            (50.0, 60.0),
            (10.0, 60.0),
        )
    return tuple(outer_ring)


def _area_condition(**overrides):
    values = {
        "uid": "condition-1",
        "name": "F9 @T 10' 0\"",
        "condition_type": Condition.TYPE_AREA,
        "thickness": 24.0,
        "z_value": 120.0,
        "is_top": True,
    }
    values.update(overrides)
    return Condition(**values)


def _area_takeoff(**overrides):
    values = {
        "uid": "takeoff-1",
        "condition_uid": "condition-1",
        "page_uid": "page-1",
        "area_uid": "area-1",
        "position": [0.0, 0.0, 100.0, 0.0, 100.0, 100.0, 0.0, 100.0],
    }
    values.update(overrides)
    return Takeoff(**values)


class _CapturingPdfWriter:
    def __init__(self):
        self.pages = []

    def merge_pages_with_annotations(self, pages, _output_path):
        self.pages = list(pages)
        return True

    def get_last_error(self):
        return ""
