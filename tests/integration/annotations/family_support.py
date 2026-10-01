import unittest
from PySide6 import QtCore, QtWidgets
from ost_visualizer.domain.entities.annotation import BidAnnotation
from ost_visualizer.infrastructure.mdb.components.serialization import (
    serialize_position_for_table,
    parse_position_storage,
)
from ost_visualizer.domain.services.page_scale_transform import (
    rescale_annotation_position_between_page_scales,
)
from ost_visualizer.presentation.visualization.pdf.renderers.annotation_renderer import (
    calculate_dimension_geometry,
    format_dimension_distance,
)
import tests.integration.placement.test_annotation_keyboard as qt_fixtures


class _PlanFixture:
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def make_view(self, detached=False):
        fixture = qt_fixtures.AnnotationPlacementKeyboardTests()
        fixture.app = self.app
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        return fixture.make_view(detached=detached)


from tests.helpers.annotation_geometry import ANNOTATION_POSITIONS


class AnnotationFamilyGeometry:
    POSITIONS = ANNOTATION_POSITIONS
